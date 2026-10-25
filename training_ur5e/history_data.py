"""Episode-wise split and causal history for the fixed-scene UR5e experiment."""
import json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import torch

from common import JOINTS


def features(history):
    names = [f't-{history - 1 - i}:{joint}' for i in range(history) for joint in JOINTS]
    return {
        'observation.state': {'dtype': 'float32', 'shape': (7,), 'names': JOINTS},
        'observation.environment_state': {'dtype': 'float32', 'shape': (history * 7 + 1,),
                                          'names': names + ['elapsed_seconds_scaled']},
        'action': {'dtype': 'float32', 'shape': (7,), 'names': JOINTS},
    }


def environment(history, elapsed, time_scale):
    return np.concatenate((np.asarray(history, dtype=np.float32).reshape(-1),
                           [min(max(elapsed, 0), time_scale) / time_scale])).astype(np.float32)


def stage_labels(action):
    closed = action[:, 6] >= .23
    seen_close = np.maximum.accumulate(closed)
    # Measured/task success is unknown: these are command phases, not success labels.
    return np.where(closed, 'carry', np.where(seen_close, 'release', 'approach'))


def load_episodes(cfg):
    files = sorted((Path(cfg['dataset_root']) / 'data').rglob('episode_*.parquet'))
    result = []
    for file in files:
        d = pq.read_table(file, columns=['observation.state', 'action', 'episode_index']).to_pydict()
        state = np.asarray(d['observation.state'], dtype=np.float32)
        action = np.asarray(d['action'], dtype=np.float32)
        if not np.isfinite(state).all() or not np.isfinite(action).all():
            raise ValueError(f'Nonfinite values in {file}')
        changes = np.flatnonzero((np.max(np.abs(np.diff(action[:, :6], axis=0)), axis=1) > .005) |
                                  (np.abs(np.diff(action[:, 6])) > .05)) + 1
        if not len(changes):
            raise ValueError(f'No command transitions in {file}')
        # Keep a second of pre-roll and five seconds after the final transition;
        # the four-second gripper trajectory must not be trimmed away.
        start = max(0, int(changes[0]) - cfg['fps'])
        end = min(len(state), int(changes[-1]) + 5 * cfg['fps'] + 1)
        result.append({'id': int(d['episode_index'][0]), 'state': state[start:end],
                       'action': action[start:end], 'stages': stage_labels(action)[start:end],
                       'source_frames': len(state), 'start_frame': start, 'end_frame': end,
                       'source': str(file)})
    if len(result) < 4:
        raise ValueError('Need at least four episodes for episode-wise evaluation.')
    return result


def split(episodes, cfg):
    ids = sorted(ep['id'] for ep in episodes)
    # Fixed before fitting this variant. Old models saw all episodes; see report.
    rng = np.random.default_rng(cfg['seed'])
    validation = sorted(int(x) for x in rng.choice(ids, size=cfg['validation_episodes'], replace=False))
    return [ep for ep in episodes if ep['id'] not in validation], [ep for ep in episodes if ep['id'] in validation]


def observation_at(ep, index, cfg):
    indices = np.maximum(0, index - np.arange(cfg['history_frames'] - 1, -1, -1))
    return {'observation.state': ep['state'][index],
            'observation.environment_state': environment(ep['state'][indices],
                index / cfg['fps'], cfg['time_scale_seconds'])}


def stats_for(episodes, cfg):
    values = {key: [] for key in features(cfg['history_frames'])}
    for ep in episodes:
        for i in range(len(ep['state'])):
            obs = observation_at(ep, i, cfg)
            for key, value in obs.items():
                values[key].append(value)
        target = ep['action'].copy()
        if cfg.get('action_representation') == 'delta_from_current':
            target -= ep['state']
        elif cfg.get('action_representation') == 'arm_delta_gripper_absolute':
            target[:, :6] -= ep['state'][:, :6]
        values['action'].extend(target)
    stats = {}
    for key, rows in values.items():
        a = np.asarray(rows, dtype=np.float32)
        # Do not amplify simulation noise on virtually stationary joints.
        # LeRobot clones Tensor statistics, while NumPy statistics can share
        # storage between normalization modules and lose keys during saving.
        stats[key] = {k: torch.tensor(v.copy()) for k, v in {
            'mean': a.mean(axis=0), 'std': np.maximum(a.std(axis=0), .02),
            'min': a.min(axis=0), 'max': a.max(axis=0)}.items()}
    return stats


def batch_at(episodes, episode_indices, frame_indices, cfg, device='cpu'):
    rows = []
    for e, i in zip(episode_indices, frame_indices):
        ep = episodes[e]
        row = observation_at(ep, int(i), cfg)
        future = int(i) + np.arange(cfg['chunk_size'])
        row['action_is_pad'] = future >= len(ep['action'])
        row['action'] = ep['action'][np.minimum(future, len(ep['action']) - 1)]
        if cfg.get('action_representation') == 'delta_from_current':
            row['action'] = row['action'] - ep['state'][int(i)]
        elif cfg.get('action_representation') == 'arm_delta_gripper_absolute':
            row['action'] = row['action'].copy()
            row['action'][:, :6] -= ep['state'][int(i), :6]
        rows.append(row)
    return {key: torch.as_tensor(np.stack([r[key] for r in rows]), device=device)
            for key in rows[0]}


def predict(policy, observations):
    normalized = policy.normalize_inputs(observations)
    return policy.unnormalize_outputs({'action': policy.model(normalized)[0]})['action']


def evaluate(policy, episodes, cfg, baseline=False):
    details = []
    policy.eval()
    with torch.inference_mode():
        for ep in episodes:
            for stage in ('approach', 'carry', 'release'):
                candidates = np.flatnonzero(ep['stages'] == stage)
                if not len(candidates):
                    continue
                indices = candidates[np.unique(np.linspace(0, len(candidates) - 1,
                                                min(24, len(candidates)), dtype=int))]
                obs_rows = [observation_at(ep, int(i), cfg) for i in indices]
                obs = {key: torch.tensor(np.stack([r[key] for r in obs_rows]))
                       for key in obs_rows[0]}
                if baseline:
                    obs['observation.environment_state'] = obs['observation.state'].clone()
                output = predict(policy, obs).cpu().numpy()
                if not baseline and cfg.get('action_representation') == 'delta_from_current':
                    output += obs['observation.state'].numpy()[:, None, :]
                elif not baseline and cfg.get('action_representation') == 'arm_delta_gripper_absolute':
                    output[:, :, :6] += obs['observation.state'].numpy()[:, None, :6]
                # Match actual n_action_steps=4; never cross episode boundaries.
                for row, i in enumerate(indices):
                    for h in range(min(cfg['n_action_steps'], len(output[row]), len(ep['action']) - i)):
                        target = ep['action'][i + h]
                        current = ep['state'][i]
                        details.append({'episode': ep['id'], 'frame': int(i + h), 'phase': stage,
                            'teacher': target.tolist(), 'prediction': output[row, h].tolist(),
                            'state': current.tolist(),
                            'active': bool(np.max(np.abs(target[:6] - current[:6])) > .01),
                            'gripper_transition': bool(abs(target[6] - current[6]) > .08),
                            'closing': bool(target[6] >= .4 and current[6] < .3)})
    groups = {}
    for name in ['all', 'active', 'gripper_transition', 'closing'] + ['approach', 'carry', 'release']:
        selected = [r for r in details if name == 'all' or
                    (name in ('active', 'gripper_transition', 'closing') and r.get(name, False)) or r['phase'] == name]
        if not selected:
            continue
        p = np.array([r['prediction'] for r in selected])
        a = np.array([r['teacher'] for r in selected])
        s = np.array([r['state'] for r in selected])
        groups[name] = {'samples': len(selected),
            'arm_rmse_rad': float(np.sqrt(np.mean((p[:, :6] - a[:, :6]) ** 2))),
            'gripper_rmse_rad': float(np.sqrt(np.mean((p[:, 6] - a[:, 6]) ** 2))),
            'gripper_disagreement': float(np.mean((p[:, 6] > .23) != (a[:, 6] > .23))),
            'hold_pose_arm_rmse_rad': float(np.sqrt(np.mean((s[:, :6] - a[:, :6]) ** 2)))}
    return groups, details


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

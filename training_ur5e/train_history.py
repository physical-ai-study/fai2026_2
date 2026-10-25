"""Train a compact ACT with causal history and fixed-task elapsed time; evaluate by episode."""
import argparse
import json
from pathlib import Path
import random
import time
import numpy as np
import torch
import yaml
from lerobot.common.datasets.utils import dataset_to_policy_features
from lerobot.common.policies.act.configuration_act import ACTConfig
from lerobot.common.policies.act.modeling_act import ACTPolicy
from lerobot.configs.types import FeatureType, NormalizationMode
from common import JOINTS
from history_data import (batch_at, evaluate, features, load_episodes, save_json, split, stats_for)
from swing_training import evaluate_swing, swing_windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).with_name('history_config.yaml')))
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    if cfg.get('swing_balanced_sampling', False):
        probabilities = [cfg['swing_turn_sample_probability'], cfg['swing_late_sample_probability']]
        if any(p < 0 for p in probabilities) or sum(probabilities) > 1:
            raise ValueError('Swing sampling probabilities must be nonnegative and sum to at most 1.')
        if not 0 <= cfg['swing_start_fraction'] < 1 or not 0 <= cfg['swing_joint_index'] < 6:
            raise ValueError('Invalid swing start fraction or arm joint index.')
        if cfg['swing_reversal_threshold_rad'] <= 0 or cfg['swing_controller_tau_seconds'] <= 0:
            raise ValueError('Swing reversal threshold and controller time constant must be positive.')
    torch.set_num_threads(cfg['torch_threads'])
    torch.manual_seed(cfg['seed'])
    np.random.seed(cfg['seed'])
    random.seed(cfg['seed'])
    output = Path(cfg['output_directory'])
    train, validation = split(load_episodes(cfg), cfg)
    output.mkdir(parents=True, exist_ok=False)
    save_json(output / 'data_split.json', {
        'train': [ep['id'] for ep in train], 'validation': [ep['id'] for ep in validation],
        'windows': [{k: v for k, v in ep.items() if k not in ('state', 'action', 'stages')}
                    for ep in train + validation],
        'note': 'New model uses only train for fitting/statistics. Baseline saw all episodes; '
                'validation is used for model selection, not an untouched final test.'})
    stats = stats_for(train, cfg)
    ft = dataset_to_policy_features(features(cfg['history_frames']))
    policy_cfg = ACTConfig(input_features={k: v for k, v in ft.items() if v.type != FeatureType.ACTION},
        output_features={'action': ft['action']}, chunk_size=cfg['chunk_size'],
        n_action_steps=cfg['n_action_steps'], dim_model=128, n_heads=4, dim_feedforward=512,
        n_encoder_layers=2, n_decoder_layers=1, use_vae=False, pretrained_backbone_weights=None,
        normalization_mapping={k: NormalizationMode.MEAN_STD for k in ('VISUAL', 'STATE', 'ENV', 'ACTION')})
    model = ACTPolicy(policy_cfg, dataset_stats=stats)
    baseline_metrics, baseline_rows = {}, []
    if cfg.get('baseline_model'):
        baseline = ACTPolicy.from_pretrained(cfg['baseline_model']).eval()
        baseline_metrics, baseline_rows = evaluate(baseline, validation, cfg, baseline=True)
        del baseline
    save_json(output / 'baseline_metrics.json', baseline_metrics)
    save_json(output / 'baseline_predictions.json', baseline_rows)
    print('BASELINE', json.dumps(baseline_metrics), flush=True)
    metadata = dict(cfg, joint_order=JOINTS, architecture='history_elapsed_act_v1',
                    baseline_comparison='Historical baseline is optional and may have seen evaluation episodes; '
                                        'it is not a held-out comparison.')
    save_json(output / 'history_training_config.json', metadata)
    weights = []
    phase_candidates = []
    swing_candidates = []
    for ep in train:
        active = (np.max(np.abs(ep['action'][:, :6] - ep['state'][:, :6]), axis=1) > .01) | (
                  np.abs(ep['action'][:, 6] - ep['state'][:, 6]) > .03)
        w = 1 + 3 * active.astype(float)
        weights.append(w / w.sum())
        if cfg.get('swing_balanced_sampling', False):
            late, turns, _ = swing_windows(ep, cfg)
            swing_candidates.append((late, turns))
        if cfg.get('transition_balanced_sampling', False):
            masks = [ep['stages'] == 'approach',
                     (ep['action'][:, 6] >= .4) & (ep['state'][:, 6] < .3),
                     (ep['stages'] == 'carry') & (ep['state'][:, 6] >= .3),
                     (ep['action'][:, 6] < .1) & (ep['state'][:, 6] > .15),
                     ep['stages'] == 'release']
            phase_candidates.append([np.flatnonzero(mask) for mask in masks if np.any(mask)])
        else:
            phase_candidates.append([np.flatnonzero(ep['stages'] == phase)
                for phase in ('approach', 'carry', 'release') if np.any(ep['stages'] == phase)])
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg['learning_rate'], weight_decay=.0001)
    rng = np.random.default_rng(cfg['seed'])
    best = float('inf')
    best_step = None
    started = time.monotonic()
    with (output / 'training.jsonl').open('w') as log:
        for step in range(1, cfg['training_steps'] + 1):
            es = rng.integers(0, len(train), cfg['batch_size'])
            frames = []
            for e in es:
                if cfg.get('swing_balanced_sampling', False):
                    late, turns = swing_candidates[e]
                    draw = rng.random()
                    if draw < cfg['swing_turn_sample_probability'] and len(turns):
                        frames.append(rng.choice(turns))
                        continue
                    if draw < cfg['swing_turn_sample_probability'] + cfg['swing_late_sample_probability']:
                        frames.append(rng.choice(late))
                        continue
                if cfg.get('phase_balanced_sampling', False):
                    candidates = phase_candidates[e][rng.integers(len(phase_candidates[e]))]
                    w = weights[e][candidates]
                    frames.append(rng.choice(candidates, p=w / w.sum()))
                else:
                    frames.append(rng.choice(len(train[e]['state']), p=weights[e]))
            batch = batch_at(train, es, frames, cfg)
            if cfg.get('state_offset_augmentation_std_rad', 0) > 0:
                # Coherently shift current pose and history, keeping absolute
                # expert targets unchanged. Residual targets must shift back.
                # This teaches recovery from small pose offsets, not physics.
                noise = torch.randn((len(es), 6)) * cfg['state_offset_augmentation_std_rad']
                noise = noise.clamp(-.1, .1)
                batch['observation.state'][:, :6] += noise
                history_view = batch['observation.environment_state'][:, :-1].reshape(
                    len(es), cfg['history_frames'], 7)
                history_view[:, :, :6] += noise[:, None, :]
                if cfg['action_representation'] in ('delta_from_current', 'arm_delta_gripper_absolute'):
                    batch['action'][:, :, :6] -= noise[:, None, :]
            model.train()
            if cfg.get('first_action_weight', 1) > 1:
                normalized_obs = model.normalize_inputs(batch)
                predicted = model.model(normalized_obs)[0]
                target = model.normalize_targets(batch)['action']
                horizon_weights = torch.ones(cfg['chunk_size'])
                horizon_weights[:cfg['n_action_steps']] = cfg['first_action_weight']
                mask = (~batch['action_is_pad']).float() * horizon_weights
                joint_weights = torch.tensor(cfg.get('action_loss_joint_weights', [1.] * 7),
                                             dtype=predicted.dtype, device=predicted.device)
                error = (torch.abs(predicted - target) * joint_weights).sum(dim=-1) / joint_weights.sum()
                loss = (error * mask).sum() / mask.sum().clamp_min(1)
            else:
                loss, _ = model.forward(batch)
            if not torch.isfinite(loss):
                raise RuntimeError('Nonfinite loss.')
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            record = {'step': step, 'train_loss': float(loss.detach()),
                      'elapsed_seconds': round(time.monotonic() - started, 1)}
            if step == 1 or step % 50 == 0:
                print(json.dumps(record), flush=True)
            if step % cfg['eval_every'] == 0 or step == cfg['training_steps']:
                metrics, rows = evaluate(model, validation, cfg)
                # Score moving frames as well as full sequence to avoid selecting identity predictions.
                score = metrics.get('active', metrics['all'])['arm_rmse_rad'] + metrics['all']['gripper_rmse_rad']
                if cfg.get('score_gripper_transition', False):
                    score += metrics.get('gripper_transition', metrics['all'])['gripper_rmse_rad']
                if cfg.get('swing_balanced_sampling', False):
                    swing = evaluate_swing(model, validation, cfg)
                    metrics['swing'] = swing
                    # Gripper quality remains in the objective, but no longer
                    # dominates selection at the expense of late arm motion.
                    score = (metrics.get('active', metrics['all'])['arm_rmse_rad']
                             + .25 * metrics['all']['gripper_rmse_rad']
                             + .25 * metrics.get('gripper_transition', metrics['all'])['gripper_rmse_rad']
                             + cfg['swing_score_amplitude_weight'] * swing['amplitude_relative_error']
                             + cfg['swing_score_reversal_weight'] * swing['reversal_count_error']
                             + cfg['swing_score_tracking_weight'] * swing['rollout_joint_rmse_rad'])
                record['validation'] = metrics
                record['selection_score'] = score
                print('VALIDATION', json.dumps(record), flush=True)
                if score < best:
                    best, best_step = score, step
                    model.save_pretrained(output / 'best')
                    save_json(output / 'best' / 'history_training_config.json', dict(metadata, best_step=step))
                    save_json(output / 'best_metrics.json', metrics)
                    save_json(output / 'best_predictions.json', rows)
            log.write(json.dumps(record) + '\n')
            log.flush()
    model.save_pretrained(output / 'last')
    save_json(output / 'last' / 'history_training_config.json', dict(metadata, best_step=cfg['training_steps']))
    save_json(output / 'summary.json', {'best_step': best_step, 'selection_score': best,
              'elapsed_seconds': time.monotonic() - started, 'baseline_metrics': baseline_metrics,
              'best_metrics': json.loads((output / 'best_metrics.json').read_text()),
              'gazebo_success_rate': 'not measured'})
    print(f'FINISHED: {output}/best', flush=True)


if __name__ == '__main__':
    main()

"""Late motion sampling and an explicitly approximate closed-loop validation."""
import numpy as np
import torch

from common import LOWER, UPPER
from history_data import environment, predict


def turning_points(values, threshold):
    """Return confirmed interior extrema, ignoring sub-threshold noise."""
    direction = 0
    low = high = float(values[0])
    li = hi = 0
    turns = []
    for i, value in enumerate(values):
        if direction == 0:
            if value < low:
                low, li = float(value), i
            if value > high:
                high, hi = float(value), i
            if value - low >= threshold:
                direction, high, hi = 1, float(value), i
            elif high - value >= threshold:
                direction, low, li = -1, float(value), i
        elif direction == 1:
            if value > high:
                high, hi = float(value), i
            elif high - value >= threshold:
                turns.append(hi)
                direction, low, li = -1, float(value), i
        else:
            if value < low:
                low, li = float(value), i
            elif value - low >= threshold:
                turns.append(li)
                direction, high, hi = 1, float(value), i
    return turns


def swing_windows(ep, cfg):
    n = len(ep['state'])
    start = int(n * cfg['swing_start_fraction'])
    joint = cfg['swing_joint_index']
    turns = [start + i for i in turning_points(
        ep['action'][start:, joint], cfg['swing_reversal_threshold_rad'])]
    mask = np.zeros(n, dtype=bool)
    radius = round(cfg['swing_turn_window_seconds'] * cfg['fps'])
    for i in turns:
        mask[max(start, i - radius):min(n, i + radius + 1)] = True
    return np.arange(start, n), np.flatnonzero(mask), turns


def evaluate_swing(policy, episodes, cfg):
    """Roll out from a recorded late pose with a first-order controller surrogate.

    No measured future states are fed back after the initial seed. This is a
    selection diagnostic, NOT a Gazebo grasp/dynamics or success-rate test.
    """
    policy.eval()
    rows = []
    joint = cfg['swing_joint_index']
    dt = 1 / cfg['fps']
    alpha = 1 - np.exp(-dt / cfg['swing_controller_tau_seconds'])
    with torch.inference_mode():
        for ep in episodes:
            late, _, _ = swing_windows(ep, cfg)
            start = int(late[0])
            count = cfg['history_frames']
            history = [ep['state'][max(0, start - count + 1 + k)].copy()
                       for k in range(count)]
            state = history[-1].copy()
            simulated, targets = [], []
            i = start
            while i < len(ep['state']):
                obs = {'observation.state': torch.tensor(state[None, :]),
                       'observation.environment_state': torch.tensor(environment(
                           history[-count:], i / cfg['fps'], cfg['time_scale_seconds'])[None, :])}
                chunk = predict(policy, obs)[0].cpu().numpy()
                if cfg['action_representation'] == 'arm_delta_gripper_absolute':
                    chunk[:, :6] += state[None, :6]
                elif cfg['action_representation'] == 'delta_from_current':
                    chunk += state[None, :]
                for action in chunk[:cfg['n_action_steps']]:
                    if i >= len(ep['state']):
                        break
                    target = np.clip(action[:6], np.maximum(LOWER[:6], state[:6] - .2),
                                     np.minimum(UPPER[:6], state[:6] + .2))
                    simulated.append(state.copy())
                    targets.append(action.copy())
                    state = state.copy()
                    state[:6] += alpha * (target - state[:6])
                    state[6] += alpha * (np.clip(action[6], 0, .455) - state[6])
                    history.append(state.copy())
                    history = history[-count:]
                    i += 1
            actual = np.asarray(simulated)
            teacher = ep['state'][start:]
            teacher_amp = float(np.ptp(teacher[:, joint]))
            predicted_amp = float(np.ptp(actual[:, joint]))
            true_turns = turning_points(teacher[:, joint], cfg['swing_reversal_threshold_rad'])
            pred_turns = turning_points(actual[:, joint], cfg['swing_reversal_threshold_rad'])
            rows.append({'episode': ep['id'], 'start_frame': start,
                         'teacher_amplitude_rad': teacher_amp,
                         'rollout_amplitude_rad': predicted_amp,
                         'amplitude_relative_error': abs(predicted_amp - teacher_amp) / max(teacher_amp, .1),
                         'teacher_reversals': len(true_turns), 'rollout_reversals': len(pred_turns),
                         'reversal_count_error': abs(len(true_turns) - len(pred_turns)),
                         'rollout_joint_rmse_rad': float(np.sqrt(np.mean(
                             (actual[:, joint] - teacher[:, joint]) ** 2))),
                         'teacher_turn_frames': [start + t for t in true_turns],
                         'rollout_turn_frames': [start + t for t in pred_turns]})
    keys = ('amplitude_relative_error', 'reversal_count_error', 'rollout_joint_rmse_rad')
    return dict({key: float(np.mean([r[key] for r in rows])) for key in keys},
                episodes=rows, evaluation='late-seeded first-order surrogate; not Gazebo')

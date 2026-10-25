"""Convert recorded UR5e episodes to local LeRobot v2.1; never overwrite."""
import argparse
import json
from pathlib import Path
import re

import numpy as np
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore

from common import (ARM, ARM_TOPIC, FEATURES, GRIPPER, GRIP_TOPIC, JOINTS, LOWER, UPPER,
                    load_config, ordered, valid_state)


def episode_key(path):
    return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', str(path))]


def read_episode(path, cfg):
    store = get_typestore(Stores.ROS2_HUMBLE)
    states, arms, grips = [], [], []
    last_clock = None
    grip_tolerance = float(cfg.get('gripper_feedback_tolerance_rad', 0.0))
    if not 0.0 <= grip_tolerance <= 0.02:
        raise ValueError('gripper_feedback_tolerance_rad must be between 0 and 0.02.')
    corrected_grip_values = []
    with Reader(path) as reader:
        connections = [c for c in reader.connections if c.topic in
                       ('/joint_states', ARM_TOPIC, GRIP_TOPIC, '/clock')]
        for connection, stamp, raw in reader.messages(connections=connections):
            msg = store.deserialize_cdr(raw, connection.msgtype)
            if connection.topic == '/clock':
                clock = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
                if last_clock is not None and clock < last_clock:
                    raise ValueError(f'{path}: simulation time reset inside episode.')
                last_clock = clock
            elif connection.topic == '/joint_states':
                value = ordered(msg.name, msg.position, JOINTS)
                # Opt-in handling for small measured overshoot; never alter commands.
                if (not LOWER[6] <= value[6] <= UPPER[6] and
                        LOWER[6] - grip_tolerance <= value[6] <= UPPER[6] + grip_tolerance):
                    corrected_grip_values.append(value[6])
                    value[6] = min(UPPER[6], max(LOWER[6], value[6]))
                if not valid_state(value):
                    details = ', '.join(
                        f'{name}={x:.6f} (allowed {lo:.6f}..{hi:.6f})'
                        for name, x, lo, hi in zip(JOINTS, value, LOWER, UPPER)
                        if not lo <= x <= hi)
                    raise ValueError(f'{path}: joint feedback outside limits: {details}')
                states.append((stamp, value))
            else:
                if not msg.points:
                    raise ValueError(f'{path}: empty trajectory.')
                wanted = ARM if connection.topic == ARM_TOPIC else [GRIPPER]
                value = ordered(msg.joint_names, msg.points[-1].positions, wanted)
                (arms if connection.topic == ARM_TOPIC else grips).append((stamp, value))
    if len(states) < 2 or not arms or not grips:
        raise ValueError(f'{path}: needs joint states, arm commands AND gripper commands.')
    gaps = np.diff([t for t, _ in states]) / 1e9
    if gaps.max() > cfg['max_state_gap_seconds']:
        raise ValueError(f'{path}: joint feedback gap {gaps.max():.2f}s; inspect recording.')
    step = round(1e9 / cfg['fps'])
    times = np.arange(states[0][0], states[-1][0] + 1, step, dtype=np.int64)
    if len(times) < cfg['chunk_size']:
        raise ValueError(f'{path}: too short for action chunk.')

    def hold(messages, initial):
        # A known initial measured pose seeds the period before the first command.
        # Never use a future command to fill the beginning of an episode.
        seed_time = min(states[0][0], messages[0][0]) - 1
        ts = np.array([seed_time] + [t for t, _ in messages], dtype=np.int64)
        vals = np.asarray([initial] + [v for _, v in messages], dtype=np.float32)
        indices = np.searchsorted(ts, times, side='right') - 1
        return vals[indices]

    observation = hold(states, states[0][1])
    actions = np.concatenate((hold(arms, states[0][1][:6]),
                              hold(grips, states[0][1][6:])), axis=1)
    if not all(valid_state(row) for row in actions):
        raise ValueError(f'{path}: command outside UR5e joint limits.')
    report = {'source': str(path), 'frames': len(times),
              'duration_seconds': float((times[-1] - times[0]) / 1e9),
              'arm_commands': len(arms), 'gripper_commands': len(grips),
              'gripper_feedback_corrections': len(corrected_grip_values),
              'corrected_gripper_raw_range': ([min(corrected_grip_values), max(corrected_grip_values)]
                                              if corrected_grip_values else None),
              'initial_action': 'measured initial joint state before first command'}
    return observation, actions, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--inspect', action='store_true', help='Read bags only; create nothing.')
    args = parser.parse_args()
    cfg = load_config(args.config)
    paths = sorted({p.parent for p in Path(cfg['bag_dir']).rglob('metadata.yaml')},
                   key=episode_key)
    if not paths:
        raise FileNotFoundError(cfg['bag_dir'])
    root = Path(cfg['dataset_root'])
    if root.exists() and not args.inspect:
        raise FileExistsError(f'{root} already exists. Choose a NEW dataset_root in config.')
    # Validate every episode before creating the destination. Do not silently skip failures.
    reports = []
    for path in paths:
        _, _, report = read_episode(path, cfg)
        reports.append(report)
        print(f"{path.name}: {report['frames']} frames, {report['duration_seconds']:.1f}s")
        if report['gripper_feedback_corrections']:
            print(f"  gripper feedback corrected: {report['gripper_feedback_corrections']} samples, "
                  f"raw range={report['corrected_gripper_raw_range']}")
    if args.inspect:
        print(f'{len(reports)} episodes inspected. No dataset was written.')
        return
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    dataset = LeRobotDataset.create(repo_id=cfg['repo_id'], root=root,
        fps=cfg['fps'], robot_type=cfg['robot_type'], features=FEATURES, use_videos=False)
    for path in paths:
        observation, actions, _ = read_episode(path, cfg)
        for state, action in zip(observation, actions):
            dataset.add_frame({'observation.state': state,
                               'observation.environment_state': state.copy(),
                               'action': action, 'task': cfg['task']})
        dataset.save_episode()
    (root / 'ur5e_conversion_report.json').write_text(
        json.dumps({'config': cfg, 'episodes': reports}, indent=2), encoding='utf-8')
    print(f'Dataset saved: {root}')


if __name__ == '__main__':
    main()

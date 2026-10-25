"""Compare policy predictions with recorded commands offline; never control ROS."""
import argparse
import json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import torch
from lerobot.common.policies.act.modeling_act import ACTPolicy
from common import JOINTS, load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--config')
    parser.add_argument('--episodes', nargs='+', type=int, default=[0, 10, 20])
    parser.add_argument('--samples', type=int, default=32)
    args = parser.parse_args()
    cfg = load_config(args.config)
    torch.set_num_threads(2)
    policy = ACTPolicy.from_pretrained(args.model_path).to('cpu').eval()
    errors, baselines, predicted, truth, starts = [], [], [], [], []
    for episode in args.episodes:
        path = Path(cfg['dataset_root']) / 'data' / f'chunk-{episode // 1000:03d}' / f'episode_{episode:06d}.parquet'
        data = pq.read_table(path).to_pydict()
        state = np.asarray(data['observation.state'], dtype=np.float32)
        actions = np.asarray(data['action'], dtype=np.float32)
        indices = np.unique(np.linspace(0, len(state) - 1, args.samples, dtype=int))
        for index in indices:
            policy.reset()
            obs = torch.tensor(state[index]).unsqueeze(0)
            with torch.inference_mode():
                output = policy.select_action({'observation.state': obs,
                    'observation.environment_state': obs.clone()}).numpy().reshape(-1)
            predicted.append(output)
            truth.append(actions[index])
            errors.append(output - actions[index])
            baselines.append(state[index] - actions[index])
            if index == 0:
                starts.append({'episode': episode, 'state': state[index].tolist(),
                               'teacher': actions[index].tolist(), 'predicted': output.tolist()})
        print(f'Analyzed recorded episode {episode}: {len(indices)} samples', flush=True)
    error = np.asarray(errors)
    prediction = np.asarray(predicted)
    target = np.asarray(truth)
    report = {'note': 'Training-record comparison only; not held-out success evaluation.',
              'samples': len(error), 'joint_order': JOINTS,
              'prediction_rmse_rad': np.sqrt(np.mean(error ** 2, axis=0)).tolist(),
              'hold_current_pose_rmse_rad': np.sqrt(np.mean(np.asarray(baselines) ** 2, axis=0)).tolist(),
              'arm_max_abs_error_rad': float(np.abs(error[:, :6]).max()),
              'arm_targets_exceeding_teleop_offset_fraction':
                  float(np.mean(np.abs(prediction[:, :6] - (target + np.asarray(baselines))[:, :6]) > .2)),
              'gripper_binary_disagreement_fraction': float(np.mean(
                  (prediction[:, 6] >= .23) != (target[:, 6] >= .23))),
              'initial_predictions': starts}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

"""Offline start probe: keep initial pose/open fingers and vary elapsed input."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from lerobot.common.policies.act.modeling_act import ACTPolicy
from history_data import environment, predict


def probe(path):
    path = Path(path)
    cfg = json.loads((path / 'history_training_config.json').read_text())
    model = ACTPolicy.from_pretrained(path).eval()
    state = np.array([0., -1.57, 0., -1.57, 0., 0., 0.], dtype=np.float32)
    elapsed = np.array([0, .5, 1, 1.5, 2, 3, 4, 6, 10, 20, 30, 60], dtype=float)
    env = np.stack([environment([state] * cfg['history_frames'], t, cfg['time_scale_seconds']) for t in elapsed])
    obs = {'observation.state': torch.tensor(np.tile(state, (len(elapsed), 1))),
           'observation.environment_state': torch.tensor(env)}
    with torch.inference_mode():
        result = predict(model, obs).numpy()[:, 0]
    representation = cfg.get('action_representation')
    if representation == 'delta_from_current':
        result += state
    elif representation == 'arm_delta_gripper_absolute':
        result[:, :6] += state[:6]
    return [{'elapsed_s': float(t), 'predicted_gripper_target': float(a[6]),
             'would_request_close': bool(a[6] > .28),
             'arm_max_target_offset_rad': float(np.max(np.abs(a[:6] - state[:6])))}
            for t, a in zip(elapsed, result)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path', required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    print(json.dumps(probe(args.model_path), indent=2))


if __name__ == '__main__':
    main()

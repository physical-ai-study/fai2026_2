"""Train local, joint-state-only ACT for UR5e using the course LeRobot checkout."""
import argparse
import json
from pathlib import Path
import random

import numpy as np
import torch
from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.common.datasets.utils import dataset_to_policy_features
from lerobot.common.policies.act.configuration_act import ACTConfig
from lerobot.common.policies.act.modeling_act import ACTPolicy
from lerobot.configs.types import FeatureType

from common import FEATURES, JOINTS, load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--steps', type=int)
    parser.add_argument('--output', help='New directory; existing directories are refused.')
    args = parser.parse_args()
    cfg = load_config(args.config)
    steps = args.steps if args.steps is not None else cfg['training_steps']
    if steps < 1:
        raise ValueError('steps must be positive.')
    output = Path(args.output or cfg['output_directory'])
    if output.exists():
        raise FileExistsError(f'{output} exists; select a NEW --output. No weights overwritten.')
    seed = cfg['seed']
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    root = Path(cfg['dataset_root'])
    metadata = LeRobotDatasetMetadata(cfg['repo_id'], root=root)
    if metadata.fps != cfg['fps']:
        raise ValueError('Dataset fps differs from training config.')
    for key in FEATURES:
        feature = metadata.features[key]
        if list(feature['shape']) != [7] or list(feature['names']) != JOINTS:
            raise ValueError(f'Unexpected feature layout: {key}')
    features = dataset_to_policy_features(FEATURES)
    inputs = {k: v for k, v in features.items() if v.type is not FeatureType.ACTION}
    outputs = {k: v for k, v in features.items() if v.type is FeatureType.ACTION}
    policy_cfg = ACTConfig(input_features=inputs, output_features=outputs,
        chunk_size=cfg['chunk_size'], n_action_steps=cfg['n_action_steps'],
        pretrained_backbone_weights=None)
    # Future actions at actual dataset intervals: 0, .05, .10, ... seconds.
    deltas = {'observation.state': [0.0], 'observation.environment_state': [0.0],
              'action': [i / cfg['fps'] for i in range(cfg['chunk_size'])]}
    dataset = LeRobotDataset(cfg['repo_id'], root=root, delta_timestamps=deltas)
    if not len(dataset):
        raise ValueError('Empty dataset.')
    device = torch.device(cfg['device'])
    policy = ACTPolicy(policy_cfg, dataset_stats=metadata.stats).to(device)
    policy.train()
    loader = torch.utils.data.DataLoader(dataset, batch_size=cfg['batch_size'],
        shuffle=True, num_workers=cfg['num_workers'], drop_last=False)
    optimizer = torch.optim.Adam(policy.parameters(), lr=cfg['learning_rate'])
    output.mkdir(parents=True, exist_ok=False)
    (output / 'ur5e_training_config.json').write_text(
        json.dumps(dict(cfg, training_steps=steps, joint_order=JOINTS), indent=2), encoding='utf-8')
    # No cloud logging, login, upload or robot control is involved.
    with (output / 'loss.jsonl').open('w') as log:
        step = 0
        while step < steps:
            for batch in loader:
                batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v
                         for k, v in batch.items()}
                for key in ('observation.state', 'observation.environment_state'):
                    batch[key] = batch[key][:, -1, :]
                loss, _ = policy.forward(batch)
                if not torch.isfinite(loss):
                    raise RuntimeError('Non-finite training loss; training stopped.')
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
                optimizer.step()
                step += 1
                if step == 1 or step % cfg['log_freq'] == 0 or step == steps:
                    record = {'step': step, 'loss': float(loss.detach().cpu())}
                    print(record, flush=True)
                    log.write(json.dumps(record) + '\n')
                    log.flush()
                if step >= steps:
                    break
    policy.save_pretrained(output)
    print(f'Model saved: {output}. Training loss alone does not establish task success.')


if __name__ == '__main__':
    main()

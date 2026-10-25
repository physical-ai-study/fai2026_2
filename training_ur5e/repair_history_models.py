"""Repair normalization serialization for this task's new history checkpoints only."""
import json
from pathlib import Path
import shutil
import torch
from lerobot.common.policies.act.modeling_act import ACTPolicy
from history_data import load_episodes, split, stats_for


def main():
    torch.set_num_threads(2)
    parent = Path('/home/ubuntu/checkpoints/train')
    for run in ('ur5e_history128_v1', 'ur5e_history128_balanced_v2', 'ur5e_history128_residual_v3'):
        root = parent / run
        cfg = json.loads((root / 'history_training_config.json').read_text())
        train, _ = split(load_episodes(cfg), cfg)
        stats = stats_for(train, cfg)
        for kind in ('best', 'last'):
            path = root / kind
            backup = path / 'model.safetensors.before_stats_repair'
            if backup.exists():
                raise FileExistsError(backup)
            model = ACTPolicy.from_pretrained(path, dataset_stats=stats)
            if not all(torch.isfinite(v).all() for v in model.state_dict().values()):
                raise RuntimeError(f'Nonfinite checkpoint: {path}')
            shutil.copy2(path / 'model.safetensors', backup)
            model.save_pretrained(path)
            restored = ACTPolicy.from_pretrained(path)
            if not all(torch.isfinite(v).all() for v in restored.state_dict().values()):
                raise RuntimeError(f'Normalization round trip failed: {path}')
            print(f'Repaired and reloaded: {path}', flush=True)


if __name__ == '__main__':
    main()

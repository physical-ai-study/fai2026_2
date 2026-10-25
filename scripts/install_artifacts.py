#!/usr/bin/env python3
"""Verify bundled artifacts and install them without overwriting different files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((repo / 'environment/artifacts.sha256.json').read_text())
    plans = []
    for relative, expected in manifest.items():
        source = repo / relative
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Artifact checksum mismatch: {relative}')
        if relative.startswith('models/'):
            target = args.home / 'checkpoints/train' / Path(relative).relative_to('models')
        elif relative.startswith('datasets/'):
            target = args.home / 'dataset/lerobot_dataset' / Path(relative).relative_to('datasets')
        else:
            raise ValueError(f'Unexpected artifact path: {relative}')
        if not args.verify_only and target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise FileExistsError(f'Different file exists; nothing copied: {target}')
        plans.append((source, target))
    if not args.verify_only:
        for source, target in plans:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
    print(f'Verified {len(plans)} artifacts.' + (' No files copied.' if args.verify_only else ' Installed.'))


if __name__ == '__main__':
    main()

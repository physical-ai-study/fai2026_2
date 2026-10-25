#!/usr/bin/env bash
# Run inside the exercise Ubuntu as ubuntu. Does not build/start Gazebo.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
train="$HOME/pai_training"
training_rev=b4d6b5459066a80433475a83567504988875248a
lerobot_rev=768e36660d1408c71118a2760f831c037fbfa17d
reuse=false
if [[ "${1:-}" == --reuse-env ]]; then reuse=true
elif [[ $# -gt 0 ]]; then echo 'Usage: bash scripts/setup_training.sh [--reuse-env]' >&2; exit 1; fi
if [[ ! -d "$train/.git" ]]; then
  if [[ -e "$train" ]]; then echo "Existing non-Git directory: $train" >&2; exit 1; fi
  git clone --no-checkout https://github.com/matsuolab/pai_training "$train"
  git -C "$train" checkout --detach "$training_rev"
  git -C "$train" submodule update --init --recursive
fi
if [[ "$(git -C "$train" rev-parse HEAD)" != "$training_rev" ]]; then
  echo "Training checkout differs. Preserve it and prepare the documented revision separately." >&2; exit 1
fi
if [[ ! -e "$train/lerobot/.git" ]]; then git -C "$train" submodule update --init --recursive; fi
if [[ "$(git -C "$train/lerobot" rev-parse HEAD)" != "$lerobot_rev" ]]; then
  echo 'LeRobot checkout differs; no reset was performed.' >&2; exit 1
fi
stamp="$(date +%Y%m%d_%H%M%S)"
if [[ -d "$train/ur5e" ]]; then cp -a "$train/ur5e" "$train/ur5e.before_pai2026_2_$stamp"; fi
mkdir -p "$train/ur5e"
cp -a "$repo/training_ur5e/." "$train/ur5e/"
python3 "$repo/scripts/install_artifacts.py"
if [[ "$reuse" == false ]]; then
  for file in pyproject.toml pixi.lock; do
    if [[ -e "$train/$file" ]]; then cp -p "$train/$file" "$train/$file.before_pai2026_2_$stamp"; fi
    cp "$repo/environment/$file" "$train/$file"
  done
  pixi_cmd="$(command -v pixi || true)"
  if [[ -z "$pixi_cmd" && -x "$HOME/.pixi/bin/pixi" ]]; then pixi_cmd="$HOME/.pixi/bin/pixi"; fi
  if [[ -z "$pixi_cmd" ]]; then echo 'Install Pixi first; see environment/README.md.' >&2; exit 1; fi
  (cd "$train" && "$pixi_cmd" install --locked)
else
  echo 'Reusing the existing Pixi environment; dependencies were not reinstalled.'
fi
echo 'Ready: ~/pai_training/ur5e; final model uses chunk_size=128 and n_action_steps=4.'

# 最終課題の学習と推論

最終版は **chunk_size=128、n_action_steps=4** です。

- [最初からの手順](../README.md)
- [最終モデルの学習条件と結果](HISTORY_README.md)
- [元のrosbagからの変換](../docs/DATA_CONVERSION.md)

このフォルダはUbuntuの `~/pai_training/ur5e` へ配置します。
初回はリポジトリ直下の `scripts/setup_training.sh` を使用してください。
`train.py` と以前の設定は比較用に残していますが、最終版の学習コマンドは
`train_history.py --config ur5e/history_swing_cylinder3_recovery.yaml` です。

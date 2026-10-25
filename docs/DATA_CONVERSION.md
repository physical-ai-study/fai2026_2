# 元のrosbagから変換する

同梱の変換済みデータを使う場合は不要です。元録画を持っている場合、新しく録画した場合だけ実行します。
先に[README](../README.md)で学習環境を準備してください。

```bash
cd ~/pai_training
pixi run python ur5e/convert.py --config ur5e/convert_cylinder3.yaml --inspect
pixi run python ur5e/convert.py --config ur5e/convert_cylinder3.yaml
```

最初のコマンドが成功してから次へ進みます。
入力は~/dataset/rosbags/move_cylinder3、出力は~/dataset/lerobot_dataset/ur5e_move_cylinder3です。
出力が存在すると上書きせず停止します。同梱データを配置済みの場合は、別の変換先を設定してください。

初期指令は開始時の測定姿勢、その後は直前の指令を使って20Hzへそろえます。
腕と指の指令・関節状態が必要です。状態配信の長い途切れや時刻リセットは拒否します。

ep6のグリッパー測定9件が下限−0.01radをわずかに超過し、最小値は−0.01360293radでした。
最終変換設定のgripper_feedback_tolerance_rad: 0.005により、この範囲の測定値だけ下限へ補正します。
アーム制限・操作指令は緩めず、補正件数と元の範囲をur5e_conversion_report.jsonへ記録します。
元rosbagは変更しません。

新しいデータにはbag_dir、dataset_root、repo_idを変更します。評価用を含め4本以上の記録が必要です。

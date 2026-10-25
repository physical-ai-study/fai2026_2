# UR5eによる円柱の移動と往復動作の模倣学習

Physical AI 応用編1の最終課題です。第5回の演習を発展させ、UR5eとRobotiq 2F-85で円柱を把持・移動・解放し、その後アームを往復させます。

**最終版は `chunk_size=128`、`n_action_steps=4`、モデル `ur5e_move_cylinder3_swing_v2/best` です。**

## 1 取得とGazeboの準備

WindowsのPowerShellで取得します。GitHubのCode → Download ZIPでも取得できます。

```powershell
git clone https://github.com/physical-ai-study/fai2026_2.git
cd fai2026_2
```

初めての場合は、[Gazeboの初回セットアップ](docs/SETUP_GAZEBO.md)を手順1から10まで進めます。
WindowsのDocker上でUbuntu・ROS 2 Humble・Gazebo Classicを使用します。
ROSパッケージ名は、リポジトリ名と異なり **physicalai_teleop** です。

すでに演習環境がある場合は、既存コンテナへ新しいコードをコピーしてビルドします。
Windowsのリポジトリ直下で実行します。

```powershell
docker start pai_ros2
$projectDir = (Get-Location).Path
docker exec -u ubuntu pai_ros2 mkdir -p /home/ubuntu/ur5e_ws/src/physicalai_teleop
docker cp "$projectDir\." pai_ros2:/home/ubuntu/ur5e_ws/src/physicalai_teleop/
docker exec -u root pai_ros2 chown -R ubuntu:ubuntu /home/ubuntu/ur5e_ws/src/physicalai_teleop
```

必要なロボット定義を導入した後、Ubuntu端末でビルドします。

```bash
source /opt/ros/humble/setup.bash
source ~/airobot_ws/install/setup.bash
cd ~/ur5e_ws
colcon build --symlink-install --packages-up-to physicalai_teleop
```

## 2 学習環境と最終モデルを配置する

[Pixiの導入と依存元の固定版](environment/README.md)を確認し、Ubuntu端末で実行します。

```bash
cd ~/ur5e_ws/src/physicalai_teleop
bash scripts/setup_training.sh
```

講座のpai_trainingとLeRobotを固定コミットで取得し、同梱環境定義で依存関係を導入します。
モデル・データはチェックサムを検証して配置します。既存ファイルの内容が異なる場合は、保存先を確認するために処理を停止します。
既存ur5eコードと環境定義は別名へ退避します。準備が終わったら、手順3以降でロボットを起動します。

同じ講座用Pixi環境がすでに動いている場合、依存の再導入を省略できます。

```bash
bash scripts/setup_training.sh --reuse-env
```

配置先：

```text
~/pai_training/ur5e/
~/checkpoints/train/ur5e_move_cylinder3_swing_v2/best/
~/dataset/lerobot_dataset/ur5e_move_cylinder3/
```

`python3 scripts/install_artifacts.py --verify-only`で同梱モデル・データの整合性だけ確認できます。

## 3 Gazeboを起動し初期状態へ戻す

Ubuntu端末1：

```bash
source /opt/ros/humble/setup.bash
source ~/airobot_ws/install/setup.bash
source ~/ur5e_ws/install/setup.bash
ros2 launch physicalai_teleop ur5e_robotiq_gazebo.launch.py
```

Ubuntu端末2でキーボード操作を起動します。

```bash
source /opt/ros/humble/setup.bash
source ~/airobot_ws/install/setup.bash
source ~/ur5e_ws/install/setup.bash
ros2 run physicalai_teleop teleop_keyboard --ros-args \
  --params-file "$(ros2 pkg prefix physicalai_teleop)/share/physicalai_teleop/config/ur5e.yaml"
```

Oで指を開いて保持を解除し、円柱を初期配置へ戻し、Xでアームを初期姿勢へ戻して完了を待ちます。
配置リセットにはEdit → Reset Model Posesを使い、シミュレーション時刻を継続させます。
**準備後はキーボード操作をCtrl+Cで終了し、Gazeboだけ起動したままにします。**

## 4 最終モデル128／4で推論する

Ubuntuの別端末で実行します。

```bash
source /opt/ros/humble/setup.bash
source ~/airobot_ws/install/setup.bash
source ~/ur5e_ws/install/setup.bash
cd ~/pai_training

pixi run python ur5e/infer.py \
  --model-path /home/ubuntu/checkpoints/train/ur5e_move_cylinder3_swing_v2/best \
  --execute
```

起動表示を確認します。

```text
ACT chunk_size=128, n_action_steps=4
EXECUTE: Gazebo commands enabled.
```

`--execute`を付けるとGazeboへ操作指令を送ります。予測だけ表示する場合は、この引数を外します。標準120秒、Ctrl+Cでも終了できます。
開始条件は、初期姿勢からのずれが0.05rad以内、指が開いた状態、円柱を解放した状態です。
推論設定は`~/pai_training/ur5e/config.yaml`、学習設定は`history_swing_cylinder3_recovery.yaml`です。

0.5秒超の受信遅延では指令送信を一時保留します。短時間で安定復帰すれば再予測します。
3秒以上の途切れ、時刻リセット、大きな姿勢変化では再起動が必要です。
終了後も送信済みの軌道と保持状態は継続します。解放はOで行います。ログは`~/pai_training/ur5e_runs/`に保存します。

## 5 同じデータと条件で再学習する

変換済み16エピソードを同梱しているため、手順2の後にそのまま学習できます。

```bash
cd ~/pai_training
pixi run python ur5e/train_history.py \
  --config ur5e/history_swing_cylinder3_recovery.yaml
```

5000ステップ、学習13本・評価3本、chunk_size=128、n_action_steps=4です。
再学習先は`~/checkpoints/train/ur5e_move_cylinder3_swing_v2_retrain/`で、同梱モデルを守ります。
再実行時は設定のoutput_directoryを新しい名前へ変えてください。
再学習モデルで推論する場合は、--model-pathを再学習先のbestへ変更します。

公開用設定のbaseline_model: nullは、同梱データを使った学習に集中する設定です。
同梱した最終モデルには、実験で選択した4000ステップ時点の重みを使用しています。
[最終モデルの学習条件と評価](training_ur5e/HISTORY_README.md)と[元の録画からの変換](docs/DATA_CONVERSION.md)も参照してください。

## 構成と出典

| フォルダ | 内容 |
|---|---|
| physicalai_teleop、launch、config、worlds | ロボット定義・配置・操作・起動 |
| gazebo_plugin | 演習用の把持補助 |
| training_ur5e | 変換・学習・往復評価・推論 |
| models、datasets | 最終モデルと変換済み関節データ |
| environment | 環境定義・依存コミット・チェックサム |

[出典と第三者コード](NOTICE.md)。講座配布コードを基に改変しています。
コード改修・調査・文書整理に生成AIの支援を利用しました。

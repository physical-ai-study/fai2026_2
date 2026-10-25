# 操作・モデル・データ収集の補足

[実行手順](../README.md)と[初回セットアップ](SETUP_GAZEBO.md)を併せて使用します。

## キーボード操作

| キー | 動作 |
|---|---|
| Q / E | 操作する関節を選択 |
| W / S | 選択関節を±0.025rad動かす |
| R / F | 全6軸を±0.05rad動かす |
| X | 起動時の初期姿勢へ戻す。グリッパーの状態は維持 |
| Space | 指令送信を一時停止／現在角から再開 |
| O / C | Robotiq 2F-85を開く／閉じる |
| Esc / Ctrl+C | 操作ノードを終了 |

関節状態を受信した後、操作キーで送信を開始します。関節名で状態を対応付け、20Hzで目標角を送ります。
アーム指令の到達時間は1秒、現在角からの目標差は各軸最大0.2radです。
状態の受信が0.5秒以上途切れると送信を一時停止します。受信の復旧後、操作キーで再開します。
Xは `config/ur5e.yaml` の `home_positions` に沿って初期姿勢 `[0, -1.57, 0, -1.57, 0, 0]` radへ戻します。
復帰中は周囲の物体との間隔を確認してください。送信済みの軌道とグリッパーの保持状態は操作ノード終了後も継続します。
Oで解放、Cで把持を指示します。パラメータは設定ファイルを更新して再ビルドするか、起動時に指定します。

## シーンと把持補助

- UR5e：公式モデルを使用し、天板高さ40cmの作業台に固定。
- Robotiq 2F-85：公開モデルを使用。主関節への位置指令とmimic設定で指を連動。
- 円柱：直径4cm、高さ20cm、質量50g。補助台で初期姿勢の指先に合わせて配置。
- 把持補助：閉じ動作後、指の角度と円柱の位置条件を満たすと手先に追従。

保持中は円柱の重力と衝突を無効にし、取得時の相対姿勢を維持します。解放すると重力と衝突を戻します。
この補助で円柱の持ち運びを模擬します。`grasp_assist:=false` で接触・摩擦による動作へ切り替えられます。
保持状態は `/physicalai/grasp_held` に配信し、推論側は閉じ指令後に保持状態を待ちます。

| ファイル | 役割 |
|---|---|
| `launch/ur5e_robotiq_gazebo.launch.py` | ロボット・ワールド・コントローラの起動 |
| `physicalai_teleop/robotiq_scene.py` | UR5eとRobotiqのモデル接続・制御定義 |
| `config/ur5e_robotiq_controllers.yaml` | アームとグリッパーの制御設定 |
| `config/ur5e.yaml` | 関節名、初期姿勢、操作量、制限値 |
| `worlds/ur5e_pick.world` | 作業台・補助台・円柱の定義 |
| `CMakeLists.txt` | Pythonノードと把持補助プラグインのビルド |

## データ収集と学習

テレオペを起動し、別のUbuntu端末で記録します。

```bash
source /opt/ros/humble/setup.bash
source ~/ur5e_ws/install/setup.bash
mkdir -p ~/dataset/rosbags/ur5e_demo
ros2 bag record -o ~/dataset/rosbags/ur5e_demo/ep0 \
  /joint_states /joint_trajectory_controller/joint_trajectory \
  /robotiq_gripper_controller/joint_trajectory /clock
```

記録開始後にOを押して開指令も記録します。各回はep0、ep1のように別フォルダへ保存します。
変換ではアーム6軸とグリッパー1軸を使い、関節名で並べ替え、次の指令まで開閉量を保持します。
準備スクリプトで `training_ur5e/` を `~/pai_training/ur5e` に配置します。
変換・学習・推論は[学習用README](../training_ur5e/README.md)、学習条件は[最終モデルの説明](../training_ur5e/HISTORY_README.md)を参照してください。
推論を開始する際はテレオペを終了し、指令の送信元を推論ノードに切り替えます。

## 関節と制御

| 順番 | 関節名 |
|---|---|
| 1 | `shoulder_pan_joint` |
| 2 | `shoulder_lift_joint` |
| 3 | `elbow_joint` |
| 4 | `wrist_1_joint` |
| 5 | `wrist_2_joint` |
| 6 | `wrist_3_joint` |

指令先は `/joint_trajectory_controller/joint_trajectory`、状態の受信先は `/joint_states` です。
Gazebo Classicの `joint_trajectory_controller` と位置制御を使用します。
関節名にprefixを付ける場合は `config/ur5e.yaml` もそろえます。
関節角の制限に加えて、操作時はロボットと周囲の物体の位置関係を確認してください。

## 参照

- [ROS公式の認証キー更新案内](https://discourse.openrobotics.org/t/ros-signing-key-migration-guide/43937)
- ローカルの第5回講義資料：Docker環境、テレオペ、記録、変換、推論の構成
- [Robotiq 2F-85の公開モデル](https://github.com/PickNikRobotics/ros2_robotiq_gripper/tree/main/robotiq_description)
- [Gazebo Classicとros2_controlの接続](https://control.ros.org/humble/doc/gazebo_ros2_control/doc/index.html)
- [公式Gazebo Classic構成（Humble）](https://github.com/UniversalRobots/Universal_Robots_ROS2_Gazebo_Simulation/tree/humble)
- [公式Gazebo起動ファイル](https://github.com/UniversalRobots/Universal_Robots_ROS2_Gazebo_Simulation/blob/humble/ur_simulation_gazebo/launch/ur_sim_control.launch.py)
- [公式Gazeboコントローラ設定](https://github.com/UniversalRobots/Universal_Robots_ROS2_Gazebo_Simulation/blob/humble/ur_simulation_gazebo/config/ur_controllers.yaml)
- [公式UR5e関節制限](https://github.com/UniversalRobots/Universal_Robots_ROS2_Description/blob/humble/config/ur5e/joint_limits.yaml)
- [ROS 2 Humble JointTrajectoryController](https://control.ros.org/humble/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html)

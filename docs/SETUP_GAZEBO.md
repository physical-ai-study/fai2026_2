# 初めてのセットアップ：UR5e＋Robotiq 2F-85

第5回の演習環境をまだ持っていない人向けに、最初から説明します。
完成すると、ブラウザの中のGazeboに次のものを表示し、キーボードで操作できます。

- UR5eのロボットアーム
- 先端のRobotiq 2F-85グリッパー
- 作業台・補助台と、赤い直径4cm・高さ20cm・重さ50gの円柱

ここでは**WindowsのIntel／AMD搭載PC**を対象にします。
ロボットとグリッパーをシミュレーションし、CPUで実行できます。
初回は大きなデータをダウンロードするため、インターネット接続と空き容量が必要です。

> 最終版の学習・推論は[リポジトリのREADME](../README.md)を参照してください。

## 最初に知っておくこと

Dockerは、演習に必要なUbuntu・ROS 2・Gazeboをまとめて動かすために使います。
その演習用の入れ物を「コンテナ」と呼び、この手順では`pai_ros2`という名前にします。
Windows本体にROS 2やGazeboを個別インストールする手順は不要です。

作業場所は2つあります。各手順の先頭で、どちらを使うか案内します。

| 作業場所 | 開き方 | 主に使う手順 |
|---|---|---|
| WindowsのPowerShell | Windows側のターミナル | 1〜4、停止・再開 |
| 演習画面内のUbuntuターミナル | ブラウザ内のデスクトップから開く | 6〜10 |

**番号順に進め、エラーが出たら次の手順へ進まないでください。**
コマンド欄だけをコピーします。`ubuntu@...$`などの表示は入力しません。

<details>
<summary>すでに第5回の環境がある人はこちら</summary>

- Docker Desktopを起動し、PowerShellで`docker start pai_ros2`を実行します。
- 新しいコンテナを作らず、手順2で変更済みフォルダを開き、手順4へ進みます。
- 別の名前で作った場合は、以下の`pai_ros2`を実際の名前に読み替えてください。
- 変更済みプログラムのコピー・必要データの導入・ビルドまで完了済みなら、手順9と10から再開できます。

</details>

## 1. Docker Desktopを入れる

**作業場所：Windows**

1. [Docker DesktopのWindows向け公式ページ](https://docs.docker.com/desktop/setup/install/windows-install/)から、Intel／AMD用のインストーラーを取得します。
2. インストーラーを実行し、WSL 2の有効化を求められたら案内に従います。再起動を求められたらPCを再起動します。
3. WindowsのスタートメニューからDocker Desktopを開き、起動が完了するまで待ちます。
4. WindowsのPowerShellを開き、次を実行します。

```powershell
docker version
```

`Client`と`Server`の両方の情報が表示されれば、次へ進みます。
接続エラーが出る場合はDocker Desktopを開いてください。
WSLの更新を求められた場合は、Docker Desktopの案内に従って更新します。
設定はLinuxコンテナ／WSL 2を使います。[公式のWSL 2設定案内](https://docs.docker.com/desktop/features/wsl/)

## 2. このプロジェクトのフォルダを開く

**作業場所：WindowsのPowerShell**

このREADMEを含む**変更済みプロジェクト一式**をWindowsに保存します。
ZIPで受け取った場合は、先に解凍してください。
元の`matsuolab/physicalai_teleop`を取得するだけでは、今回のUR5e・Robotiq・練習用物体の追加分は入りません。

エクスプローラーで、`README.md`と`package.xml`があるフォルダを開きます。
アドレス欄に`powershell`と入力してEnterを押すと、その場所でPowerShellを開けます。
以下を実行してください。

```powershell
$projectDir = (Get-Location).Path
if (-not (Test-Path '.\launch\ur5e_robotiq_gazebo.launch.py')) {
    throw 'フォルダが違うか、変更済みプロジェクトが揃っていません。'
}
```

エラーが出なければ正しい場所です。**このPowerShellは、手順4が終わるまで開いたままにします。**

## 3. 第5回の演習環境をダウンロードして作る

**作業場所：手順2と同じWindowsのPowerShell**

まず、講座で使うUbuntu・ROS 2 Humble・Gazebo入りのイメージを取得します。

```powershell
docker pull airobotbook/ros2-desktop-ai-robot-book-humble:latest
```

ダウンロードが成功したら、次をまとめて実行します。
PowerShellの行末のバッククォートも含めてコピーしてください。

```powershell
docker run -d --name pai_ros2 --shm-size=512m `
  -p 127.0.0.1:6080:80 `
  -p 127.0.0.1:9090:9090 -p 127.0.0.1:9876:9876 `
  --mount "type=bind,source=$projectDir,target=/workspace" `
  airobotbook/ros2-desktop-ai-robot-book-humble:latest
```

長い英数字のIDが表示されたら、作成できています。
6080は演習画面用、9090と9876は第5回で使うデータ可視化用の接続口です。
このイメージには、講座で使ったCRANE+ V2関連の環境も含まれます。
出典：[演習環境の公式リポジトリ](https://github.com/AI-Robot-Book-Humble/docker-ros2-desktop-ai-robot-book-humble)

`pai_ros2`がすでにあるというエラーなら、作り直さず次で起動します。

```powershell
docker start pai_ros2
```

## 4. 操作プログラムをコンテナにコピーする

**作業場所：手順2と同じWindowsのPowerShell**

Windowsの編集用フォルダから、Ubuntu内の実行用フォルダへコピーします。
次をまとめて実行してください。

```powershell
$projectDir = (Get-Location).Path
if (-not (Test-Path '.\launch\ur5e_robotiq_gazebo.launch.py')) {
    throw '手順2のプロジェクトフォルダで実行してください。'
}
docker exec -u ubuntu pai_ros2 mkdir -p /home/ubuntu/ur5e_ws/src/physicalai_teleop
if ($LASTEXITCODE -ne 0) { throw '保存先を作れませんでした。' }
docker cp "$projectDir\." pai_ros2:/home/ubuntu/ur5e_ws/src/physicalai_teleop/
if ($LASTEXITCODE -ne 0) { throw 'コピーに失敗しました。' }
docker exec -u root pai_ros2 chown -R ubuntu:ubuntu /home/ubuntu/ur5e_ws/src/physicalai_teleop
if ($LASTEXITCODE -ne 0) { throw 'コピー先の権限を設定できませんでした。' }
```

赤いエラーが出なければ完了です。講座用の`~/airobot_ws`や`~/pai_ws`のソースは上書きしません。
今後Windows側のプログラムを編集した場合も、この手順と手順8を行います。

## 5. ブラウザで演習画面を開く

**作業場所：Windowsのブラウザ**

[http://localhost:6080/](http://localhost:6080/)を開きます。
初回は画面が準備されるまで少し待ち、接続ボタンがあれば押してください。
パスワードを求められた場合は`ubuntu`です。

Ubuntuのデスクトップが表示されたら、デスクトップの`Terminator`を開きます。
見当たらなければ、画面内のメニューからターミナルを開いてください。

**ここからは、このブラウザ内のターミナルで実行します。**
Windowsのスタートメニューにある別の「Ubuntu」ではありません。
貼り付けは通常Ctrl+Shift+Vです。使えない場合はnoVNCのクリップボード機能を使います。

## 6. ダウンロード用の認証キーを更新する

**作業場所：演習画面内のUbuntuターミナル**

古いイメージでは、ROSの認証キーが期限切れになっていることがあります。
必要なロボットデータを追加する前に更新します。
次は、括弧も含めてまとめて実行してください。途中で失敗すると、このまとまりの処理が止まります。

```bash
(
  set -e
  curl -fSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /tmp/ur5e-ros-key.gpg
  if [ -f /usr/share/keyrings/ros-archive-keyring.gpg ]; then
    sudo cp -n /usr/share/keyrings/ros-archive-keyring.gpg /usr/share/keyrings/ros-archive-keyring.gpg.before-ur5e-repair
  fi
  sudo install -m 644 /tmp/ur5e-ros-key.gpg /usr/share/keyrings/ros-archive-keyring.gpg
  sudo apt-get update
)
```

最後まで進み、`EXPKEYSIG`や`E:`で始まるエラーがなければ次へ進みます。
これは上記の講座用イメージの配布元設定に合わせた更新です。
[ROS公式の認証キー更新案内](https://discourse.openrobotics.org/t/ros-signing-key-migration-guide/43937)を参考にしています。

## 7. UR5eとグリッパーのデータを追加する

**作業場所：同じUbuntuターミナル**

形状や関節、制御に必要なデータを追加します。次をまとめて実行します。

```bash
(
  set -e
  source /opt/ros/humble/setup.bash
  source ~/airobot_ws/install/setup.bash
  sudo apt-get install -y \
    ros-humble-ur-description ros-humble-ur-controllers \
    ros-humble-ur-moveit-config ros-humble-robotiq-description
  mkdir -p ~/ur5e_ws/src
  cd ~/ur5e_ws/src
  if [ ! -d Universal_Robots_ROS2_Gazebo_Simulation ]; then
    git clone -b humble https://github.com/UniversalRobots/Universal_Robots_ROS2_Gazebo_Simulation.git
  fi
  if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    sudo rosdep init
  fi
  rosdep update
  cd ~/ur5e_ws
  rosdep install --from-paths src --ignore-src --rosdistro humble -y
)
```

`All required rosdeps installed successfully`と表示されれば完了です。
すでに導入済みのものはそのまま使い、取得済みのリポジトリも再取得しません。
エラーが出た場合は、ビルドに進まないでください。

## 8. プログラムを使える状態にする（ビルド）

**作業場所：同じUbuntuターミナル**

```bash
(
  set -e
  source /opt/ros/humble/setup.bash
  source ~/airobot_ws/install/setup.bash
  cd ~/ur5e_ws
  colcon build --symlink-install --packages-up-to physicalai_teleop
)
```

最後に`Summary: 2 packages finished`などと表示され、`Failed`や`Aborted`がなければ完了です。
構成によってパッケージ数は変わります。手順7が失敗したままの場合、ビルドだけ成功しても起動できません。

## 9. UR5e・グリッパー・円柱を表示する

**作業場所：演習画面内のUbuntuターミナル1**

第5回のCRANE+ V2や古いGazeboが動いていたら、その端末でCtrl+Cを押して終了します。
次を実行してください。

```bash
source /opt/ros/humble/setup.bash &&
source ~/airobot_ws/install/setup.bash &&
source ~/ur5e_ws/install/setup.bash &&
ros2 launch physicalai_teleop ur5e_robotiq_gazebo.launch.py
```

Gazeboに、グリッパー付きUR5e・作業台・補助台・赤い円柱が表示されるまで待ちます。
**このターミナルは開いたままにします。**

## 10. キーボードで動かす

**作業場所：演習画面内で新しく開いたUbuntuターミナル2**

```bash
source /opt/ros/humble/setup.bash &&
source ~/airobot_ws/install/setup.bash &&
source ~/ur5e_ws/install/setup.bash &&
ros2 run physicalai_teleop teleop_keyboard --ros-args \
  --params-file "$(ros2 pkg prefix physicalai_teleop)/share/physicalai_teleop/config/ur5e.yaml"
```

操作用のターミナル2をクリックしてからキーを押します。

**Xキーの変更を反映したい場合**：この変更だけならGazeboはそのままで構いません。
操作用のターミナル2でCtrl+Cを押し、この手順10のコマンドをもう一度実行してください。
ソースを自分で更新した場合は、先に手順4のコピーと手順8のビルドを済ませます。

グリッパーの設定を更新した場合は、Gazeboとキーボード操作の端末でそれぞれCtrl+Cを押し、
手順9・10で両方を起動し直してください。起動中のロボットには新しい設定が反映されません。
指は1つの開閉指令に連動する簡易的な位置制御です。
現在のCキーは直径4cmの円柱に合わせた幅まで、4秒かけて閉じます。完全には閉じません。
棒を左右の指の中央に置いてからCを押してください。中心がずれたり、違う太さの物体を使ったりすると、
押し倒すことがあります。接触を検知して自動停止する方式ではありません。

**演習用の把持補助が標準で有効です。** 棒を指の中央に入れてCを押し、4秒待つと、
指の間にある円柱を手先に保持します。その後アームを動かし、Oを押すと離します。
Gazeboを起動した端末の`Grasp assist: cylinder held`が保持開始の目印です。
保持できなかった場合は位置を合わせてO→Cでやり直します。
把持補助を使用します。保持中の円柱は衝突と重力を無効にして手先に追従させ、
Oで戻します。机や壁をすり抜けるため、物理的な把持性能の評価には使えません。
補助を無効にする場合は、手順9の起動コマンド末尾に`grasp_assist:=false`を付けます。

| キー | 動作 |
|---|---|
| Q / E | 動かす関節を選ぶ |
| W / S | 選んだ関節を少し動かす |
| O / C | グリッパーを開く／閉じる |
| Space | アームへの指令送信を一時停止／再開 |
| R / F | 全6軸をまとめて動かす。最初は使わず1軸ずつ操作する |
| X | アームを起動時の初期姿勢へゆっくり戻す（指の開閉は維持） |
| Esc / Ctrl+C | 操作プログラムを終了 |

最初はEで関節を選び、WかSを1回ずつ押して動きを確認してください。
初期姿勢から始める場合は、まずOで開き、円柱の中央が指の間にあるか確認してからCで閉じます。
補助台の高さを合わせているため、つかむ操作を試す際の腕の移動は少なくて済む配置を狙っています。
すでに腕を動かしている場合は、Xを押すと、この配置に対応する初期姿勢へ戻ります。
第5回演習と同じくXが「姿勢を戻す」キーです。UR5eでは、Gazeboを起動したときの曲がった姿勢へ戻します。
Xは操作用ターミナル2をクリックしてから押します。GazeboのReset World／Reset Timeは別の操作です。
時刻をリセットした後に関節データの配信が止まった場合は、Gazeboと操作プログラムの両方を再起動します。
復帰先は設定ファイルの起動姿勢です。
指の開閉は変わらず、把持補助で保持した棒も保持したまま移動します。離す場合はOを押します。
戻っている途中でもSpaceで送信を一時停止でき、W/S/R/Fで通常操作に切り替わります。
Spaceで止めた後、再び初期姿勢へ戻したい場合はXを押してください。
障害物を避ける経路は計算しないため、戻る範囲に台などがないことを確認してください。
持ち上げるには、つかんだ後に腕を動かす必要があります。指の中心に円柱を合わせてから閉じます。
Spaceや終了操作では、送信済みのグリッパー指令を取り消しません。開き直す場合はOを押します。

## 動画撮影を何度も繰り返す

毎回の配置戻しには、Gazeboの **Edit → Reset Model Poses（Ctrl+Shift+R）** を使います。
物体の配置だけを戻し、シミュレーション時刻は戻しません。
**Reset World（Ctrl+R）／Reset Time／画面下のReset Timeは使わないでください。**
時刻が巻き戻ると、この環境では関節状態の配信が止まり、操作できなくなることがあります。

1. 録画を開始し、アームを操作する。
2. 録画を停止する。
3. 操作用ターミナルでOを押して棒の保持を解除し、指が開くまで待つ。
4. Xを押して、`Startup pose reached.`が出るまで待つ。
5. Gazeboのメニューから **Edit → Reset Model Poses** を選ぶ。ブラウザのショートカットと混同しないよう、メニュー操作がおすすめです。
6. 操作用ターミナルをクリックし、もう一度Xを押して初期姿勢にそろえ、棒が補助台で静止するまで待つ。
7. 次の録画を開始する。以降は同じ手順を繰り返す。

リセット前にもXで戻すのは、リセット直後に以前の操作目標へ腕が動くのを避けるためです。
Reset Model Posesでシミュレーション時刻を継続したまま配置を戻します。
すでに時刻リセットで状態配信が止まった場合だけ、Gazeboと操作プログラムの両方を終了し、
手順9→10で一度起動し直してから、この撮影手順に切り替えます。
撮影を繰り返す間もシミュレーション時刻を継続します。データ整理時に、その回の開始時刻を引いて相対時刻にします。

## 終了と、次回の再開

終了するときは、Ubuntuターミナル2、続いて1でCtrl+Cを押します。
その後、WindowsのPowerShellでコンテナを停止できます。

```powershell
docker stop pai_ros2
```

次回はDocker Desktopを開き、PowerShellで次を実行します。

```powershell
docker start pai_ros2
```

ブラウザで[演習画面](http://localhost:6080/)を開き、手順9と10を実行します。
2回目以降は導入済みの環境を起動します。
`docker stop`で止めても作業内容は残ります。コンテナを削除すると内部の変更が失われるため、
再開には`docker start`を使ってください。

## よくある困りごと

| 表示・症状 | 対応 |
|---|---|
| Xを押しても初期姿勢に戻らない | 手順10の操作プログラムをCtrl+Cで終了して起動し直す。自分でソースを更新した場合は、先に手順4・8も実行する |
| `No fresh Robotiq joint feedback`／`Joint feedback is missing or stopped` | Gazeboが一時停止中なら再生する。再生中でも出る場合は、操作端末とGazebo起動端末の両方をCtrl+Cで終了し、手順9→10で起動し直す。操作端末だけの再起動では復旧しない場合がある |
| `docker`が見つからない | Docker Desktopをインストールし、PowerShellを開き直す |
| Dockerへ接続できない | Docker Desktopを起動し、準備が終わるまで待つ |
| コンテナ名`pai_ros2`が使用済み | 新しく作らず、`docker start pai_ros2`を使う |
| 6080番などのポートが使用済み | `docker ps`で既存の演習コンテナを確認する。別サービスが使っている場合は、新規作成時の画面用指定を`127.0.0.1:6081:80`に変え、ブラウザも`http://localhost:6081/`で開く |
| `EXPKEYSIG`／署名が無効 | 手順6を完了してから手順7へ進む |
| `ament_python`のrosdep定義が見つからない | 古い版のソースの可能性がある。変更済みフォルダ一式を手順4でコピーし直す |
| `ur_description`／`robotiq_description`が見つからない | 手順7でのインストール成功を確認し、手順9を最初の行から実行する |
| `~/airobot_ws/install/setup.bash`がない | 指定した講座用イメージではない可能性がある。手順3のイメージ名を確認する |
| 起動ファイルが見つからない | 手順4のコピーと手順8のビルドを行う。元の公開版だけでは今回の追加分は入らない |
| O/Cを押しても開閉しない | 手順9のグリッパー付き起動ファイルを使い、手順10の設定ファイルも指定する。端末に出るエラーを確認する |
| 円柱を持ち上げられない | 指の位置・向き、摩擦や制御設定の調整が必要。最終デモでは把持補助を併用。物理的な把持力の評価はしていない |

## 第5回の内容と、追加情報

ここまでで、第5回で使うDocker・Ubuntu・ROS 2 Humble・Gazeboの土台に、UR5eとRobotiqを追加できます。
CRANE+ V2の元の演習や、LeRobotによる学習までをすべて再現する手順ではありません。
学習に進む場合は、別の`pai_training`側にも変更が必要です。
今回のUR5e向け追加コードと実行手順は、[UR5eの変換・学習・推論](../training_ur5e/README.md)にまとめています。

操作量・モデル定義・円柱の配置・データ収集と学習については、
[設定・データ収集・モデルの補足](REFERENCE.md)を参照してください。

参考：

- [Docker DesktopのWindows導入手順](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker DesktopとWSL 2](https://docs.docker.com/desktop/features/wsl/)
- [第5回で使用した演習用Docker環境](https://github.com/AI-Robot-Book-Humble/docker-ros2-desktop-ai-robot-book-humble)
- [ROSの認証キー更新案内](https://discourse.openrobotics.org/t/ros-signing-key-migration-guide/43937)
- [URのGazebo Classic構成（Humble）](https://github.com/UniversalRobots/Universal_Robots_ROS2_Gazebo_Simulation/tree/humble)

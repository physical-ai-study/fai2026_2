# 出典と第三者コード

講座配布コードを基に、UR5e・Robotiq・円柱配置、把持補助、学習・評価・推論を追加しました。

- [matsuolab/physicalai_teleop](https://github.com/matsuolab/physicalai_teleop)：改変元。
- [matsuolab/pai_training](https://github.com/matsuolab/pai_training)：講座の学習環境。
- [huggingface/lerobot](https://github.com/huggingface/lerobot)：ACT実装。固定コミットを別途取得。
- [UR ROS 2 Gazebo Simulation](https://github.com/UniversalRobots/Universal_Robots_ROS2_Gazebo_Simulation)：セットアップ時に取得。
- [演習用Docker環境](https://github.com/AI-Robot-Book-Humble/docker-ros2-desktop-ai-robot-book-humble)。

基準コミットはenvironment/provenance.jsonに記録しています。
元のphysicalai_teleopのpackage.xmlとsetup.pyのMIT表記を保持しました。
確認した配布元のファイル一覧には独立したLICENSE文書がありません。本ファイルは第三者コードに新しいライセンスを付与するものではありません。
依存ライブラリ・形状データ・Dockerイメージ等は、それぞれの配布元のライセンスと表示に従います。
公開用コピーでは連絡先メールを非個人のプレースホルダーへ変更しています。

同梱モデルと変換済みの関節データは本課題の実験で作成したものです。
把持補助を用いた結果を実機の把持性能やAI単独の成功率として扱わないでください。

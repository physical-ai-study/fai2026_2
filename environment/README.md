# 学習環境の導入と版

演習用Docker内のUbuntuユーザーubuntuを対象にします。
Pixiがなければ[公式の導入手順](https://pixi.prefix.dev/latest/installation/)に従います。

```bash
curl -fsSL https://pixi.sh/install.sh | sh
export PATH="$HOME/.pixi/bin:$PATH"
pixi --version
```

準備スクリプトは次のコミットを使用します。

| 依存元 | コミット |
|---|---|
| matsuolab/pai_training | b4d6b5459066a80433475a83567504988875248a |
| huggingface/lerobot | 768e36660d1408c71118a2760f831c037fbfa17d |

pyproject.tomlとpixi.lockは実行環境から取得したもので、個人のauthors情報のみ除いています。
ロックファイルは講座のpai_trainingとローカルのlerobotを参照するので、
リポジトリ直下の準備スクリプトで学習環境を導入してください。
既存チェックアウトの版を確認し、指定した版と一致する環境を使用します。
既存環境を使う場合は--reuse-envで依存の再導入を省略できます。

Pixiのsystem-requirements非推奨警告は元環境の形式によるもので、版の変更を避けるため保持しています。

## 同梱モデルとデータ

- models/ur5e_move_cylinder3_swing_v2/best：選択された4000stepの最終モデル。
- datasets/ur5e_move_cylinder3：16エピソード、23899フレーム、20Hzの関節角・教師指令。
- 再学習には同梱の変換済みデータを使えます。
- provenance.jsonに依存元、artifacts.sha256.jsonにモデル・データの整合性情報を記録。

同名の既存モデル・データと内容が違う場合、配置処理は停止します。既存結果を保管し、別の保存先を指定してください。

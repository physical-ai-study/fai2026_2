"""Report closing-initiation errors separately from averaged action errors."""
import json
from pathlib import Path
import torch
from lerobot.common.policies.act.modeling_act import ACTPolicy
from history_data import evaluate, load_episodes, save_json, split
from probe_start import probe


def main():
    torch.set_num_threads(2)
    parent = Path('/home/ubuntu/checkpoints/train')
    names = ['ur5e_history128_residual_v3', 'ur5e_history128_hybrid_v4',
             'ur5e_history128_transition_v5']
    report = {}
    for name in names:
        root = parent / name
        cfg = json.loads((root / 'history_training_config.json').read_text())
        _, validation = split(load_episodes(cfg), cfg)
        model = ACTPolicy.from_pretrained(root / 'best')
        metrics, _ = evaluate(model, validation, cfg)
        report[name] = {'metrics': metrics, 'initial_pose_probe': probe(root / 'best'),
                        'summary': json.loads((root / 'summary.json').read_text())}
    out = parent / names[-1] / 'report'
    out.mkdir(exist_ok=True)
    save_json(out / 'transition_comparison.json', report)
    rows = []
    for name, data in report.items():
        m = data['metrics']
        rows.append(f"| {name.rsplit('_',1)[-1]} | {m['closing']['gripper_rmse_rad']:.4f} | "
            f"{100*m['closing']['gripper_disagreement']:.1f}% | {m['active']['arm_rmse_rad']:.4f} | "
            f"{100*m['approach']['gripper_disagreement']:.1f}% |")
    lines = ['# 指を閉じ始めない問題の確認結果', '',
        '提示ログでは指の予測が0〜0.05付近のまま、開いた状態で小さく腕が動き続けていました。',
        '冒頭の保持状態待ちはその後解消しており、Pixiの非推奨警告や--execute不足が原因ではありません。', '',
        '学習18回・評価3回（ep1, ep13, ep15）は前の比較と同じです。元データと旧モデルは残しています。',
        '閉じ始めは「手本の目標が0.4以上、現在の指角度が0.3未満」の評価点です。', '',
        '| モデル | 閉じ始めの指RMSE (rad) | 閉じ始めの開閉判定不一致 | 動作対象点の腕RMSE (rad) | 開始前段階の開閉判定不一致 |',
        '|---|---:|---:|---:|---:|', *rows, '',
        'v4は腕だけを現在角からの修正量とし、指を絶対目標角へ変更しました。',
        'v5はさらに、閉じ始め・閉じた運搬・開き始め・その他の段階を均等に学習へ取り込みました。',
        'しきい値を下げる、経過時間で強制的に閉じる、といった推論側の強制操作は追加していません。', '',
        '## 初期状態の追加診断', '',
        '初期姿勢・開いた指の入力を固定し、経過時間だけを変えたオフライン診断を実施しました。',
        'v3では閉じる判定に届かず、v5では開始時に判定に届きました。詳細値はJSONに保存しています。',
        'ただしv5は開始前の待機段階でも閉じる傾向があり、元の操作と同じタイミングを再現できたわけではありません。',
        '評価3回はモデル選択にも使っています。未知の最終テストやGazeboでの繰り返し成功率は未測定です。',
        '「初回は動いたが2回目は動かない」の初回の正確な状態は記録がないため確定できません。', '',
        '## 実行', '',
        '姿勢・指・棒を初期状態に戻し、テレオペを終了してから以下を実行します。', '',
        '```bash', 'cd ~/pai_training', 'pixi run python ur5e/infer.py \\',
        '  --model-path /home/ubuntu/checkpoints/train/ur5e_history128_transition_v5/best \\',
        '  --execute', '```', '',
        '実行ログは~/pai_training/ur5e_runs/へ保存します。開いた指・初期姿勢でない場合は理由を表示して停止します。',
        '新しい推論開始の前には毎回、Oで解放、Xで復帰、Reset Model Posesで棒の配置戻し、必要なら再度X、テレオペ終了の順で準備します。',
        'GazeboのReset World／Reset Timeは使いません。', '']
    (out / 'TRANSITION_RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()

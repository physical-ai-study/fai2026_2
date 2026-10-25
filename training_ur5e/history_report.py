"""Summarize completed offline comparisons and plot phase errors."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    parent = Path('/home/ubuntu/checkpoints/train')
    runs = [parent / 'ur5e_history128_v1', parent / 'ur5e_history128_balanced_v2',
            parent / 'ur5e_history128_residual_v3']
    summaries = [json.loads((p / 'summary.json').read_text()) for p in runs]
    baseline = summaries[0]['baseline_metrics']
    best = [s['best_metrics'] for s in summaries]
    destination = runs[-1] / 'report'
    destination.mkdir(exist_ok=True)
    values = [('Previous ACT', baseline), ('History v1', best[0]),
              ('Balanced history v2', best[1]), ('Residual history v3', best[2])]
    phases = ['approach', 'carry', 'release', 'active']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    x = np.arange(len(phases))
    for idx, (name, metrics) in enumerate(values):
        for axis, key, title in zip(axes, ['arm_rmse_rad', 'gripper_rmse_rad'],
                                    ['Arm command error', 'Gripper command error']):
            axis.bar(x + (idx - 1.5) * .20, [metrics[p][key] for p in phases], .20, label=name)
            axis.set_title(title)
            axis.set_xticks(x, phases)
            axis.set_ylabel('RMSE (radians, lower is better)')
            axis.grid(axis='y', alpha=.2)
    axes[-1].legend(fontsize=8)
    fig.suptitle('Offline episode validation: 18 train / 3 validation; not Gazebo success rate')
    fig.savefig(destination / 'phase_comparison.png', dpi=170)
    plt.close(fig)
    rows = []
    for name, m in values:
        rows.append(f"| {name} | {m['all']['arm_rmse_rad']:.4f} | {m['active']['arm_rmse_rad']:.4f} | "
                    f"{m['all']['gripper_rmse_rad']:.4f} | {100*m['all']['gripper_disagreement']:.1f}% |")
    notes = [
        '# UR5eの学習・評価結果', '',
        '21回の記録をエピソード単位で18回の学習と3回の評価に分けました。評価はep1・ep13・ep15です。',
        '元データと以前のモデルは維持しています。Gazeboでのアーム操作・成功率測定は実施していません。', '',
        '| モデル | 全段階のアームRMSE (rad) | 動作対象点のアームRMSE (rad) | 指のRMSE (rad) | 開閉判定の不一致 |',
        '|---|---:|---:|---:|---:|', *rows, '',
        '動作対象点は、手本の目標角と現在角との差がいずれかのアーム関節で0.01radを超える点です。',
        '段階ラベルは指令から分類したもので、把持成功を確認したラベルではありません。', '',
        '## 変更した学習方法', '',
        '- 過去8点（20Hzで0.35秒の履歴幅）の関節角と、切り出し開始からの経過時間を入力。',
        '- 初動1秒前から最終指令変更5秒後までを使用。指の開閉待機を保持。全切り出し範囲はdata_split.jsonへ保存。',
        '- 正規化統計は学習18回だけで算出。微小な関節ノイズを過度に拡大しないよう標準偏差に下限を設定。',
        '- CPU向けの小型ACTへ変更し、VAEの潜在変数を使わない予測誤差の学習。chunk_size=128、n_action_steps=4を維持。',
        '- v2では操作段階を均等に抽出し、実行対象の先頭4点を8倍に重み付け。',
        '- v3では、さらに絶対目標角ではなく予測時点の現在角からの修正量を学習。推論時に予測時点の角度を足し戻す。',
        '- 各モデルを5000ステップ学習し、500ステップごとに評価。動作対象点のアームRMSEと全体の指RMSEの和で保存モデルを選択。', '',
        f"v1の選択ステップ: {summaries[0]['best_step']}。v2の選択ステップ: {summaries[1]['best_step']}。", '',
        f"v3の選択ステップ: {summaries[2]['best_step']}。", '',
        '## 結果の限界', '',
        '以前のモデルは全21回を学習済みなので、以前のモデルにとっては未知データではありません。',
        '評価3回はモデル選択にも使っています。独立した最終テスト用の記録は別途必要です。',
        '経過時間を入力に含むため、固定配置の作業を同じ開始条件で行う用途です。時間変動や新しい物体位置への対応は未確認です。',
        'オフラインの指令誤差が改善しても、閉ループで動き出すことや運搬成功は保証しません。',
        '把持待機などの実行補助も残るため、結果をモデル単独の成功率として扱わないでください。', '',
        '![段階別比較](phase_comparison.png)', '',
    ]
    (destination / 'RESULTS.md').write_text('\n'.join(notes), encoding='utf-8')
    (destination / 'comparison.json').write_text(json.dumps({
        'baseline': baseline, 'history_v1': summaries[0], 'balanced_v2': summaries[1],
        'residual_v3': summaries[2]}, indent=2))
    print(destination)


if __name__ == '__main__':
    main()

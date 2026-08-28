"""随机抽取学习者画像样本，评测 Agent1「画像生成 + 难度分配」准确率（真实 LLM）。

真值来源：``data/evaluation/learner_profiles.json`` 的 ``expected_profile``
（外部预先标注，评测时禁止从模型输出回填，见 learner_profiles.json 的 meta.truth_policy）。
模型输出：``DiagnosisAgent`` 在真实 LLM 模式下生成的 ``diagnosis_result``。

评测两项（对应用户问题「人物画像生成 + 难度分配」）：
  * 难度分配准确率 = ``recommended_difficulty == expected_difficulty`` 的占比。
    —— 难度由 ``_enforce_pretest_evidence`` 按前置测试得分率确定性校正，
       在真值齐全的前提下理论应为 100%；本脚本仍按模型最终输出如实统计。
  * 学习风格准确率 = ``learning_style == expected_learning_style`` 的占比。
    —— 这是画像中唯一由 LLM 生成、真值可比的字段，是本次评测的核心考察项。

补充输出「画像综合准确率」：难度与风格同时命中的画像占比。

Run:
    python scripts/eval_persona_accuracy.py [--sample N] [--seed 42] [--output PATH]

Exit:
    0 = 两项准确率均 ≥ 阈值；1 = 任一未达标（或样本不足无法评估）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，统一 UTF-8 输出兜底（与 eval_adaptation.py 一致）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.agents.diagnosis import DiagnosisAgent  # noqa: E402
from backend.src.config import settings  # noqa: E402
from backend.src.llm.client import llm  # noqa: E402

DEFAULT_TRUTH = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "evaluation" / "runs" / "persona_accuracy_report.json"

# 用户目标阈值（问题原文：85%）；配置内另有 ADAPTATION_PDCA_TARGET=0.90 一并展示
USER_TARGET = 0.85
_CANONICAL_STYLES = {"visual", "theory_first", "practice_first", "project_based"}


def load_profiles(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    profiles = doc.get("profiles", [])
    if not isinstance(profiles, list) or not profiles:
        raise ValueError(f"learner_profiles.json 缺少 profiles 列表: {path}")
    return [dict(p) for p in profiles if isinstance(p, dict)]


async def run_one(profile: dict[str, Any]) -> dict[str, Any]:
    """对单个画像跑 DiagnosisAgent，返回 {pred_difficulty, pred_style, error}。"""
    agent = DiagnosisAgent()
    state: dict[str, Any] = {"learner_data": profile["input"]}
    state = await agent.run(state)
    if state.get("status") == "error":
        return {
            "pred_difficulty": None,
            "pred_style": None,
            "error": state.get("error") or state.get("error_type") or "unknown error",
        }
    diag = state.get("diagnosis_result") or {}
    pred_difficulty = diag.get("recommended_difficulty")
    pred_style = diag.get("learning_style")
    # 诊断解析失败时 diag 可能只含 _parse_error，难度/风格为 None → 计为缺失
    return {
        "pred_difficulty": pred_difficulty if isinstance(pred_difficulty, str) else None,
        "pred_style": pred_style if isinstance(pred_style, str) else None,
        "error": None,
    }


def _match(pred: str | None, truth: str) -> bool:
    if pred is None:
        return False
    return pred.strip().casefold() == truth.strip().casefold()


def _fmt(pct: float | None) -> str:
    return "N/A" if pct is None else f"{pct:.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    parser.add_argument("--sample", type=int, default=0, help="抽样画像数（0=全部）")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    profiles = load_profiles(args.truth)
    total = len(profiles)
    rng = random.Random(args.seed)
    order = list(range(total))
    rng.shuffle(order)
    n_sample = total if args.sample <= 0 else min(args.sample, total)
    sampled = [profiles[i] for i in order[:n_sample]]

    mode = (
        "演示模式（无 API Key，学习风格非真实 LLM 生成）"
        if llm.is_demo
        else (f"真实调用（{settings.LLM_PROVIDER}/{settings.LLM_MODEL}）")
    )

    print("===== 学习者画像生成 + 难度分配 准确率评测 =====")
    print()
    print(f"  模式: {mode}")
    print(f"  样本: 随机抽取 {n_sample}/{total} 画像 (seed={args.seed})")
    if n_sample < 30:
        print(f"  ⚠ 样本数 {n_sample} < 30，统计可信度有限，结论仅供参考。")
    print()

    async def _run_all() -> list[dict[str, Any]]:
        return await asyncio.gather(*(run_one(p) for p in sampled))

    results = asyncio.run(_run_all())

    rows: list[dict[str, Any]] = []
    print("【逐画像明细】(难度 / 学习风格：pred → 真值)")
    for profile, res in zip(sampled, results):
        exp = profile.get("expected_profile", {})
        true_diff = str(exp.get("expected_difficulty", ""))
        true_style = str(exp.get("expected_learning_style", ""))
        diff_ok = _match(res["pred_difficulty"], true_diff)
        style_ok = _match(res["pred_style"], true_style)
        rows.append(
            {
                "profile_id": profile.get("id"),
                "label": profile.get("label"),
                "true_difficulty": true_diff,
                "pred_difficulty": res["pred_difficulty"],
                "difficulty_ok": diff_ok,
                "true_style": true_style,
                "pred_style": res["pred_style"],
                "style_ok": style_ok,
                "error": res["error"],
            }
        )
        mark = "✓" if (diff_ok and style_ok and not res["error"]) else "✗"
        err = f"  [错误: {res['error']}]" if res["error"] else ""
        print(
            f"  [{mark}] {profile.get('id')}"
            f"  难度: {res['pred_difficulty']} → {true_diff}"
            f"  | 风格: {res['pred_style']} → {true_style}{err}"
        )
    print()

    n_diff_valid = sum(1 for r in rows if r["pred_difficulty"] is not None)
    n_style_valid = sum(1 for r in rows if r["pred_style"] is not None)
    diff_correct = sum(1 for r in rows if r["difficulty_ok"])
    style_correct = sum(1 for r in rows if r["style_ok"])
    both_correct = sum(1 for r in rows if r["difficulty_ok"] and r["style_ok"])

    diff_rate = diff_correct / n_sample if n_sample else None
    style_rate = style_correct / n_sample if n_sample else None
    both_rate = both_correct / n_sample if n_sample else None

    print("【汇总】")
    print(
        f"  难度分配准确率 : {diff_correct}/{n_sample} = {_fmt(diff_rate)}"
        f"  (有效预测 {n_diff_valid}/{n_sample})  → 目标 ≥ {_fmt(USER_TARGET)}"
    )
    print(
        f"  学习风格准确率 : {style_correct}/{n_sample} = {_fmt(style_rate)}"
        f"  (有效预测 {n_style_valid}/{n_sample})  → 目标 ≥ {_fmt(USER_TARGET)}"
    )
    print(f"  画像综合准确率 : {both_correct}/{n_sample} = {_fmt(both_rate)}（难度+风格同时命中）")
    print()
    print(f"  参考：配置内链路A PDCA 目标 ≥ {settings.ADAPTATION_PDCA_TARGET:.0%}（较 85% 更严格）")
    print()

    # 学习风格混淆：仅展示预测/真值都是规范值的情况，帮助定位偏差方向
    style_confusion: dict[str, dict[str, int]] = {}
    for r in rows:
        p, t = r["pred_style"], r["true_style"]
        if p in _CANONICAL_STYLES and t in _CANONICAL_STYLES:
            style_confusion.setdefault(t, {})[p] = style_confusion.setdefault(t, {}).get(p, 0) + 1
    if style_confusion:
        print("【学习风格混淆】(行=真值, 列=预测)")
        styles = sorted(_CANONICAL_STYLES)
        print("            " + "  ".join(f"{s:<15}" for s in styles))
        for t in styles:
            row = style_confusion.get(t, {})
            print(f"  {t:<10} " + "  ".join(f"{row.get(p, 0):<15}" for p in styles))
        print()

    diff_pass = diff_rate is not None and diff_rate >= USER_TARGET
    style_pass = style_rate is not None and style_rate >= USER_TARGET
    passed = diff_pass and style_pass
    print("【阈值判定】")
    print(f"  难度分配 ≥85%: {'通过' if diff_pass else '不通过'}")
    print(f"  学习风格 ≥85%: {'通过' if style_pass else '不通过'}")
    print(f"  综合判定: {'通过' if passed else '不通过'}")

    report = {
        "mode": mode,
        "sample_size": n_sample,
        "total_profiles": total,
        "seed": args.seed,
        "target": USER_TARGET,
        "difficulty_accuracy": diff_rate,
        "style_accuracy": style_rate,
        "combined_accuracy": both_rate,
        "passed": passed,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  报告已写入: {args.output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

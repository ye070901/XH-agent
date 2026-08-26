"""难度适配评估 — 链路A/B/E2E + 2×2 归因 + 问题2 结果输出（禁止调用 LLM）。

本脚本只读离线数据，绝不调用 LLM：

  * 真值来源：``learner_profiles.json`` 的 ``expected_profile``（外部预先标注）
  * 模型输出：raw outputs 记录里的 ``diagnosis`` / ``resources`` / ``audit``
  * 链路A：Agent1 画像难度判定准确率（PDCA / OffByOne / 加权Kappa / 偏置 / MAE）
  * 链路B：原有 ``EvaluationMetrics.compute_adaptation`` 资源适配准确率
  * E2E：  Agent2 生成资源难度是否遵从 Agent1 给出的难度
  * 2×2 归因：区分「Agent1 判断出错」/「Agent2 未遵守难度指令」
  * 问题2：复用 ``EvaluationMetrics.compute_all`` + ``aggregate_case_results``（不修改算法）

难度档位经 ``metrics._normalise_difficulty`` 归一化为 0/1/2（beginner/intermediate/advanced），
避免「初级/入门/basic」等别名或字段名（difficulty vs difficulty_level）带来的计算偏差。

Run:
    python scripts/eval_adaptation.py --outputs data/evaluation/<outputs>.json

Exit:
    0 = 门禁通过；1 = 门禁不通过（任一指标未达标或样本不足无法评估）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，统一 UTF-8 输出兜底（与 check_contracts.py 一致）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_phase3_evaluation import evaluate_negative_case, response_parts  # noqa: E402

from backend.src.config import settings  # noqa: E402
from backend.src.evaluation.metrics import (  # noqa: E402
    EvaluationMetrics,
    _normalise_difficulty,
    aggregate_case_results,
)

DEFAULT_TRUTH = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"
DEFAULT_CASES = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases.json"
DEFAULT_CORE_MAP = REPO_ROOT / "data" / "core_knowledge_map.json"

AGENT1 = "Agent1（学情诊断）"
AGENT2 = "Agent2（知识生成）"
DIFF_LABELS = ("beginner", "intermediate", "advanced")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON must be an object: {path}")
    return data


def mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def difficulty_index(value: Any) -> int | None:
    """复用 metrics 的统一档位归一化，避免别名/字段名造成偏差。"""
    return _normalise_difficulty(value)


def load_truth(path: Path) -> dict[str, dict[str, Any]]:
    """读取 learner_profiles.json，返回 profile_id -> expected_profile。"""
    doc = load_json(path)
    truth: dict[str, dict[str, Any]] = {}
    for profile in doc.get("profiles", []):
        if not isinstance(profile, Mapping):
            continue
        pid = profile.get("id")
        expected = profile.get("expected_profile", {})
        if pid:
            truth[str(pid)] = dict(expected)
    return truth


def collect_samples(
    records: Sequence[Any],
    truth_by_profile: dict[str, dict[str, Any]],
    positive_case_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """从 records 抽取问题1 样本（每 record 一个诊断 = 链路A 一个样本）。

    positive_case_ids 非空时只评估正例（负例是安全/边界用例，不参与适配准确率）。
    """
    samples: list[dict[str, Any]] = []
    for record in records:
        rec = mapping(record)
        case_id = str(rec.get("case_id") or "")
        if positive_case_ids is not None and case_id not in positive_case_ids:
            continue
        profile_id = str(rec.get("profile_id") or "")
        truth = truth_by_profile.get(profile_id)
        if truth is None:
            continue
        true_idx = difficulty_index(truth.get("expected_difficulty"))
        if true_idx is None:
            continue
        diagnosis, resources, _audit = response_parts(rec.get("response"))
        samples.append(
            {
                "case_id": case_id,
                "profile_id": profile_id,
                "true_idx": true_idx,
                "pred_idx": difficulty_index(mapping(diagnosis).get("recommended_difficulty")),
                "resources": [mapping(r) for r in resources if mapping(r)],
                "truth": truth,
            }
        )
    return samples


def linear_weighted_kappa(confusion: Sequence[Sequence[int]]) -> float | None:
    """线性加权 Cohen's Kappa（3 档序数，相邻档位权重 0.5）。"""
    n_classes = len(confusion)
    total = sum(sum(row) for row in confusion)
    if total == 0 or n_classes < 2:
        return None
    row_sums = [sum(row) for row in confusion]
    col_sums = [sum(confusion[i][j] for i in range(n_classes)) for j in range(n_classes)]
    observed = 0.0
    expected = 0.0
    for i in range(n_classes):
        for j in range(n_classes):
            weight = 1.0 - abs(i - j) / (n_classes - 1)
            observed += weight * confusion[i][j]
            expected += weight * (row_sums[i] / total) * (col_sums[j] / total)
    observed /= total
    if abs(1.0 - expected) < 1e-12:
        return 1.0 if abs(observed - expected) < 1e-12 else None
    return round((observed - expected) / (1.0 - expected), 4)


def compute_link_a(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """链路A：Agent1 画像难度判定准确率。"""
    valid = [s for s in samples if s["pred_idx"] is not None]
    missing = len(samples) - len(valid)
    if not valid:
        return {
            "n_samples": len(samples),
            "n_missing_pred": missing,
            "not_applicable": True,
            "reason": "no_evaluable_pairs",
        }
    n = len(valid)
    confusion = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    exact = 0
    off_by_one = 0
    diff_sum = 0.0
    bias_sum = 0.0
    for s in valid:
        t = s["true_idx"]
        p = s["pred_idx"]
        confusion[t][p] += 1
        gap = abs(p - t)
        if gap == 0:
            exact += 1
        if gap <= 1:
            off_by_one += 1
        diff_sum += gap
        bias_sum += p - t
    return {
        "n_samples": len(samples),
        "n_missing_pred": missing,
        "n_valid": n,
        "pdca": round(exact / n, 4),
        "off_by_one": round(off_by_one / n, 4),
        "mae": round(diff_sum / n, 4),
        "bias": round(bias_sum / n, 4),
        "kappa": linear_weighted_kappa(confusion),
        "confusion": confusion,
        "not_applicable": False,
    }


def compute_link_b(
    samples: Sequence[dict[str, Any]],
    evaluator: EvaluationMetrics,
) -> dict[str, Any]:
    """链路B：复用原有 compute_adaptation 资源适配准确率（资源难度+风格 vs 真值）。"""
    rates: list[float] = []
    difficulty_matches: list[float] = []
    style_matches: list[float] = []
    for s in samples:
        adapt = evaluator.compute_adaptation({}, s["resources"], expected_profile=s["truth"])
        if adapt.get("ground_truth_provided"):
            rates.append(float(adapt["rate"]))
            difficulty_matches.append(float(adapt["difficulty_match"]))
            style_matches.append(float(adapt["style_match"]))
    if not rates:
        return {"not_applicable": True, "reason": "no_ground_truth_resources"}
    return {
        "rate": round(sum(rates) / len(rates), 4),
        "difficulty_match": round(sum(difficulty_matches) / len(difficulty_matches), 4),
        "style_match": round(sum(style_matches) / len(style_matches), 4),
        "evaluated_cases": len(rates),
        "not_applicable": False,
    }


def compute_e2e(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """端到端一致性：Agent2 生成资源难度 == Agent1 判定难度 的资源占比。"""
    total = 0
    matched = 0
    for s in samples:
        pred = s["pred_idx"]
        if pred is None:
            continue
        for resource in s["resources"]:
            res_idx = difficulty_index(
                resource.get("difficulty_level") or resource.get("difficulty")
            )
            if res_idx is None:
                continue
            total += 1
            if res_idx == pred:
                matched += 1
    if total == 0:
        return {"not_applicable": True, "reason": "no_resources_with_difficulty"}
    return {
        "rate": round(matched / total, 4),
        "matched": matched,
        "total": total,
        "not_applicable": False,
    }


def compute_attribution(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """2×2 归因表（资源粒度）。

    行 = Agent1 判定（对/错 vs 真值），列 = Agent2 遵从（资源难度 == Agent1 判定难度）。
    """
    cells = {
        "a1_ok_a2_ok": 0,  # 链路健康
        "a1_ok_a2_bad": 0,  # Agent2 未遵守难度指令
        "a1_bad_a2_ok": 0,  # Agent1 判断出错（Agent2 遵从了错误指令）
        "a1_bad_a2_bad": 0,  # 双重问题
    }
    skipped = 0
    for s in samples:
        pred = s["pred_idx"]
        true = s["true_idx"]
        if pred is None:
            continue
        for resource in s["resources"]:
            res_idx = difficulty_index(
                resource.get("difficulty_level") or resource.get("difficulty")
            )
            if res_idx is None:
                skipped += 1
                continue
            a1_ok = pred == true
            a2_ok = res_idx == pred
            if a1_ok and a2_ok:
                cells["a1_ok_a2_ok"] += 1
            elif a1_ok and not a2_ok:
                cells["a1_ok_a2_bad"] += 1
            elif not a1_ok and a2_ok:
                cells["a1_bad_a2_ok"] += 1
            else:
                cells["a1_bad_a2_bad"] += 1
    agent1_errors = cells["a1_bad_a2_ok"] + cells["a1_bad_a2_bad"]
    agent2_errors = cells["a1_ok_a2_bad"] + cells["a1_bad_a2_bad"]
    return {
        "cells": cells,
        "agent1_errors": agent1_errors,
        "agent2_errors": agent2_errors,
        "skipped_resources": skipped,
        "total_resources": sum(cells.values()),
    }


def link_b_blame(attribution: dict[str, Any]) -> str:
    """链路B 失败的责任归因：Agent1 判断错 → 资源即使遵从也是错的。"""
    parts: list[str] = []
    if attribution["agent1_errors"] > 0:
        parts.append(AGENT1)
    if attribution["agent2_errors"] > 0:
        parts.append(AGENT2)
    return " + ".join(parts) if parts else "（未定位到责任 Agent）"


def build_gate_checks(
    link_a: dict[str, Any],
    link_b: dict[str, Any],
    e2e: dict[str, Any],
    attribution: dict[str, Any],
) -> list[dict[str, Any]]:
    """组装问题1 全部指标门禁检查，逐条给出阈值/实际值/方向/链路/责任 Agent。

    画像链路（链路A）与资源链路（链路B）两套门禁各自独立校验；
    端到端一致性（E2E）单独校验，互不替代、互不放宽。
    """
    checks: list[dict[str, Any]] = []

    def add(
        name: str,
        threshold: float,
        actual: float | None,
        op: str,
        blame: str,
        link: str,
    ) -> None:
        if actual is None:
            passed = False
        elif op == ">=":
            passed = actual >= threshold
        else:
            passed = actual <= threshold
        checks.append(
            {
                "name": name,
                "link": link,
                "threshold": threshold,
                "actual": actual,
                "op": op,
                "passed": passed,
                "blame": blame,
            }
        )

    if not link_a.get("not_applicable"):
        add(
            "链路A·画像判定准确率(PDCA)",
            settings.ADAPTATION_PDCA_TARGET,
            link_a["pdca"],
            ">=",
            AGENT1,
            "画像链路",
        )
        add(
            "链路A·相邻容错(OffByOne)",
            settings.ADAPTATION_OFFBYONE_TARGET,
            link_a["off_by_one"],
            ">=",
            AGENT1,
            "画像链路",
        )
        add(
            "链路A·加权Kappa",
            settings.ADAPTATION_KAPPA_TARGET,
            link_a["kappa"],
            ">=",
            AGENT1,
            "画像链路",
        )
        add(
            "链路A·偏置下限",
            settings.ADAPTATION_BIAS_MIN,
            link_a["bias"],
            ">=",
            AGENT1,
            "画像链路",
        )
        add(
            "链路A·偏置上限",
            settings.ADAPTATION_BIAS_MAX,
            link_a["bias"],
            "<=",
            AGENT1,
            "画像链路",
        )
        add(
            "链路A·平均绝对误差(MAE)",
            settings.ADAPTATION_MAE_TARGET,
            link_a["mae"],
            "<=",
            AGENT1,
            "画像链路",
        )

    if not link_b.get("not_applicable"):
        add(
            "链路B·资源适配准确率",
            settings.ADAPTATION_TARGET,
            link_b["rate"],
            ">=",
            link_b_blame(attribution),
            "资源链路",
        )

    if not e2e.get("not_applicable"):
        add(
            "端到端一致性(E2E)",
            settings.ADAPTATION_E2E_TARGET,
            e2e["rate"],
            ">=",
            AGENT2,
            "端到端一致性",
        )

    return checks


async def run_problem2(
    cases: Sequence[Any],
    records_by_id: dict[str, Any],
    core_map: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """问题2：复用原有 compute_all + aggregate_case_results（不改内部算法）。"""
    evaluator = EvaluationMetrics()
    aggregate_inputs: list[dict[str, Any]] = []
    positive_results: list[dict[str, Any]] = []
    negative_results: list[dict[str, Any]] = []
    for case in cases:
        case_m = mapping(case)
        record = records_by_id.get(case_m.get("id"))
        if record is None:
            continue
        if case_m.get("kind") == "negative":
            negative_result = evaluate_negative_case(evaluator, case_m, record)
            negative_results.append(negative_result)
            aggregate_inputs.append(
                {
                    "case_id": case_m.get("id"),
                    "profile_id": case_m.get("profile_id"),
                    "is_negative": True,
                    "negative_pass": negative_result["pass"],
                }
            )
            continue
        _diagnosis, resources, audit = response_parts(mapping(record).get("response"))
        metrics = await evaluator.compute_all(
            audit,
            {},
            resources,
            expected_profile=case_m.get("expected_profile"),
            expected_gaps=case_m.get("expected_gaps"),
            core_knowledge_map=core_map,
        )
        status = int(mapping(record).get("http_status") or 0)
        if not 200 <= status < 300:
            metrics["all_pass"] = False
            metrics.setdefault("suggestions", []).append(f"HTTP request failed with {status}")
        positive_result = {
            "case_id": case_m.get("id"),
            "profile_id": case_m.get("profile_id"),
            "is_negative": False,
            **metrics,
        }
        positive_results.append(positive_result)
        aggregate_inputs.append(positive_result)
    aggregate = aggregate_case_results(aggregate_inputs)
    return aggregate, positive_results, negative_results


def _fmt_rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def print_problem1(
    link_a: dict[str, Any],
    link_b: dict[str, Any],
    e2e: dict[str, Any],
    attribution: dict[str, Any],
    checks: list[dict[str, Any]],
) -> bool:
    print("=====【问题1：学习者画像-资源难度适配准确率】结果 =====")
    print()

    print("【样本概况】")
    n_samples = link_a.get("n_samples", 0)
    print(
        f"  链路A 有效画像样本数: {n_samples}"
        + (
            f"（缺诊断难度 {link_a.get('n_missing_pred', 0)}）"
            if link_a.get("n_missing_pred")
            else ""
        )
    )
    if n_samples < settings.ADAPTATION_MIN_SAMPLES:
        print(
            f"  ⚠ 警告：样本数 {n_samples} < {settings.ADAPTATION_MIN_SAMPLES}，"
            "样本不足，统计结果可信度低，结论仅供参考。"
        )
    print()

    print("【链路A - Agent1 画像判定各项指标】")
    if link_a.get("not_applicable"):
        print(f"  不适用：{link_a.get('reason')}")
    else:
        print(
            f"  画像判定准确率 (PDCA)      : {_fmt_rate(link_a['pdca'])}"
            f"  (目标 ≥ {_fmt_rate(settings.ADAPTATION_PDCA_TARGET)})"
        )
        print(
            f"  相邻档位容错率 (OffByOne)  : {_fmt_rate(link_a['off_by_one'])}"
            f"  (目标 ≥ {_fmt_rate(settings.ADAPTATION_OFFBYONE_TARGET)})"
        )
        print(
            f"  线性加权 Cohen's Kappa     : {_fmt_rate(link_a['kappa'])}"
            f"  (目标 ≥ {_fmt_rate(settings.ADAPTATION_KAPPA_TARGET)})"
        )
        print(
            f"  系统性偏置 (bias, 正=偏难) : {link_a['bias']:+.3f}"
            f"  (范围 [{settings.ADAPTATION_BIAS_MIN:+.2f}, {settings.ADAPTATION_BIAS_MAX:+.2f}])"
        )
        print(
            f"  平均绝对误差 (MAE, 档位)   : {link_a['mae']:.3f}"
            f"  (目标 ≤ {settings.ADAPTATION_MAE_TARGET:.2f})"
        )
        print("  混淆矩阵 (行=真值, 列=判定):")
        print("          " + "  ".join(f"{label:<12}" for label in DIFF_LABELS))
        for i, row in enumerate(link_a["confusion"]):
            print(f"    {DIFF_LABELS[i]:<8} " + "  ".join(f"{v:<12}" for v in row))
    print()

    print("【链路B - 原有 compute_adaptation 资源适配准确率】")
    if link_b.get("not_applicable"):
        print(f"  不适用：{link_b.get('reason')}")
    else:
        print(
            f"  适配率 (difficulty+style)/2 : {_fmt_rate(link_b['rate'])}"
            f"  (目标 ≥ {_fmt_rate(settings.ADAPTATION_TARGET)})"
        )
        print(f"    ├─ 难度匹配 (difficulty)  : {_fmt_rate(link_b['difficulty_match'])}")
        print(f"    └─ 风格匹配 (style)       : {_fmt_rate(link_b['style_match'])}")
        print(f"  评估样本数: {link_b['evaluated_cases']}")
    print()

    print("【端到端一致性 - Agent2 是否遵从 Agent1 给出的难度】")
    if e2e.get("not_applicable"):
        print(f"  不适用：{e2e.get('reason')}")
    else:
        print(
            f"  一致性 (资源难度==判定难度) : {_fmt_rate(e2e['rate'])}"
            f"  ({e2e['matched']}/{e2e['total']})"
            f"  (目标 ≥ {_fmt_rate(settings.ADAPTATION_E2E_TARGET)})"
        )
    print()

    cells = attribution["cells"]
    print("【2×2 归因统计表（资源粒度，行=Agent1 判定，列=Agent2 遵从）】")
    print("                        Agent2 遵从       Agent2 未遵从")
    print(f"  Agent1 判定正确        {cells['a1_ok_a2_ok']:<16} {cells['a1_ok_a2_bad']}")
    print(f"  Agent1 判定错误        {cells['a1_bad_a2_ok']:<16} {cells['a1_bad_a2_bad']}")
    print(
        f"  共 {attribution['total_resources']} 条资源"
        + (
            f"，另有 {attribution['skipped_resources']} 条缺难度标注无法归因"
            if attribution["skipped_resources"]
            else ""
        )
    )
    print("  错误根源归因:")
    print(f"    - Agent1 判断出错（含双重）: {attribution['agent1_errors']} 条")
    print(f"    - Agent2 未遵守难度指令（含双重）: {attribution['agent2_errors']} 条")
    print()

    failed = [c for c in checks if not c["passed"]]
    passed = not failed
    print("【门禁校验】")
    for check in checks:
        mark = "通过" if check["passed"] else "不通过"
        actual = check["actual"]
        actual_str = "N/A" if actual is None else f"{actual:.4f}"
        print(
            f"  [{mark}] {check['name']}: {actual_str} {check['op']} "
            f"{check['threshold']:.4f}"
            + (f"  ← 责任 {check['blame']}" if not check["passed"] else "")
        )
    # 分别标注画像链路、资源链路是否达标（两套门禁独立校验，互不放宽）
    links: dict[str, list[dict[str, Any]]] = {}
    for check in checks:
        links.setdefault(check.get("link", "其他"), []).append(check)
    for link_name, link_checks in links.items():
        link_pass = all(c["passed"] for c in link_checks)
        link_blame = {c["blame"] for c in link_checks if not c["passed"] and c["blame"]}
        if link_pass:
            print(f"  {link_name}：达标")
        else:
            blame_str = " / ".join(sorted(link_blame)) if link_blame else "（未定位到责任 Agent）"
            print(f"  {link_name}：不达标，责任 {blame_str}")

    if passed:
        print("  门禁校验：通过")
    else:
        blame = {check["blame"] for check in failed if check["blame"]}
        print("  门禁校验：不通过，失败对应 Agent：" + " / ".join(sorted(blame)))
    print()
    return passed


def print_problem2(
    aggregate: dict[str, Any],
    positive_results: Sequence[dict[str, Any]],
    negative_results: Sequence[dict[str, Any]],
) -> bool:
    print("=====【问题2】结果 =====")
    print()
    print("【问题2 全套计算指标数值（复用原有 compute_all + aggregate_case_results）】")
    print(
        f"  幻觉率 (hallucination) : {_fmt_rate(aggregate['hallucination']['rate'])}"
        f"  (目标 < {_fmt_rate(settings.HALLUCINATION_THRESHOLD)})"
    )
    print(
        f"  适配率 (adaptation)    : {_fmt_rate(aggregate['adaptation']['rate'])}"
        f"  (目标 ≥ {_fmt_rate(settings.ADAPTATION_TARGET)})"
    )
    print(
        f"  覆盖率 (coverage)      : {_fmt_rate(aggregate['coverage']['rate'])}"
        f"  (目标 ≥ {_fmt_rate(settings.COVERAGE_TARGET)})"
    )
    print(
        f"  正例数: {aggregate.get('positive_case_count', 0)}"
        f"，负例数: {aggregate.get('negative_case_count', 0)}"
        f"，画像数: {aggregate.get('profile_count', 0)}"
    )
    print(f"  用例通过数: {aggregate.get('case_passed', 0)}/{aggregate.get('case_count', 0)}")
    req = aggregate.get("dataset_requirements", {})
    print(f"  数据集要求: {'通过' if req.get('pass') else '不通过'} {req.get('checks', {})}")
    print()
    print("【门禁校验】")
    all_pass = bool(aggregate.get("all_pass"))
    if all_pass:
        print("  门禁校验：通过")
    else:
        reasons = []
        if not aggregate.get("metrics_pass"):
            reasons.append("三项指标未全部达标")
        if not req.get("pass"):
            reasons.append("数据集要求未满足")
        if not aggregate.get("negative_cases_pass"):
            reasons.append("负例未全部通过")
        print("  门禁校验：不通过" + ("（" + "；".join(reasons) + "）" if reasons else ""))
    print()
    return all_pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--core-map", type=Path, default=DEFAULT_CORE_MAP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        outputs_doc = load_json(args.outputs)
        truth_by_profile = load_truth(args.truth)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"评估输入错误: {exc}")
        return 2

    records = outputs_doc.get("records", [])
    if not isinstance(records, list):
        print("评估输入错误: outputs 缺少 records 列表")
        return 2

    records_by_id: dict[str, Any] = {}
    for record in records:
        rec = mapping(record)
        cid = rec.get("case_id")
        if cid:
            records_by_id[str(cid)] = rec

    cases: list[dict[str, Any]] = []
    positive_case_ids: set[str] = set()
    core_map: Any = None
    if args.cases.exists():
        cases = [mapping(c) for c in load_json(args.cases).get("cases", [])]
        positive_case_ids = {str(c.get("id")) for c in cases if c.get("kind") == "positive"}
    if args.core_map.exists():
        core_map = load_json(args.core_map)

    # ── 问题1：链路A/B/E2E + 2×2 归因 ──
    evaluator = EvaluationMetrics()
    samples = collect_samples(records, truth_by_profile, positive_case_ids)
    link_a = compute_link_a(samples)
    link_b = compute_link_b(samples, evaluator)
    e2e = compute_e2e(samples)
    attribution = compute_attribution(samples)
    checks = build_gate_checks(link_a, link_b, e2e, attribution)
    problem1_pass = print_problem1(link_a, link_b, e2e, attribution, checks)
    print()

    # ── 问题2：复用原有指标逻辑 ──
    problem2_pass = True
    if cases:
        aggregate, positive_results, negative_results = asyncio.run(
            run_problem2(cases, records_by_id, core_map)
        )
        problem2_pass = print_problem2(aggregate, positive_results, negative_results)
    else:
        print("=====【问题2】结果 =====")
        print()
        print("  跳过：未提供 --cases（phase3_test_cases.json）")
        print()

    return 0 if (problem1_pass and problem2_pass) else 1


if __name__ == "__main__":
    raise SystemExit(main())

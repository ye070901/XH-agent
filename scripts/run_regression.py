"""XH-agent 部分支持质量风控回归检查脚本。

对一份 raw outputs（records）逐条匹配回归测试集中的 case claim，
按期望约束校验 verdict，输出通过/未通过/未找到明细与汇总。

用法：
    python scripts/run_regression.py <raw_outputs.json> [--cases regression_cases.json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "data" / "evaluation" / "regression_cases.json"


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).lower()


def iter_items(rec: dict) -> list[dict]:
    """遍历单个 record 的所有 fact_check items。"""
    resp = rec.get("response") or {}
    audit = resp.get("audit") if isinstance(resp, dict) else None
    items: list[dict] = []
    if isinstance(audit, list):
        for report in audit:
            if not isinstance(report, dict):
                continue
            fc = report.get("fact_check") or {}
            if isinstance(fc, dict) and isinstance(fc.get("items"), list):
                items.extend(fc["items"])
    return items


def find_item(records: list[dict], case_id: str, claim: str) -> dict | None:
    """在同一 case 的 fact_check 中精确匹配 claim（归一化后完全一致）。"""
    target = normalize(claim)
    for rec in records:
        if rec.get("case_id") != case_id:
            continue
        for it in iter_items(rec):
            if normalize(it.get("claim") or "") == target:
                return it
    return None


def check_case(records: list[dict], case: dict) -> tuple[str, dict | None]:
    """返回 (状态, 详情)：passed / failed / not_found。"""
    item = find_item(records, case["case_id"], case["claim"])
    if item is None:
        return "not_found", None
    verdict = str(item.get("verdict") or "")
    expected = case.get("expected", "")
    if expected == "kb_present_not_unverifiable":
        ok = verdict != "unverifiable"
    elif expected == "hallucination":
        ok = verdict == "hallucination"
    elif expected == "accurate":
        ok = verdict == "accurate"
    else:
        ok = True
    return ("passed" if ok else "failed"), {
        "verdict": verdict,
        "expected": expected,
        "evidence": (item.get("evidence_from_kb") or "")[:80],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()

    records = list(json.load(open(args.outputs, encoding="utf-8")).get("records", []))
    reg = json.load(open(args.cases, encoding="utf-8"))
    cases = reg.get("cases", [])

    passed = failed = not_found = 0
    detail_lines: list[str] = []
    for case in cases:
        status, detail = check_case(records, case)
        if status == "passed":
            passed += 1
        elif status == "failed":
            failed += 1
        else:
            not_found += 1
        tag = {"passed": "✅ 通过", "failed": "❌ 未达", "not_found": "⚠️ 未匹配"}[status]
        vd = f"verdict={detail['verdict']}" if detail else "—"
        detail_lines.append(
            f"{tag} [{case['id']}] {case['case_id']} | {vd} | 期望={case['expected']}\n"
            f"      claim: {case['claim'][:70]}\n"
            f"      {case.get('note', '')}"
        )

    print(f"回归测试集: {len(cases)} 条")
    print(f"通过 {passed} / 未达 {failed} / 未匹配 {not_found}\n")
    for line in detail_lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

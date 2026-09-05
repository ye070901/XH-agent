"""抽取全局幻觉率采样中的「unverifiable / hallucination」断言，按知识点归组。

用途：定位「知识库缺料」vs「检索未召回」vs「生成过度延伸」三类根因，
输出按 knowledge_point_id 归组的坏断言清单，供人工判断需补充哪些知识库内容。

Run:
    python scripts/audit_unverifiable_claims.py \
        --outputs data/evaluation/runs/phase3_raw_outputs_eval_sample.json \
        --cases data/evaluation/runs/phase3_test_cases_sample.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None


def load(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_fact_items(value):
    if isinstance(value, list):
        for child in value:
            yield from iter_fact_items(child)
        return
    if not isinstance(value, dict):
        return
    for container in ("fact_check", "audit_result", "items", "claims"):
        if container in value:
            yield from iter_fact_items(value[container])
            return
    if "verdict" in value or "is_accurate" in value:
        yield value


def verdict_for(item):
    v = str(item.get("verdict") or "").strip().casefold()
    if v:
        return v
    acc = item.get("is_accurate")
    if acc is True:
        return "accurate"
    if acc is False:
        return "hallucination"
    return "unverifiable"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", type=Path, required=True)
    ap.add_argument("--cases", type=Path, required=True)
    args = ap.parse_args()

    outputs = load(args.outputs)
    cases_doc = load(args.cases)
    case_by_id = {c["id"]: c for c in cases_doc.get("cases", [])}

    # knowledge_point_id → list[(case_id, profile_id, claim, verdict)]
    by_kp: dict[str, list[dict]] = defaultdict(list)
    total_bad = Counter()

    for rec in outputs.get("records", []):
        case_id = rec.get("case_id", "")
        case = case_by_id.get(case_id, {})
        kp = case.get("knowledge_point_id", "?")
        profile = rec.get("profile_id", "?")
        resp = rec.get("response") or {}
        audit = resp.get("audit") or []
        for item in iter_fact_items(audit):
            v = verdict_for(item)
            if v in ("unverifiable", "hallucination"):
                total_bad[v] += 1
                by_kp[kp].append(
                    {
                        "case_id": case_id,
                        "profile_id": profile,
                        "claim": str(item.get("claim") or "").strip(),
                        "verdict": v,
                        "evidence_from_kb": item.get("evidence_from_kb"),
                        "explanation": str(item.get("explanation") or "").strip(),
                    }
                )

    print(
        f"总坏断言: {sum(total_bad.values())} "
        f"(unverifiable={total_bad['unverifiable']}, "
        f"hallucination={total_bad['hallucination']})"
    )
    print()
    for kp in sorted(by_kp):
        rows = by_kp[kp]
        uv = sum(1 for r in rows if r["verdict"] == "unverifiable")
        hl = sum(1 for r in rows if r["verdict"] == "hallucination")
        print(
            f"\n{'=' * 70}\n## {kp}  共 {len(rows)} 条坏断言 "
            f"(unverifiable={uv}, hallucination={hl})"
        )
        # 去重显示，保留首现
        seen = set()
        for r in rows:
            key = r["claim"]
            if key in seen:
                continue
            seen.add(key)
            print(f"  [{r['verdict']}] {r['claim'][:160]}")
            if r["explanation"]:
                print(f"        └ {r['explanation'][:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

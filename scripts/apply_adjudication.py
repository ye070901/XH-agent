#!/usr/bin/env python3
"""Apply non-blank decisions from the Markdown adjudication table to JSON.

The output remains pending until independent annotator/reviewer approval is
recorded. This script never invents reviewer identities or signatures.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID = {"accurate", "unverifiable", "hallucination", "skip"}
ROW_RE = re.compile(r"^###\s+\d+\.\s+`([^`]+)`\s*$")
DECISION_RE = re.compile(r"^-\s+\*\*判定\*\*：`([^`]*)`.*?\*\*来源文档\*\*：`([^`]*)`\s*$")


def parse_table(path: Path) -> dict[str, dict[str, str]]:
    decisions: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        row = ROW_RE.match(line.strip())
        if row:
            current = row.group(1)
            continue
        if current is None:
            continue
        match = DECISION_RE.match(line.strip())
        if not match:
            continue
        verdict = match.group(1).strip().casefold()
        source = match.group(2).strip()
        if verdict in {"", "__"}:
            continue
        if verdict not in VALID:
            raise ValueError(f"invalid verdict {verdict!r} for {current}")
        decisions[current] = {
            "expected_verdict": verdict,
            "source_document": "" if source in {"", "__"} else source,
        }
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--annotator", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--review-status", default="pending_human_review")
    args = parser.parse_args()

    document: dict[str, Any] = json.loads(args.draft.read_text(encoding="utf-8"))
    decisions = parse_table(args.table)
    items = document.get("items")
    if not isinstance(items, list):
        raise ValueError("draft JSON must contain an items array")
    by_id = {str(item.get("claim_id")): item for item in items if item.get("claim_id")}
    applied = 0
    missing: list[str] = []
    for claim_id, decision in decisions.items():
        item = by_id.get(claim_id)
        if item is None:
            missing.append(claim_id)
            continue
        item["expected_verdict"] = decision["expected_verdict"]
        evidence = item.setdefault("evidence", {})
        if decision["source_document"]:
            evidence["source_document"] = decision["source_document"]
            evidence["locator"] = "仲裁表人工填写"
        elif decision["expected_verdict"] != "accurate":
            evidence["source_document"] = ""
            evidence["locator"] = "仲裁表人工填写：无支持来源"
        item["rationale"] = (
            f"K1 标注、K2 复核结论：{decision['expected_verdict']}。依据当前知识库证据完成核验。"
        )
        if args.annotator:
            item["annotator"] = args.annotator
        if args.reviewer:
            item["reviewer"] = args.reviewer
        if args.annotator or args.reviewer:
            item["annotated_at"] = datetime.now(timezone.utc).isoformat()
        item["review_status"] = args.review_status
        applied += 1

    meta = document.setdefault("meta", {})
    meta.update(
        {
            "name": "Agent3 三态判定人工金标准（K1-K7 扩展）",
            "version": "1.0-pending-human-review",
            "sample_count": len(items),
            "workflow_status": args.review_status,
            "adjudication_table": str(args.table),
            "adjudication_applied_count": applied,
            "adjudication_missing_claim_ids": missing,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "instructions": (
                "候选正式金标准：仲裁表已填写的结论已回填；空白项仍待 K1/K2/K3 人工仲裁。"
                "发布前每条事实断言必须填写不同的 annotator/reviewer、annotated_at，"
                "并将 review_status 设为 approved。"
            ),
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(items)} items; applied {applied} decisions)")
    if missing:
        print(f"warning: {len(missing)} table claim IDs were not found in draft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

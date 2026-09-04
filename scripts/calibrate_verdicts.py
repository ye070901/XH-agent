#!/usr/bin/env python3
"""Calibrate Agent3 verdicts against independently approved gold labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FACT_VERDICTS = {"accurate", "hallucination", "unverifiable"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def predictions(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, dict) and isinstance(document.get("gold_candidate_claims"), list):
        rows = document["gold_candidate_claims"]
    elif isinstance(document, dict) and isinstance(document.get("items"), list):
        rows = document["items"]
    elif isinstance(document, list):
        rows = document
    else:
        return []
    return [
        {
            "claim_id": row["claim_id"],
            "verdict": str(
                row.get("verdict") or row.get("agent3_predicted_verdict") or "unverifiable"
            ).casefold(),
        }
        for row in rows
        if isinstance(row, dict) and row.get("claim_id")
    ]


def gold_rows(document: Any, include_pending: bool) -> list[dict[str, Any]]:
    rows = document.get("items", []) if isinstance(document, dict) else []
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get("expected_verdict") not in FACT_VERDICTS:
            continue
        if not include_pending and (
            row.get("review_status") != "approved"
            or not row.get("annotator")
            or not row.get("reviewer")
            or row.get("annotator") == row.get("reviewer")
        ):
            continue
        result.append(row)
    return result


def calibrate(
    predicted: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    minimum_accuracy: float,
    minimum_gold: int,
) -> dict[str, Any]:
    pred = {row["claim_id"]: row["verdict"] for row in predicted}
    confusion: dict[str, dict[str, int]] = {}
    missing: list[str] = []
    correct = 0
    used: set[str] = set()
    for row in gold:
        key, expected = row["claim_id"], row["expected_verdict"]
        if key not in pred:
            missing.append(key)
            continue
        actual = pred[key]
        used.add(key)
        bucket = confusion.setdefault(expected, {})
        bucket[actual] = bucket.get(actual, 0) + 1
        correct += int(actual == expected)
    total = len(gold)
    accuracy = correct / total if total else 0.0
    return {
        "status": "evaluated" if total >= minimum_gold else "not_ready",
        "accuracy": round(accuracy, 4),
        "pass": bool(total >= minimum_gold and accuracy >= minimum_accuracy),
        "correct": correct,
        "total_gold": total,
        "matched": total - len(missing),
        "missing_prediction_keys": missing,
        "unexpected_prediction_keys": sorted(set(pred) - used),
        "confusion_matrix": confusion,
        "minimum_accuracy": minimum_accuracy,
        "minimum_gold_items": minimum_gold,
        "dataset_size_pass": total >= minimum_gold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--minimum-accuracy", type=float, default=0.90)
    parser.add_argument("--minimum-gold-items", type=int, default=50)
    parser.add_argument(
        "--include-pending", action="store_true", help="diagnostic only; not a release metric"
    )
    args = parser.parse_args()
    result = calibrate(
        predictions(load(args.predictions)),
        gold_rows(load(args.gold), args.include_pending),
        args.minimum_accuracy,
        args.minimum_gold_items,
    )
    result.update(
        {
            "predictions_file": str(args.predictions),
            "gold_file": str(args.gold),
            "include_pending": args.include_pending,
        }
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "evaluated" else 2


if __name__ == "__main__":
    raise SystemExit(main())

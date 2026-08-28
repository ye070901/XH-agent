"""Evaluate saved Phase 3 pipeline outputs without calling an LLM.

The runner deliberately ignores model-produced profile/gap predictions when it
scores adaptation and coverage.  It uses ``expected_profile`` and
``expected_gaps`` from the externally authored case set, calls the production
``backend.src.evaluation.metrics`` implementation, evaluates negative cases in
a separate section, and writes a reproducible JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.evaluation.metrics import (  # noqa: E402
    EvaluationMetrics,
    aggregate_case_results,
    calibrate_verdicts,
)

DEFAULT_CASES = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases.json"
DEFAULT_CORE_MAP = REPO_ROOT / "data" / "core_knowledge_map.json"
DEFAULT_GOLD = REPO_ROOT / "data" / "evaluation" / "gold_labels.json"
VALID_FACT_VERDICTS = {"accurate", "hallucination", "unverifiable", "partially_supported"}


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


def response_parts(response: Any) -> tuple[dict[str, Any], list[Any], Any]:
    payload = mapping(response)
    nested = mapping(payload.get("result"))
    diagnosis = mapping(
        payload.get("diagnosis")
        or payload.get("diagnosis_result")
        or nested.get("diagnosis")
        or nested.get("diagnosis_result")
    )
    resources = (
        payload.get("resources")
        or payload.get("generated_resources")
        or nested.get("resources")
        or nested.get("generated_resources")
        or []
    )
    if not isinstance(resources, list):
        resources = []
    audit = (
        payload.get("audit")
        or payload.get("audit_result")
        or nested.get("audit")
        or nested.get("audit_result")
        or []
    )
    return diagnosis, resources, audit


def iter_fact_items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from iter_fact_items(child)
        return
    item = mapping(value)
    if not item:
        return
    for container in ("fact_check", "audit_result", "items", "claims"):
        if container in item:
            yield from iter_fact_items(item[container])
            return
    if "verdict" in item or "is_accurate" in item:
        yield item


def verdict_for(item: Mapping[str, Any]) -> str:
    verdict = str(item.get("verdict") or "").strip().casefold()
    if verdict:
        return verdict
    accurate = item.get("is_accurate")
    if accurate is True:
        return "accurate"
    if accurate is False:
        return "hallucination"
    return "unverifiable"


def resource_text(resources: Sequence[Any]) -> str:
    return "\n".join(
        json.dumps(resource, ensure_ascii=False, sort_keys=True) for resource in resources
    )


def labelled_gold_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    ready: list[dict[str, Any]] = []
    seen_claim_ids: set[str] = set()
    for raw in items:
        item = mapping(raw)
        verdict = item.get("expected_verdict")
        claim_id = str(item.get("claim_id") or "").strip()
        annotator = str(item.get("annotator") or "").strip()
        reviewer = str(item.get("reviewer") or "").strip()
        evidence_source = str(mapping(item.get("evidence")).get("source_document") or "").strip()
        if (
            verdict in VALID_FACT_VERDICTS
            and claim_id
            and claim_id not in seen_claim_ids
            and str(item.get("claim") or "").strip()
            and str(item.get("rationale") or "").strip()
            and str(item.get("annotated_at") or "").strip()
            and annotator
            and reviewer
            and annotator != reviewer
            and item.get("review_status") == "approved"
            and (
                verdict != "accurate"
                or (evidence_source and (REPO_ROOT / evidence_source).is_file())
            )
        ):
            ready.append(item)
            seen_claim_ids.add(claim_id)
    return ready


def validate_run_inputs(
    cases: list[dict[str, Any]], records: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    positives = [case for case in cases if case.get("kind") == "positive"]
    negatives = [case for case in cases if case.get("kind") == "negative"]
    profiles = {case.get("profile_id") for case in cases}
    if len(cases) < 50:
        errors.append(f"case set has {len(cases)} cases; at least 50 required")
    if len(profiles) < 3:
        errors.append(f"case set has {len(profiles)} profiles; at least 3 required")
    if not 3 <= len(negatives) <= 5:
        errors.append(f"negative case count is {len(negatives)}; required range is 3..5")
    for case in positives:
        profile = case.get("expected_profile", {})
        if not profile.get("expected_difficulty") or not profile.get("expected_learning_style"):
            errors.append(f"{case.get('id')}: external expected_profile is incomplete")
        if not case.get("expected_gaps"):
            errors.append(f"{case.get('id')}: external expected_gaps is empty")

    records_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = record.get("case_id")
        if not case_id or case_id in records_by_id:
            errors.append(f"raw outputs contain missing/duplicate case_id {case_id!r}")
            continue
        records_by_id[case_id] = record
    case_ids = {case["id"] for case in cases}
    missing = sorted(case_ids - set(records_by_id))
    extra = sorted(set(records_by_id) - case_ids)
    if missing:
        errors.append(f"raw outputs are missing {len(missing)} required cases")
    if extra:
        errors.append(f"raw outputs contain {len(extra)} unknown cases")
    return records_by_id, errors


def evaluate_negative_case(
    evaluator: EvaluationMetrics,
    case: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    _, resources, audit = response_parts(record.get("response"))
    checks = mapping(case.get("expected_behavior"))
    facts = list(iter_fact_items(audit))
    verdicts = sorted({verdict_for(item) for item in facts})
    response_text = json.dumps(record.get("response"), ensure_ascii=False, sort_keys=True)
    resources_text = resource_text(resources)
    outcomes: list[dict[str, Any]] = []

    status = int(record.get("http_status") or 0)
    outcomes.append(
        {
            "check": "http_success",
            "pass": 200 <= status < 300,
            "observed": status,
        }
    )
    required_verdicts = set(checks.get("required_audit_verdicts_any", []))
    if required_verdicts:
        outcomes.append(
            {
                "check": "required_audit_verdicts_any",
                "pass": bool(required_verdicts.intersection(verdicts)),
                "expected": sorted(required_verdicts),
                "observed": verdicts,
            }
        )
    required_markers = checks.get("required_response_markers_any", [])
    if required_markers:
        outcomes.append(
            {
                "check": "required_response_markers_any",
                "pass": any(marker in response_text for marker in required_markers),
                "expected": required_markers,
            }
        )
    forbidden_markers = checks.get("forbidden_resource_markers", [])
    if forbidden_markers:
        found = [marker for marker in forbidden_markers if marker in resources_text]
        outcomes.append(
            {
                "check": "forbidden_resource_markers",
                "pass": not found,
                "found": found,
            }
        )
    minimum_adaptation = checks.get("minimum_adaptation_rate")
    if minimum_adaptation is not None:
        adaptation = evaluator.compute_adaptation(
            {},
            resources,
            expected_profile=case["expected_profile"],
        )
        outcomes.append(
            {
                "check": "minimum_adaptation_rate",
                "pass": adaptation["rate"] >= float(minimum_adaptation),
                "expected": float(minimum_adaptation),
                "observed": adaptation["rate"],
            }
        )
    return {
        "case_id": case["id"],
        "category": case.get("negative_category"),
        "expected_disposition": checks.get("expected_disposition"),
        "pass": bool(outcomes and all(outcome["pass"] for outcome in outcomes)),
        "checks": outcomes,
    }


async def evaluate(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    cases_doc = load_json(args.cases)
    outputs_doc = load_json(args.outputs)
    core_map = load_json(args.core_map)
    cases = list(cases_doc.get("cases", []))
    records = list(outputs_doc.get("records", []))
    records_by_id, errors = validate_run_inputs(cases, records)
    if errors:
        raise ValueError("; ".join(errors))

    evaluator = EvaluationMetrics()
    positive_results: list[dict[str, Any]] = []
    negative_results: list[dict[str, Any]] = []
    aggregate_inputs: list[dict[str, Any]] = []
    claim_candidates: list[dict[str, Any]] = []
    all_predictions: list[dict[str, Any]] = []
    for case in cases:
        record = records_by_id[case["id"]]
        if case["kind"] == "negative":
            negative_result = evaluate_negative_case(evaluator, case, record)
            negative_results.append(negative_result)
            aggregate_inputs.append(
                {
                    "case_id": case["id"],
                    "profile_id": case["profile_id"],
                    "is_negative": True,
                    "negative_pass": negative_result["pass"],
                }
            )
            continue
        _, resources, audit = response_parts(record.get("response"))
        # Coverage truth is external.  The model's own diagnosis/skill_gaps are
        # intentionally not passed to the metric implementation.
        metrics = await evaluator.compute_all(
            audit,
            {},
            resources,
            expected_profile=case["expected_profile"],
            expected_gaps=case["expected_gaps"],
            core_knowledge_map=core_map,
        )
        status = int(record.get("http_status") or 0)
        if not 200 <= status < 300:
            metrics["all_pass"] = False
            metrics.setdefault("suggestions", []).append(f"HTTP request failed with {status}")
        positive_result = {
            "case_id": case["id"],
            "profile_id": case["profile_id"],
            "is_negative": False,
            **metrics,
        }
        positive_results.append(positive_result)
        aggregate_inputs.append(positive_result)

        for index, item in enumerate(iter_fact_items(audit), start=1):
            source_id = item.get("claim_id") or item.get("id") or f"claim-{index:03d}"
            claim_id = f"{case['id']}:{source_id}:{index:03d}"
            prediction = dict(item)
            prediction["claim_id"] = claim_id
            prediction["verdict"] = verdict_for(item)
            all_predictions.append(prediction)
            claim_candidates.append(
                {
                    "claim_id": claim_id,
                    "case_id": case["id"],
                    "claim": item.get("claim") or item.get("statement"),
                    "agent3_predicted_verdict": prediction["verdict"],
                    "citation_ref": item.get("citation_ref"),
                    "note": "prediction only; a human must supply expected_verdict",
                }
            )

    aggregate = aggregate_case_results(aggregate_inputs)
    negative_passed = sum(result["pass"] for result in negative_results)

    calibration: dict[str, Any]
    if args.gold_file.is_file():
        gold_doc = load_json(args.gold_file)
        gold_items = labelled_gold_items(gold_doc.get("items"))
        if len(gold_items) >= 50:
            calibration = {
                "status": "evaluated",
                **calibrate_verdicts(all_predictions, gold_items),
                "approved_fact_labels": len(gold_items),
            }
        else:
            calibration = {
                "status": "not_ready",
                "approved_fact_labels": len(gold_items),
                "required_fact_labels": 50,
                "pass": False,
            }
    else:
        calibration = {
            "status": "missing_gold_file",
            "approved_fact_labels": 0,
            "required_fact_labels": 50,
            "pass": False,
        }

    release_ready = bool(
        aggregate["all_pass"]
        and negative_results
        and negative_passed == len(negative_results)
        and calibration.get("pass")
    )
    report = {
        "meta": {
            "name": "O4 Phase 3 evaluation report",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "source_cases": str(args.cases),
            "source_outputs": str(args.outputs),
            "truth_policy": (
                "adaptation uses case.expected_profile; coverage uses case.expected_gaps; "
                "model diagnosis is never used as ground truth"
            ),
            "calls_llm": False,
        },
        "data_quality": {
            "case_count": len(cases),
            "positive_case_count": len(positive_results),
            "negative_case_count": len(negative_results),
            "profile_count": len({case["profile_id"] for case in cases}),
            "raw_output_record_count": len(records),
        },
        "aggregate_metrics": aggregate,
        "positive_case_results": positive_results,
        "negative_evaluation": {
            "passed": negative_passed,
            "total": len(negative_results),
            "all_pass": bool(negative_results and negative_passed == len(negative_results)),
            "results": negative_results,
        },
        "agent3_gold_calibration": calibration,
        "gold_candidate_claims": claim_candidates,
        "release_ready": release_ready,
    }
    return report, release_ready


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--core-map", type=Path, default=DEFAULT_CORE_MAP)
    parser.add_argument("--gold-file", type=Path, default=DEFAULT_GOLD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report, release_ready = asyncio.run(evaluate(args))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Evaluation input error: {exc}")
        return 2
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    aggregate = report["aggregate_metrics"]
    calibration = report["agent3_gold_calibration"]
    print(
        "Saved evaluation report to "
        f"{args.output_report}; metrics_pass={aggregate['all_pass']}, "
        f"negative_pass={report['negative_evaluation']['all_pass']}, "
        f"gold_status={calibration['status']}, release_ready={release_ready}."
    )
    return 0 if release_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate Phase 3 truth data, case counts, provenance, and human gold labels.

By default the command is release-gating: fewer than 50 fully annotated and
independently reviewed gold claims is a failure.  Use ``--dataset-only`` while
the K groups are still annotating to validate the non-gold dataset structure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"
DEFAULT_CORE_MAP = REPO_ROOT / "data" / "core_knowledge_map.json"
DEFAULT_CASES = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases.json"
DEFAULT_GOLD = REPO_ROOT / "data" / "evaluation" / "gold_labels_k1k7.json"
VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
VALID_STYLES = {"theory_first", "practice_first", "visual", "project_based"}
VALID_LEVELS = {"core", "high", "standard"}
VALID_VERDICTS = {"accurate", "hallucination", "unverifiable", "partially_supported", "skip"}


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        errors.append(f"missing file: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"top-level JSON must be an object: {path}")
        return {}
    return data


def validate_core_map(document: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    points: dict[str, dict[str, Any]] = {}
    counted = set(document.get("meta", {}).get("counted_levels", []))
    if counted != {"core", "high"}:
        errors.append("core map counted_levels must be exactly ['core', 'high']")
    topics: set[str] = set()
    for domain in document.get("domains", []):
        domain_id = domain.get("id")
        for point in domain.get("knowledge_points", []):
            point_id = point.get("id")
            topic = str(point.get("topic") or "").strip()
            level = point.get("level")
            prefix = f"core point {point_id or '<missing-id>'}"
            if not point_id or point_id in points:
                errors.append(f"{prefix}: id is missing or duplicated")
                continue
            if not topic or topic in topics:
                errors.append(f"{prefix}: topic is missing or duplicated")
            if level not in VALID_LEVELS:
                errors.append(f"{prefix}: invalid level {level!r}")
            sources = point.get("source_documents", [])
            if not sources:
                errors.append(f"{prefix}: source_documents must not be empty")
            for source in sources:
                if not (REPO_ROOT / str(source)).is_file():
                    errors.append(f"{prefix}: source does not exist: {source}")
            if not point.get("aliases"):
                errors.append(f"{prefix}: aliases must not be empty")
            item = dict(point)
            item["domain"] = domain_id
            points[point_id] = item
            topics.add(topic)
    counted_points = [point for point in points.values() if point.get("level") in counted]
    if len(counted_points) < 12:
        errors.append(f"core map has {len(counted_points)} countable points; at least 12 required")
    declared_count = document.get("meta", {}).get("counted_knowledge_points")
    if declared_count != len(counted_points):
        errors.append(
            f"core map declares {declared_count} countable points but "
            f"contains {len(counted_points)}"
        )
    return points


def validate_profiles(document: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for profile in document.get("profiles", []):
        profile_id = profile.get("id")
        prefix = f"profile {profile_id or '<missing-id>'}"
        if not profile_id or profile_id in profiles:
            errors.append(f"{prefix}: id is missing or duplicated")
            continue
        learner_input = profile.get("input", {})
        for required in ("name", "education_level", "learning_goal", "pretest_results"):
            if required not in learner_input or learner_input[required] in (None, "", []):
                errors.append(f"{prefix}: input.{required} is required")
        truth = profile.get("expected_profile", {})
        if truth.get("expected_difficulty") not in VALID_DIFFICULTIES:
            errors.append(f"{prefix}: invalid expected_difficulty")
        if truth.get("expected_learning_style") not in VALID_STYLES:
            errors.append(f"{prefix}: invalid expected_learning_style")
        for rationale in ("difficulty_rationale", "style_rationale"):
            if not str(truth.get(rationale) or "").strip():
                errors.append(f"{prefix}: {rationale} is required")
        profiles[profile_id] = profile
    if len(profiles) < 3:
        errors.append(f"only {len(profiles)} learner profiles; at least 3 required")
    declared_count = document.get("meta", {}).get("profile_count")
    if declared_count != len(profiles):
        errors.append(f"profiles declares {declared_count} but contains {len(profiles)}")
    return profiles


def validate_cases(
    document: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    points: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    cases = document.get("cases", [])
    if len(cases) < 50:
        errors.append(f"only {len(cases)} cases; at least 50 required")
    ids: set[str] = set()
    positive_pairs: set[tuple[str, str]] = set()
    used_profiles: set[str] = set()
    negative_count = 0
    counted_point_ids = {
        point_id for point_id, point in points.items() if point.get("level") in {"core", "high"}
    }

    for case in cases:
        case_id = case.get("id")
        prefix = f"case {case_id or '<missing-id>'}"
        if not case_id or case_id in ids:
            errors.append(f"{prefix}: id is missing or duplicated")
            continue
        ids.add(case_id)
        profile_id = case.get("profile_id")
        profile = profiles.get(profile_id)
        if profile is None:
            errors.append(f"{prefix}: unknown profile_id {profile_id!r}")
            continue
        used_profiles.add(profile_id)
        if any(
            key in case
            for key in ("actual_output", "response", "metric_result", "measured_metrics")
        ):
            errors.append(
                f"{prefix}: case truth file must not contain model output or measured metrics"
            )
        request = case.get("input", {})
        if not request.get("learning_goal") or not request.get("resource_types"):
            errors.append(f"{prefix}: runnable input is incomplete")
        external_profile = case.get("expected_profile", {})
        canonical = profile.get("expected_profile", {})
        if external_profile.get("expected_difficulty") != canonical.get("expected_difficulty"):
            errors.append(f"{prefix}: expected_difficulty differs from external profile truth")
        if external_profile.get("expected_learning_style") != canonical.get(
            "expected_learning_style"
        ):
            errors.append(f"{prefix}: expected_learning_style differs from external profile truth")
        if not case.get("truth_provenance"):
            errors.append(f"{prefix}: truth_provenance is required")

        if case.get("kind") == "negative":
            negative_count += 1
            if not case.get("negative_category"):
                errors.append(f"{prefix}: negative_category is required")
            behavior = case.get("expected_behavior", {})
            if not behavior.get("expected_disposition"):
                errors.append(f"{prefix}: negative expected_disposition is required")
            continue

        if case.get("kind") != "positive":
            errors.append(f"{prefix}: kind must be positive or negative")
            continue
        point_id = case.get("knowledge_point_id")
        if point_id not in counted_point_ids:
            errors.append(f"{prefix}: positive case references non-counted point {point_id!r}")
            continue
        pair = (profile_id, point_id)
        if pair in positive_pairs:
            errors.append(f"{prefix}: duplicate profile/knowledge-point pair {pair}")
        positive_pairs.add(pair)
        point = points[point_id]
        gaps = case.get("expected_gaps", [])
        expected_priority = "critical" if point["level"] == "core" else "high"
        if gaps != [
            {
                "knowledge_point_id": point_id,
                "topic": point["topic"],
                "priority": expected_priority,
            }
        ]:
            errors.append(f"{prefix}: expected_gaps differs from core-map truth")
        evidence = case.get("expected_behavior", {}).get("acceptable_evidence_documents", [])
        if not evidence or not set(evidence).issubset(set(point.get("source_documents", []))):
            errors.append(f"{prefix}: evidence documents are not grounded in the core map")

    expected_pairs = {
        (profile_id, point_id) for profile_id in profiles for point_id in counted_point_ids
    }
    missing_pairs = expected_pairs - positive_pairs
    extra_pairs = positive_pairs - expected_pairs
    if missing_pairs:
        errors.append(f"Cartesian product is missing {len(missing_pairs)} positive pairs")
    if extra_pairs:
        errors.append(f"Cartesian product has {len(extra_pairs)} unexpected positive pairs")
    if len(used_profiles) < 3:
        errors.append(f"cases use only {len(used_profiles)} profiles; at least 3 required")
    if not 3 <= negative_count <= 5:
        errors.append(f"negative case count is {negative_count}; required range is 3..5")

    meta = document.get("meta", {})
    if meta.get("case_count") != len(cases):
        errors.append("case meta.case_count does not match cases length")
    if meta.get("positive_case_count") != len(positive_pairs):
        errors.append("case meta.positive_case_count does not match positive cases")
    if meta.get("negative_case_count") != negative_count:
        errors.append("case meta.negative_case_count does not match negative cases")
    if meta.get("profile_count") != len(used_profiles):
        errors.append("case meta.profile_count does not match used profiles")
    if meta.get("counted_knowledge_point_count") != len(counted_point_ids):
        errors.append("case meta.counted_knowledge_point_count does not match core map")
    if meta.get("contains_model_outputs") is not False:
        errors.append("case meta must explicitly declare contains_model_outputs=false")
    if meta.get("contains_measured_metrics") is not False:
        errors.append("case meta must explicitly declare contains_measured_metrics=false")


def validate_gold(document: dict[str, Any], errors: list[str]) -> int:
    items = document.get("items", [])
    if not isinstance(items, list):
        errors.append("gold items must be an array")
        return 0
    approved = 0
    claim_ids: set[str] = set()
    for index, item in enumerate(items):
        prefix = f"gold item #{index + 1}"
        claim_id = str(item.get("claim_id") or "").strip()
        claim = str(item.get("claim") or "").strip()
        verdict = item.get("expected_verdict")
        annotator = str(item.get("annotator") or "").strip()
        reviewer = str(item.get("reviewer") or "").strip()
        complete = True
        if not claim_id or claim_id in claim_ids:
            errors.append(f"{prefix}: claim_id is missing or duplicated")
            complete = False
        claim_ids.add(claim_id)
        if not claim:
            errors.append(f"{prefix}: claim text is required")
            complete = False
        if verdict not in VALID_VERDICTS:
            errors.append(f"{prefix}: invalid expected_verdict {verdict!r}")
            complete = False
        for field in ("rationale", "annotated_at"):
            if not str(item.get(field) or "").strip():
                errors.append(f"{prefix}: {field} is required")
                complete = False
        if not annotator or not reviewer or annotator == reviewer:
            errors.append(f"{prefix}: independent annotator and reviewer are required")
            complete = False
        if item.get("review_status") != "approved":
            errors.append(f"{prefix}: review_status must be approved")
            complete = False
        if verdict == "accurate" and not item.get("evidence", {}).get("source_document"):
            errors.append(f"{prefix}: accurate claim requires evidence.source_document")
            complete = False
        elif verdict == "accurate":
            source = str(item["evidence"]["source_document"])
            if not (REPO_ROOT / source).is_file():
                errors.append(f"{prefix}: evidence source does not exist: {source}")
                complete = False
        # ``skip`` is useful for checking sentence classification, but it is a
        # non-claim and therefore does not count toward the required 50 facts.
        if complete and verdict != "skip":
            approved += 1
    if approved < 50:
        errors.append(
            f"only {approved} fully annotated and independently approved fact labels; "
            "at least 50 required"
        )
    return approved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--core-map", type=Path, default=DEFAULT_CORE_MAP)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--gold-file", type=Path, default=DEFAULT_GOLD)
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Validate profiles/core map/cases but do not release-gate on human gold yet.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    core_map = load_json(args.core_map, errors)
    profiles_doc = load_json(args.profiles, errors)
    cases_doc = load_json(args.cases, errors)
    points = validate_core_map(core_map, errors) if core_map else {}
    profiles = validate_profiles(profiles_doc, errors) if profiles_doc else {}
    if cases_doc:
        validate_cases(cases_doc, profiles, points, errors)
    if not args.dataset_only:
        gold = load_json(args.gold_file, errors)
        if gold:
            validate_gold(gold, errors)

    if errors:
        print("Phase 3 validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1

    cases = cases_doc.get("cases", [])
    negatives = sum(case.get("kind") == "negative" for case in cases)
    counted = sum(point.get("level") in {"core", "high"} for point in points.values())
    suffix = " (gold not checked)" if args.dataset_only else ""
    print(
        "Phase 3 validation PASSED"
        f"{suffix}: {len(profiles)} profiles, {counted} core/high points, "
        f"{len(cases)} cases, {negatives} negative cases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 3 离线 runner 的端到端烟雾测试（不调用 LLM）。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from scripts.run_phase3_evaluation import evaluate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _positive_response(case: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected_profile"]
    topic = case["expected_gaps"][0]["topic"]
    style = expected["expected_learning_style"]
    return {
        "resources": [
            {
                "title": topic,
                "content": f"{topic} 的权威讲解与安全操作步骤。",
                "difficulty_level": expected["expected_difficulty"],
                "learning_style": style,
            }
        ],
        "audit": {
            "fact_check": {
                "items": [
                    {
                        "claim_id": "fact-001",
                        "claim": f"{topic} 测试断言",
                        "verdict": "accurate",
                    }
                ]
            }
        },
    }


def _negative_response(case: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected_profile"]
    response: dict[str, Any] = {
        "resources": [
            {
                "title": "安全响应",
                "content": "禁止旁路安全回路；无法核验的信息不得编造。",
                "difficulty_level": expected["expected_difficulty"],
                "learning_style": expected["expected_learning_style"],
            }
        ],
        "audit": {"fact_check": {"items": []}},
    }
    if case["expected_behavior"].get("required_audit_verdicts_any"):
        response["audit"]["fact_check"]["items"] = [
            {
                "claim_id": "negative-fact",
                "claim": "知识库外断言",
                "verdict": "unverifiable",
            }
        ]
    return response


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_runner_reaches_release_ready_only_with_all_gates(tmp_path: Path) -> None:
    cases_path = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases.json"
    cases_doc = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = cases_doc["cases"]
    records = []
    positive_cases = []
    for case in cases:
        if case["kind"] == "positive":
            response = _positive_response(case)
            positive_cases.append(case)
        else:
            response = _negative_response(case)
        records.append(
            {
                "case_id": case["id"],
                "http_status": 200,
                "response": response,
            }
        )

    outputs_path = tmp_path / "outputs.json"
    gold_path = tmp_path / "gold.json"
    report_path = tmp_path / "report.json"
    _write_json(outputs_path, {"records": records})
    gold_items = [
        {
            "claim_id": f"{case['id']}:fact-001:001",
            "claim": f"{case['expected_gaps'][0]['topic']} 测试断言",
            "expected_verdict": "accurate",
            "evidence": {
                "source_document": case["expected_behavior"]["acceptable_evidence_documents"][0]
            },
            "rationale": "烟雾测试中的确定性人工真值。",
            "annotator": "tester-a",
            "annotated_at": "2026-08-18T00:00:00Z",
            "reviewer": "tester-b",
            "review_status": "approved",
        }
        for case in positive_cases[:50]
    ]
    _write_json(gold_path, {"items": gold_items})

    args = argparse.Namespace(
        cases=cases_path,
        outputs=outputs_path,
        core_map=REPO_ROOT / "data" / "core_knowledge_map.json",
        gold_file=gold_path,
        output_report=report_path,
    )
    report, release_ready = asyncio.run(evaluate(args))

    assert report["data_quality"] == {
        "case_count": 424,
        "positive_case_count": 420,
        "negative_case_count": 4,
        "profile_count": 10,
        "raw_output_record_count": 424,
    }
    assert report["aggregate_metrics"]["all_pass"] is True
    assert report["negative_evaluation"]["all_pass"] is True
    assert report["gold_candidate_claims"][0]["claim_id"] == gold_items[0]["claim_id"]
    assert report["agent3_gold_calibration"]["pass"] is True, report["agent3_gold_calibration"]
    assert release_ready is True

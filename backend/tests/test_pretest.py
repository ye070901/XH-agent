"""Phase 3 前置测试题库、评分与 API 测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.api.pretests import router as pretests_router
from backend.src.evaluation.pretest import (
    load_question_bank,
    public_question_bank,
    score_pretest,
)
from backend.src.schemas import PretestSubmission


def _submission(learner_id: str, answers: list[dict[str, str]]) -> PretestSubmission:
    return PretestSubmission.model_validate({"learner_id": learner_id, "answers": answers})


def test_public_question_bank_never_exposes_answers_or_explanations() -> None:
    private = load_question_bank()
    public = public_question_bank()

    assert public["meta"] == private["meta"]
    assert len(public["questions"]) == len(private["questions"]) == 12
    assert all("correct_answer" in question for question in private["questions"])
    for question in public["questions"]:
        assert "correct_answer" not in question
        assert "explanation" not in question
        assert {"id", "domain", "topic", "prompt", "options", "score"} <= question.keys()


def test_all_correct_answers_produce_full_score_and_pretest_mapping() -> None:
    bank = load_question_bank()
    submission = _submission(
        "learner-full-score",
        [
            {
                "question_id": question["id"],
                "answer": question["correct_answer"],
            }
            for question in bank["questions"]
        ],
    )

    result = score_pretest(submission)

    assert result["learner_id"] == "learner-full-score"
    assert result["total_score"] == result["max_score"] == 120.0
    assert result["percentage"] == 100.0
    assert set(result["topic_scores"]) == {
        "机器人坐标系",
        "运动指令",
        "RobotStudio仿真",
        "ROS2/Gazebo仿真",
        "SRVO-068数据传输故障",
        "安全急停链路",
    }
    assert all(score == 100.0 for score in result["topic_scores"].values())
    assert len(result["pretest_results"]) == 1
    mapped = result["pretest_results"][0]
    assert mapped["test_name"] == bank["meta"]["name"]
    assert mapped["total_score"] == 120.0
    assert mapped["max_score"] == 120.0
    assert mapped["topic_scores"] == result["topic_scores"]
    assert len(result["details"]) == 12
    assert all(item["correct"] is True for item in result["details"])


def test_partial_submission_is_case_insensitive_and_unanswered_questions_score_zero() -> None:
    submission = _submission(
        "learner-partial",
        [{"question_id": "PT-K1-001", "answer": " b "}],
    )

    result = score_pretest(submission)

    assert result["total_score"] == 10.0
    assert result["max_score"] == 120.0
    assert result["percentage"] == 8.33
    assert result["topic_scores"]["机器人坐标系"] == 50.0
    assert sum(item["correct"] for item in result["details"]) == 1
    assert len(result["details"]) == 12


def test_unknown_question_is_rejected_by_scorer_and_api() -> None:
    submission = _submission(
        "learner-unknown",
        [{"question_id": "UNKNOWN-QUESTION", "answer": "A"}],
    )
    with pytest.raises(ValueError, match="UNKNOWN-QUESTION"):
        score_pretest(submission)

    app = FastAPI()
    app.include_router(pretests_router)
    with TestClient(app) as client:
        response = client.post(
            "/api/pretests/score",
            json=submission.model_dump(mode="json"),
        )
    assert response.status_code == 422
    assert "UNKNOWN-QUESTION" in response.json()["detail"]


@pytest.fixture
def pretest_client() -> TestClient:
    app = FastAPI()
    app.include_router(pretests_router)
    return TestClient(app)


def test_pretest_api_serves_safe_questions_and_scores_submission(
    pretest_client: TestClient,
) -> None:
    questions_response = pretest_client.get("/api/pretests/questions")
    assert questions_response.status_code == 200
    public_questions = questions_response.json()["questions"]
    assert len(public_questions) == 12
    assert all("correct_answer" not in item for item in public_questions)
    assert all("explanation" not in item for item in public_questions)

    score_response = pretest_client.post(
        "/api/pretests/score",
        json={
            "learner_id": "api-learner",
            "answers": [{"question_id": "PT-K3-003", "answer": "B"}],
        },
    )
    assert score_response.status_code == 200, score_response.text
    scored = score_response.json()
    assert scored["learner_id"] == "api-learner"
    assert scored["total_score"] == 10.0
    assert scored["max_score"] == 120.0
    assert scored["percentage"] == 8.33
    assert scored["topic_scores"]["安全急停链路"] == 50.0
    assert len(scored["pretest_results"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"learner_id": "", "answers": [{"question_id": "PT-K1-001", "answer": "B"}]},
        {"learner_id": "learner", "answers": []},
        {"learner_id": "learner", "answers": [{"question_id": "", "answer": "B"}]},
    ],
)
def test_pretest_api_rejects_invalid_submission(
    pretest_client: TestClient,
    payload: dict,
) -> None:
    response = pretest_client.post("/api/pretests/score", json=payload)
    assert response.status_code == 422

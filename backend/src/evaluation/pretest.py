"""前置测试题库读取、确定性评分及 PretestResult 映射。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..schemas import PretestResult, PretestSubmission

_DEFAULT_BANK_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "evaluation" / "pretest_questions.json"
)


def load_question_bank(path: str | Path | None = None) -> dict[str, Any]:
    bank_path = Path(path or _DEFAULT_BANK_PATH)
    with bank_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("pretest question bank must contain a non-empty questions list")
    return data


def public_question_bank(path: str | Path | None = None) -> dict[str, Any]:
    """返回给前端的题库不包含答案和解析。"""

    bank = load_question_bank(path)
    public_questions = []
    for question in bank["questions"]:
        public_questions.append(
            {
                key: value
                for key, value in question.items()
                if key not in {"correct_answer", "explanation"}
            }
        )
    return {"meta": bank.get("meta", {}), "questions": public_questions}


def score_pretest(
    submission: PretestSubmission,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """未答题按 0 分计，保证不同学习者使用同一固定分母。"""

    bank = load_question_bank(path)
    known_question_ids = {str(question["id"]) for question in bank["questions"]}
    submitted_question_ids = {answer.question_id for answer in submission.answers}
    unknown_question_ids = sorted(submitted_question_ids - known_question_ids)
    if unknown_question_ids:
        raise ValueError("unknown pretest question_id(s): " + ", ".join(unknown_question_ids))
    submitted = {
        answer.question_id: answer.answer.strip().casefold() for answer in submission.answers
    }
    topic_earned: dict[str, float] = defaultdict(float)
    topic_max: dict[str, float] = defaultdict(float)
    details: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = 0.0

    for question in bank["questions"]:
        question_id = str(question["id"])
        topic = str(question["topic"])
        points = float(question.get("score", 0))
        expected = str(question.get("correct_answer", "")).strip().casefold()
        actual = submitted.get(question_id, "")
        correct = bool(actual and actual == expected)
        earned = points if correct else 0.0
        total_score += earned
        max_score += points
        topic_earned[topic] += earned
        topic_max[topic] += points
        details.append(
            {
                "question_id": question_id,
                "domain": question.get("domain"),
                "topic": topic,
                "correct": correct,
                "earned_score": earned,
                "max_score": points,
                "correct_answer": question.get("correct_answer"),
                "explanation": question.get("explanation"),
            }
        )

    topic_scores = {
        topic: round(topic_earned[topic] / maximum * 100, 2) if maximum else 0.0
        for topic, maximum in topic_max.items()
    }
    percentage = round(total_score / max_score * 100, 2) if max_score else 0.0
    mapped_result = PretestResult(
        test_name=str(bank.get("meta", {}).get("name") or "工业机器人前置测试"),
        total_score=total_score,
        max_score=max_score,
        topic_scores=topic_scores,
    )
    return {
        "learner_id": submission.learner_id,
        "total_score": total_score,
        "max_score": max_score,
        "percentage": percentage,
        "topic_scores": topic_scores,
        "pretest_results": [mapped_result.model_dump(mode="json")],
        "details": details,
    }

"""Quiz submission API backed by the existing learner profile store."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.src.agents.k1_exam_pipeline import (
    calculate_topic_mastery,
    run_exam_pipeline,
)
from backend.src.agents.k1_post_feedback import post_feedback_pipeline
from backend.src.persistence.profile_store import ProfileStore, profile_store


router = APIRouter(prefix="/api/exams", tags=["exams"])


class ExamQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    question_type: Literal["choice", "fill"] = "choice"
    standard_answer: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(default="", max_length=8000)
    knowledge_id: str = Field(default="general", min_length=1, max_length=160)


class ExamAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    answer: str = Field(default="", max_length=2000)


class ExamSubmission(BaseModel):
    learner_id: str = Field(min_length=1, max_length=160)
    topic: str = Field(default="general", max_length=500)
    resource_id: str | None = Field(default=None, max_length=160)
    questions: list[ExamQuestion] = Field(min_length=1, max_length=100)
    answers: list[ExamAnswer] = Field(min_length=1, max_length=100)

    @field_validator("learner_id", "topic")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_unique_question_ids(self) -> "ExamSubmission":
        question_ids = [question.id for question in self.questions]
        answer_ids = [answer.question_id for answer in self.answers]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question ids must be unique")
        if len(set(answer_ids)) != len(answer_ids):
            raise ValueError("answer question ids must be unique")
        return self


def get_profile_store() -> ProfileStore:
    return profile_store


def _normalise(value: str) -> str:
    return "".join(value.casefold().split())


def _is_correct(question: ExamQuestion, submitted: str) -> bool:
    expected = _normalise(question.standard_answer)
    actual = _normalise(submitted)
    if not actual:
        return False
    if question.question_type == "choice":
        return actual == expected

    # Fill-in answers can contain harmless whitespace or punctuation differences.
    expected_chars = set(expected)
    actual_chars = set(actual)
    overlap = len(expected_chars & actual_chars)
    union = len(expected_chars | actual_chars) or 1
    return overlap / union >= 0.7


def _build_advice(details: list[dict[str, object]], topic: str) -> list[str]:
    weak_topics = sorted(
        {
            str(detail["knowledge_id"])
            for detail in details
            if not bool(detail["correct"])
        }
    )
    if not weak_topics:
        return [
            f"你已掌握当前“{topic}”相关题目，可以进入下一阶段练习。",
            "建议完成一组更高难度的练习，并用自己的话说明每道题的判断依据。",
        ]
    focus = ", ".join(weak_topics[:3])
    return [
        f"优先复习这些知识点：{focus}。",
        "重新阅读相关资源后，在不查看答案的情况下再次完成答错题目。",
    ]


async def _save_quiz_profile(
    store: ProfileStore,
    submission: ExamSubmission,
    details: list[dict[str, object]],
    score: float,
) -> str:
    previous_page = await store.list_profiles(
        learner_id=submission.learner_id, limit=1, offset=0
    )
    previous_items = list(previous_page.get("items") or [])
    profile = dict(previous_items[0].get("profile") or {}) if previous_items else {}
    knowledge_map = dict(profile.get("knowledge_map") or {})
    now = datetime.now(timezone.utc).isoformat()

    for detail in details:
        knowledge_id = str(detail["knowledge_id"])
        current = dict(knowledge_map.get(knowledge_id) or {})
        mastery = int(current.get("mastery", 50))
        mastery = max(0, min(100, mastery + (8 if detail["correct"] else -12)))
        knowledge_map[knowledge_id] = {
            **current,
            "mastery": mastery,
            "last_result": "correct" if detail["correct"] else "incorrect",
            "updated_at": now,
        }

    weak_topics = [
        knowledge_id
        for knowledge_id, item in knowledge_map.items()
        if int(item.get("mastery", 50)) < 60
    ]
    history = list(profile.get("quiz_history") or [])
    history.append(
        {
            "topic": submission.topic,
            "resource_id": submission.resource_id,
            "score": score,
            "total": len(details),
            "completed_at": now,
        }
    )
    profile.update(
        {
            "knowledge_map": knowledge_map,
            "weak_topics": weak_topics,
            "quiz_history": history[-20:],
            "last_quiz": history[-1],
        }
    )
    saved = await store.save_profile(
        {
            "learner_id": submission.learner_id,
            "profile": profile,
            "label": "quiz_submission",
        }
    )
    return str(saved["profile_id"])


def _build_adaptive_feedback(
    submission: ExamSubmission,
    details: list[dict[str, object]],
) -> dict[str, object]:
    """Run the K1 post-exam analysis against the answers just scored."""
    details_by_id = {str(detail["question_id"]): detail for detail in details}

    def score_answer(answer_data: dict[str, object]) -> dict[str, object]:
        detail = details_by_id[str(answer_data["question_id"])]
        return {
            **answer_data,
            # K1 topic mastery expects a 0-10 score for each answered question.
            "score": 10.0 if bool(detail["correct"]) else 0.0,
            "status": "answered",
        }

    pipeline = run_exam_pipeline(
        [
            {
                "id": question.id,
                "topic": question.knowledge_id,
                "weight": 1.0,
            }
            for question in submission.questions
        ],
        {"adaptive_difficulty": 5.0},
        answer_handler=score_answer,
    )
    topic_mastery = calculate_topic_mastery(pipeline["topic_scores"])
    questions_by_id = {question.id: question for question in submission.questions}
    details_by_id = {str(detail["question_id"]): detail for detail in details}
    feedback_items: list[dict[str, Any]] = []

    for answer_data in pipeline["results"]:
        question_id = str(answer_data["question_id"])
        question = questions_by_id[question_id]
        detail = details_by_id[question_id]
        knowledge_id = question.knowledge_id
        grading = {
            "question_id": question_id,
            "question_type": question.question_type,
            "knowledge_point": knowledge_id,
            "is_correct": bool(detail["correct"]),
            "score": 1.0 if bool(detail["correct"]) else 0.0,
            "user_answer": detail["submitted_answer"],
            "standard_answer": question.standard_answer,
        }
        feedback_items.append(post_feedback_pipeline(
            grading,
            topic_mastery=float(topic_mastery.get(knowledge_id, 0.0)) / 100.0,
        ))

    def topic_items(correct: bool) -> list[dict[str, object]]:
        topic_ids = sorted({
            str(detail["knowledge_id"])
            for detail in details
            if bool(detail["correct"]) is correct
        })
        return [
            {"topic": topic_id, "mastery": float(topic_mastery.get(topic_id, 0.0))}
            for topic_id in topic_ids
        ]

    recommendations = [
        str(item["feedback"].get("tip", ""))
        for item in feedback_items
        if isinstance(item.get("feedback"), dict) and item["feedback"].get("tip")
    ]
    return {
        "weak_topics": topic_items(False),
        "strong_topics": topic_items(True),
        "recommendations": list(dict.fromkeys(recommendations)),
        "items": feedback_items,
        "retry_hints": [item["retry_hint"] for item in feedback_items],
    }


@router.post("/submit")
async def submit_exam(
    submission: ExamSubmission,
    store: ProfileStore = Depends(get_profile_store),
) -> dict[str, object]:
    answers = {item.question_id: item.answer for item in submission.answers}
    known_question_ids = {question.id for question in submission.questions}
    unknown_answers = sorted(set(answers) - known_question_ids)
    if unknown_answers:
        raise HTTPException(
            status_code=422,
            detail=f"answers reference unknown question ids: {', '.join(unknown_answers)}",
        )

    details: list[dict[str, object]] = []
    for question in submission.questions:
        submitted = answers.get(question.id, "")
        correct = _is_correct(question, submitted)
        details.append(
            {
                "question_id": question.id,
                "knowledge_id": question.knowledge_id,
                "submitted_answer": submitted,
                "correct": correct,
                "standard_answer": question.standard_answer,
                "explanation": question.explanation,
            }
        )

    correct_count = sum(1 for detail in details if detail["correct"])
    total = len(details)
    score = round(correct_count / total * 100, 2)
    feedback = _build_adaptive_feedback(submission, details)
    profile_snapshot_id = await _save_quiz_profile(store, submission, details, score)
    snapshot = await store.get_profile(profile_snapshot_id)
    return {
        "correct_count": correct_count,
        "total": total,
        "score": score,
        "details": details,
        "learning_advice": _build_advice(details, submission.topic),
        "profile_snapshot_id": profile_snapshot_id,
        "adaptive_profile": dict(snapshot.get("profile") or {}) if snapshot else {},
        "feedback": feedback,
    }

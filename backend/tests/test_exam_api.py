import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.api.exams import get_profile_store, router
from backend.src.persistence.profile_store import ProfileStore


def make_client(tmp_path):
    store = ProfileStore(db_path=tmp_path / "profiles.db", cleanup_enabled=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_profile_store] = lambda: store
    return TestClient(app), store


def test_submit_exam_scores_answers_and_saves_snapshot(tmp_path):
    client, store = make_client(tmp_path)
    response = client.post(
        "/api/exams/submit",
        json={
            "learner_id": "learner-1",
            "topic": "robotics",
            "questions": [
                {
                    "id": "q1",
                    "standard_answer": "A",
                    "explanation": "A is correct.",
                    "knowledge_id": "coordinates",
                },
                {
                    "id": "q2",
                    "question_type": "fill",
                    "standard_answer": "emergency stop",
                    "explanation": "Use the emergency stop.",
                    "knowledge_id": "safety",
                },
            ],
            "answers": [
                {"question_id": "q1", "answer": "a"},
                {"question_id": "q2", "answer": "wrong"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["correct_count"] == 1
    assert body["score"] == 50.0
    assert body["details"][1]["standard_answer"] == "emergency stop"
    assert body["details"][1]["correct"] is False
    assert body["learning_advice"]

    snapshot = asyncio.run(store.get_profile(body["profile_snapshot_id"]))
    assert snapshot is not None
    assert snapshot["profile"]["knowledge_map"]["coordinates"]["mastery"] == 58
    assert "safety" in snapshot["profile"]["weak_topics"]


def test_submit_exam_rejects_unknown_answer_question(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.post(
        "/api/exams/submit",
        json={
            "learner_id": "learner-1",
            "questions": [{"id": "q1", "standard_answer": "A"}],
            "answers": [{"question_id": "not-a-question", "answer": "A"}],
        },
    )

    assert response.status_code == 422

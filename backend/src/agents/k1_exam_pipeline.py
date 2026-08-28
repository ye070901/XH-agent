"""
K1 Exam Pipeline Module

Main examination pipeline that orchestrates question delivery,
answer collection, scoring, and progression decisions.
"""

from typing import Any


def run_exam_pipeline(
    questions: list[dict[str, Any]],
    pre_analysis: dict[str, Any],
    answer_handler: Any = None,
) -> dict[str, Any]:
    """
    Execute the full exam pipeline with adaptive question delivery.

    Args:
        questions: List of question dictionaries to deliver.
        pre_analysis: Pre-exam analysis from k1_pre_heuristic_ask.
        answer_handler: Optional callable for handling each answer.

    Returns:
        Pipeline results including scores, timing, and performance metrics.
    """
    results: list[dict[str, Any]] = []
    topic_scores: dict[str, list[float]] = {}

    adaptive_weight = pre_analysis.get("adaptive_difficulty", 5.0) / 10.0

    for idx, question in enumerate(questions):
        q_id = question.get("id", f"q_{idx}")
        q_topic = question.get("topic", "general")
        base_weight = question.get("weight", 1.0)

        adjusted_weight = base_weight * (0.5 + adaptive_weight * 0.5)

        answer_data = {
            "question_id": q_id,
            "topic": q_topic,
            "weight": adjusted_weight,
            "status": "pending",
        }

        if answer_handler:
            answer_data = answer_handler(answer_data)

        results.append(answer_data)

        if q_topic not in topic_scores:
            topic_scores[q_topic] = []
        topic_scores[q_topic].append(answer_data.get("score", 0.0))

    total_weighted_score = sum(r.get("score", 0.0) * r.get("weight", 1.0) for r in results)
    total_weight = sum(r.get("weight", 1.0) for r in results)
    normalized_score = (total_weighted_score / total_weight) if total_weight > 0 else 0.0

    return {
        "results": results,
        "topic_scores": topic_scores,
        "normalized_score": normalized_score,
        "total_questions": len(questions),
        "answered_questions": sum(1 for r in results if r.get("status") == "answered"),
    }


def calculate_topic_mastery(topic_scores: dict[str, list[float]]) -> dict[str, float]:
    """
    Calculate mastery level per topic based on historical scores.

    Args:
        topic_scores: Dictionary mapping topics to list of scores.

    Returns:
        Dictionary mapping topics to mastery percentages (0-100).
    """
    mastery: dict[str, float] = {}

    for topic, scores in topic_scores.items():
        if not scores:
            mastery[topic] = 0.0
            continue

        avg_score = sum(scores) / len(scores)
        consistency = 1.0 - (max(scores) - min(scores)) / 10.0
        mastery[topic] = max(0.0, min(100.0, avg_score * consistency * 10.0))

    return mastery

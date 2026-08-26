"""
K1 Pre-Heuristic Ask Module

This module handles the pre-examination heuristic questioning phase,
where candidate profiles and exam contexts are analyzed to generate
adaptive preliminary questions.
"""

from typing import Any


def generate_heuristic_questions(context: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Generate heuristic-based preliminary questions based on context.

    Args:
        context: Dictionary containing candidate info, exam type, and history.

    Returns:
        List of preliminary question dictionaries with question text and metadata.
    """
    exam_type = context.get("exam_type", "general")
    difficulty = context.get("difficulty", "medium")

    questions = [
        {
            "id": "pre_q1",
            "text": f"What is your primary goal for this {exam_type} exam?",
            "type": "heuristic",
            "weight": 1.0,
        },
        {
            "id": "pre_q2",
            "text": "Describe your comfort level with the exam material (1-10):",
            "type": "self_assessment",
            "weight": 0.8,
        },
        {
            "id": "pre_q3",
            "text": "Which topics do you feel least confident about?",
            "type": "topic_prioritization",
            "weight": 0.9,
        },
    ]

    if difficulty == "hard":
        questions.append(
            {
                "id": "pre_q4",
                "text": "Have you attempted this exam type before?",
                "type": "experience_check",
                "weight": 0.7,
            }
        )

    return questions


def process_pre_ask_response(responses: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Process and analyze responses from the pre-heuristic ask phase.

    Args:
        responses: List of response dictionaries from preliminary questions.

    Returns:
        Processed analysis including topic weights and difficulty adjustments.
    """
    topic_confidence: dict[str, float] = {}
    overall_confidence = 0.0

    for response in responses:
        q_type = response.get("type")
        answer = response.get("answer", "")

        if q_type == "self_assessment":
            try:
                overall_confidence = float(answer)
            except (ValueError, TypeError):
                overall_confidence = 5.0

        elif q_type == "topic_prioritization":
            topics = [t.strip() for t in str(answer).split(",")]
            for topic in topics:
                topic_confidence[topic] = 0.3

        elif q_type == "experience_check":
            if answer.lower() in ("yes", "y", "true"):
                for topic in topic_confidence:
                    topic_confidence[topic] = max(topic_confidence[topic], 0.5)

    return {
        "topic_confidence": topic_confidence,
        "overall_confidence": overall_confidence,
        "adaptive_difficulty": max(1.0, min(10.0, overall_confidence)),
    }

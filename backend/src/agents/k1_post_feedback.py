"""
K1 Post-Feedback Module

Handles post-examination analysis, feedback generation,
and recommendation derivation based on exam performance.
"""

from typing import Any


def generate_post_feedback(
    exam_results: dict[str, Any],
    topic_mastery: dict[str, float],
) -> dict[str, Any]:
    """
    Generate comprehensive feedback based on exam results.

    Args:
        exam_results: Results dictionary from k1_exam_pipeline.
        topic_mastery: Topic mastery scores from calculate_topic_mastery.

    Returns:
        Complete feedback report with scores, strengths, weaknesses, and recommendations.
    """
    normalized_score = exam_results.get("normalized_score", 0.0)
    total_questions = exam_results.get("total_questions", 0)
    answered = exam_results.get("answered_questions", 0)

    weak_topics = [
        (topic, score) for topic, score in topic_mastery.items() if score < 60.0
    ]
    strong_topics = [
        (topic, score) for topic, score in topic_mastery.items() if score >= 80.0
    ]

    weak_topics.sort(key=lambda x: x[1])
    strong_topics.sort(key=lambda x: x[1], reverse=True)

    recommendations = _derive_recommendations(weak_topics, normalized_score)

    return {
        "score": normalized_score,
        "total_questions": total_questions,
        "answered": answered,
        "completion_rate": answered / total_questions if total_questions > 0 else 0.0,
        "strong_topics": [{"topic": t, "mastery": s} for t, s in strong_topics[:5]],
        "weak_topics": [{"topic": t, "mastery": s} for t, s in weak_topics[:5]],
        "recommendations": recommendations,
        "overall_assessment": _assess_performance(normalized_score),
    }


def _derive_recommendations(
    weak_topics: list[tuple[str, float]],
    overall_score: float,
) -> list[str]:
    """
    Derive study and improvement recommendations from weak areas.

    Args:
        weak_topics: Sorted list of (topic, score) tuples (lowest first).
        overall_score: Normalized overall exam score.

    Returns:
        List of recommendation strings.
    """
    recommendations: list[str] = []

    if overall_score < 50.0:
        recommendations.append(
            "Consider a comprehensive review of fundamental concepts before retaking."
        )
    elif overall_score < 70.0:
        recommendations.append(
            "Focus on targeted practice in weaker areas identified below."
        )

    if weak_topics:
        top_weak = weak_topics[:3]
        recommendations.append(
            f"Priority topics to review: {', '.join(t for t, _ in top_weak)}"
        )

    recommendations.append(
        "Schedule regular practice sessions to improve retention and familiarity."
    )

    return recommendations


def _assess_performance(score: float) -> str:
    """
    Provide an overall textual assessment based on the normalized score.

    Args:
        score: Normalized score value (typically 0-100).

    Returns:
        Assessment string describing performance level.
    """
    if score >= 90.0:
        return "Excellent - Demonstrates strong mastery of the material."
    elif score >= 80.0:
        return "Very Good - Solid understanding with minor areas for improvement."
    elif score >= 70.0:
        return "Good - Competent performance, consider reviewing weak topics."
    elif score >= 60.0:
        return "Satisfactory - Basic proficiency achieved, further study recommended."
    elif score >= 50.0:
        return "Needs Improvement - Significant gaps identified, dedicated review required."
    else:
        return "Unsatisfactory - Comprehensive study recommended before continuation."

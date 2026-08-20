"""Phase 3 三项硬指标的确定性契约测试。

这些测试刻意只使用外部标注和静态数据，不调用 LLM，也不接受生成资源对自身
覆盖情况的声明。这样一旦指标公式、边界条件或真值来源被改坏，测试会立即失败。
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.src.evaluation.metrics import (
    EvaluationMetrics,
    aggregate_case_results,
    calibrate_verdicts,
)


def _claims(*verdicts: str) -> dict[str, list[dict[str, str]]]:
    return {
        "items": [
            {"claim_id": f"claim-{index}", "verdict": verdict}
            for index, verdict in enumerate(verdicts)
        ]
    }


def _diagnosis(
    *,
    difficulty: str = "beginner",
    style: str = "practice_first",
    gaps: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "recommended_difficulty": difficulty,
        "learning_style": style,
        "skill_gaps": gaps or [],
    }


def _resource(
    *,
    difficulty: str = "beginner",
    style: str | None = "practice_first",
    title: str = "测试资源",
    content: str = "操作步骤：先检查安全状态，再进行实操练习。",
    target_skill_gaps: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "resource_id": "resource-1",
        "difficulty_level": difficulty,
        "title": title,
        "content": content,
        "target_skill_gaps": target_skill_gaps or [],
    }
    if style is not None:
        result["learning_style"] = style
    return result


class TestHallucinationMetric:
    def test_three_state_rate_and_counts(self) -> None:
        metric = EvaluationMetrics(hallucination_threshold=0.80)

        result = metric.compute_hallucination(
            _claims("accurate", "accurate", "hallucination", "unverifiable")
        )

        assert result == {
            "rate": 0.5,
            "pass": True,
            "hallucination_count": 1,
            "unverifiable_count": 1,
            "accurate_count": 2,
            "skip_count": 0,
            "invalid_verdict_count": 0,
            "total": 4,
            "reason": None,
        }

    def test_skip_is_counted_but_excluded_from_denominator(self) -> None:
        metric = EvaluationMetrics(hallucination_threshold=0.05)

        result = metric.compute_hallucination(_claims("accurate", "accurate", "skip", "skip"))

        assert result["rate"] == 0.0
        assert result["total"] == 2
        assert result["skip_count"] == 2
        assert result["pass"] is True

    def test_empty_or_skip_only_input_never_passes(self) -> None:
        metric = EvaluationMetrics(hallucination_threshold=0.05)

        for fact_check in (None, {}, {"items": []}, _claims("skip", "skip")):
            result = metric.compute_hallucination(fact_check)
            assert result["rate"] == 0.0
            assert result["total"] == 0
            assert result["pass"] is False
            assert result["reason"] == "no_fact_claims"

    def test_five_percent_boundary_is_strictly_less_than(self) -> None:
        metric = EvaluationMetrics(hallucination_threshold=0.05)
        exactly_five_percent = _claims(*(["accurate"] * 19), "hallucination")
        below_five_percent = _claims(*(["accurate"] * 20), "hallucination")

        boundary = metric.compute_hallucination(exactly_five_percent)
        below = metric.compute_hallucination(below_five_percent)

        assert boundary["rate"] == 0.05
        assert boundary["pass"] is False
        assert below["rate"] == pytest.approx(0.0476, abs=0.0001)
        assert below["pass"] is True

    def test_unknown_and_legacy_none_are_conservatively_unverifiable(self) -> None:
        metric = EvaluationMetrics(hallucination_threshold=1.0)

        result = metric.compute_hallucination(
            {
                "items": [
                    {"claim": "unknown label", "verdict": "maybe"},
                    {"claim": "legacy undecidable", "is_accurate": None},
                    {"claim": "legacy correct", "is_accurate": True},
                    {"claim": "legacy incorrect", "is_accurate": False},
                ]
            }
        )

        assert result["unverifiable_count"] == 2
        assert result["invalid_verdict_count"] == 1
        assert result["accurate_count"] == 1
        assert result["hallucination_count"] == 1
        assert result["rate"] == 0.75


class TestAdaptationMetric:
    def test_external_profile_truth_overrides_conflicting_diagnosis(self) -> None:
        metric = EvaluationMetrics(adaptation_target=0.85)
        diagnosis = _diagnosis(difficulty="advanced", style="theory_first")
        expected_profile = {
            "expected_difficulty": "beginner",
            "expected_learning_style": "practice_first",
        }

        result = metric.compute_adaptation(
            diagnosis,
            [_resource(difficulty="beginner", style="practice_first")],
            expected_profile=expected_profile,
        )

        assert result["expected_difficulty"] == "beginner"
        assert result["expected_learning_style"] == "practice_first"
        assert result["difficulty_match"] == 1.0
        assert result["style_match"] == 1.0
        assert result["rate"] == 1.0
        assert result["pass"] is True

    @pytest.mark.parametrize(
        ("actual_difficulty", "expected_score", "expected_rate"),
        [
            ("beginner", 1.0, 1.0),
            ("intermediate", 0.5, 0.75),
            ("advanced", 0.0, 0.5),
        ],
    )
    def test_three_level_difficulty_distance_scoring(
        self,
        actual_difficulty: str,
        expected_score: float,
        expected_rate: float,
    ) -> None:
        metric = EvaluationMetrics(adaptation_target=0.0)
        expected_profile = {
            "expected_difficulty": "beginner",
            "expected_learning_style": "practice_first",
        }

        result = metric.compute_adaptation(
            {},
            [_resource(difficulty=actual_difficulty, style="practice_first")],
            expected_profile=expected_profile,
        )

        assert result["difficulty_match"] == expected_score
        assert result["style_match"] == 1.0
        assert result["rate"] == expected_rate

    @pytest.mark.parametrize(
        "style",
        ["theory_first", "practice_first", "visual", "project_based"],
    )
    def test_all_four_valid_explicit_styles_can_fully_match(self, style: str) -> None:
        metric = EvaluationMetrics(adaptation_target=0.85)
        expected_profile = {
            "expected_difficulty": "intermediate",
            "expected_learning_style": style,
        }

        result = metric.compute_adaptation(
            {},
            [_resource(difficulty="intermediate", style=style)],
            expected_profile=expected_profile,
        )

        assert result["style_match"] == 1.0
        assert result["rate"] == 1.0
        assert result["pass"] is True

    @pytest.mark.parametrize(
        ("style", "content"),
        [
            ("theory_first", "定义与概念：坐标系的理论原理和运动学机制。"),
            ("practice_first", "操作步骤：1. 示教；2. 调试；3. 完成实操练习。"),
            ("visual", "流程图如下：\n```mermaid\ngraph LR; A-->B\n```\n如图所示。"),
            ("project_based", "项目目标与项目任务；步骤 1：实现；验收标准如下。"),
        ],
    )
    def test_all_four_styles_have_deterministic_content_rules(
        self, style: str, content: str
    ) -> None:
        metric = EvaluationMetrics(adaptation_target=0.85)

        result = metric.compute_adaptation(
            {},
            [_resource(difficulty="beginner", style=None, content=content)],
            expected_profile={
                "expected_difficulty": "beginner",
                "expected_learning_style": style,
            },
        )

        assert result["details"][0]["style_source"] == "content_rules"
        assert result["style_match"] == 1.0
        assert result["pass"] is True

    def test_invalid_expected_style_cannot_pass(self) -> None:
        metric = EvaluationMetrics(adaptation_target=0.85)

        result = metric.compute_adaptation(
            {},
            [_resource(difficulty="beginner", style="audio_only")],
            expected_profile={
                "expected_difficulty": "beginner",
                "expected_learning_style": "audio_only",
            },
        )

        # 未知风格不能因为资源复制了同一字符串就被视为有效风格。
        assert result["style_match"] == 0.0
        assert result["rate"] == 0.0
        assert result["pass"] is False
        assert "valid_expected_learning_style" in result["missing"]

    @pytest.mark.parametrize(
        ("resources", "expected_profile", "missing_field"),
        [
            (
                [],
                {
                    "expected_difficulty": "beginner",
                    "expected_learning_style": "visual",
                },
                "resources",
            ),
            ([_resource()], {"expected_learning_style": "visual"}, "expected_difficulty"),
            ([_resource()], {"expected_difficulty": "beginner"}, "expected_learning_style"),
        ],
    )
    def test_missing_adaptation_evidence_fails_closed(
        self,
        resources: list[dict[str, Any]],
        expected_profile: dict[str, str],
        missing_field: str,
    ) -> None:
        metric = EvaluationMetrics(adaptation_target=0.85)

        result = metric.compute_adaptation({}, resources, expected_profile=expected_profile)

        assert result["rate"] == 0.0
        assert result["pass"] is False
        assert missing_field in result["missing"]


class TestCoverageMetric:
    def test_only_critical_and_high_gaps_enter_denominator(self) -> None:
        metric = EvaluationMetrics(coverage_target=1.0)
        diagnosis = _diagnosis(
            gaps=[
                {"topic": "安全急停", "priority": "critical"},
                {"topic": "坐标系", "priority": "high"},
                {"topic": "锦上添花", "priority": "medium"},
            ]
        )

        result = metric.compute_coverage(
            diagnosis,
            [_resource(content="本节讲解安全急停与坐标系。")],
            expected_gaps=diagnosis["skill_gaps"],
        )

        assert result["total_critical_high"] == 2
        assert result["covered"] == 2
        assert result["covered_topics"] == ["安全急停", "坐标系"]
        assert result["rate"] == 1.0
        assert result["pass"] is True

    def test_core_map_alias_counts_as_actual_coverage(self) -> None:
        metric = EvaluationMetrics(coverage_target=1.0)
        diagnosis = _diagnosis(gaps=[{"topic": "紧急停止", "priority": "critical"}])
        core_map = {
            "knowledge_points": [
                {
                    "topic": "紧急停止",
                    "priority": "critical",
                    "aliases": ["E-STOP", "急停按钮"],
                }
            ]
        }

        result = metric.compute_coverage(
            diagnosis,
            [_resource(content="触发 E-STOP 后，应先确认现场安全。")],
            core_knowledge_map=core_map,
            expected_gaps=diagnosis["skill_gaps"],
        )

        assert result["covered_topics"] == ["紧急停止"]
        assert result["rate"] == 1.0
        assert result["pass"] is True

    def test_target_skill_gaps_self_declaration_is_not_coverage_evidence(self) -> None:
        metric = EvaluationMetrics(coverage_target=0.90)
        diagnosis = _diagnosis(gaps=[{"topic": "SRVO-068", "priority": "critical"}])
        resource = _resource(
            title="无关内容",
            content="这里只讨论办公室网络设置。",
            target_skill_gaps=["SRVO-068"],
        )

        result = metric.compute_coverage(
            diagnosis,
            [resource],
            expected_gaps=diagnosis["skill_gaps"],
        )

        assert result["covered"] == 0
        assert result["uncovered_topics"] == ["SRVO-068"]
        assert result["rate"] == 0.0
        assert result["pass"] is False

    def test_short_ascii_alias_requires_token_boundary(self) -> None:
        metric = EvaluationMetrics(coverage_target=1.0)
        gaps = [{"topic": "机器人输出信号", "priority": "high"}]
        core_map = {
            "knowledge_points": [
                {
                    "topic": "机器人输出信号",
                    "priority": "high",
                    "aliases": ["RO"],
                }
            ]
        }

        false_match = metric.compute_coverage(
            {},
            [_resource(content="RobotStudio 工作站")],
            core_knowledge_map=core_map,
            expected_gaps=gaps,
        )
        true_match = metric.compute_coverage(
            {},
            [_resource(content="将 RO[1] 设置为 ON")],
            core_knowledge_map=core_map,
            expected_gaps=gaps,
        )

        assert false_match["covered"] == 0
        assert true_match["covered"] == 1

    def test_coverage_threshold_is_inclusive_at_ninety_percent(self) -> None:
        metric = EvaluationMetrics(coverage_target=0.90)
        gaps = [{"topic": f"知识点{i}", "priority": "high"} for i in range(10)]
        content = "、".join(f"知识点{i}" for i in range(9))

        result = metric.compute_coverage(
            _diagnosis(gaps=gaps),
            [_resource(content=content)],
            expected_gaps=gaps,
        )

        assert result["covered"] == 9
        assert result["total_critical_high"] == 10
        assert result["rate"] == 0.9
        assert result["pass"] is True

    def test_no_critical_or_high_gaps_is_not_an_automatic_pass(self) -> None:
        metric = EvaluationMetrics(coverage_target=0.90)

        result = metric.compute_coverage(
            _diagnosis(gaps=[{"topic": "可选内容", "priority": "low"}]),
            [_resource(content="可选内容")],
            expected_gaps=[],
        )

        assert result["rate"] == 0.0
        assert result["pass"] is False
        assert result["not_applicable"] is True
        assert result["reason"] == "no_critical_high_skill_gaps"

    def test_external_expected_gaps_override_diagnosis_gaps(self) -> None:
        metric = EvaluationMetrics(coverage_target=1.0)
        model_diagnosis = _diagnosis(gaps=[{"topic": "模型自报盲区", "priority": "critical"}])
        externally_labeled_gaps = [{"topic": "人工金标准盲区", "priority": "critical"}]

        result = metric.compute_coverage(
            model_diagnosis,
            [_resource(content="人工金标准盲区的完整讲解。")],
            expected_gaps=externally_labeled_gaps,
        )

        assert result["covered_topics"] == ["人工金标准盲区"]
        assert result["ground_truth_provided"] is True
        assert result["pass"] is True

    def test_diagnosis_gaps_without_external_truth_can_be_scored_but_not_pass(self) -> None:
        metric = EvaluationMetrics(coverage_target=1.0)
        diagnosis = _diagnosis(gaps=[{"topic": "模型自报盲区", "priority": "critical"}])

        result = metric.compute_coverage(
            diagnosis,
            [_resource(content="模型自报盲区的完整讲解。")],
        )

        assert result["rate"] == 1.0
        assert result["ground_truth_provided"] is False
        assert result["reason"] == "external_expected_gaps_required"
        assert result["pass"] is False


class TestVerdictCalibration:
    @staticmethod
    def _calibration_data(correct: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        gold = [
            {"claim_id": f"gold-{index}", "expected_verdict": "accurate"} for index in range(50)
        ]
        predictions = [
            {
                "claim_id": f"gold-{index}",
                "verdict": "accurate" if index < correct else "hallucination",
            }
            for index in range(50)
        ]
        return predictions, gold

    def test_empty_gold_set_fails_closed(self) -> None:
        result = calibrate_verdicts([], [])

        assert result["accuracy"] == 0.0
        assert result["total_gold"] == 0
        assert result["pass"] is False

    def test_accuracy_threshold_is_inclusive_with_fifty_gold_assertions(self) -> None:
        predictions, gold = self._calibration_data(correct=45)

        result = calibrate_verdicts(predictions, gold, minimum_accuracy=0.90)

        assert result["total_gold"] == 50
        assert result["correct"] == 45
        assert result["accuracy"] == 0.9
        assert result["pass"] is True

    def test_accuracy_below_threshold_fails(self) -> None:
        predictions, gold = self._calibration_data(correct=44)

        result = calibrate_verdicts(predictions, gold, minimum_accuracy=0.90)

        assert result["accuracy"] == 0.88
        assert result["pass"] is False

    def test_missing_and_unexpected_predictions_are_reported(self) -> None:
        gold = [
            {"claim_id": "required", "expected_verdict": "accurate"},
            {"claim_id": "missing", "expected_verdict": "hallucination"},
        ]
        predicted = [
            {"claim_id": "required", "verdict": "accurate"},
            {"claim_id": "extra", "verdict": "accurate"},
        ]

        result = calibrate_verdicts(
            predicted,
            gold,
            minimum_accuracy=0.50,
            minimum_gold_items=2,
        )

        assert result["accuracy"] == 0.5
        assert result["pass"] is True
        assert result["missing_prediction_keys"] == ["missing"]
        assert result["unexpected_prediction_keys"] == ["extra"]

    def test_fewer_than_fifty_gold_assertions_cannot_pass(self) -> None:
        gold = [
            {"claim_id": f"short-{index}", "expected_verdict": "accurate"} for index in range(49)
        ]
        predicted = [{"claim_id": f"short-{index}", "verdict": "accurate"} for index in range(49)]

        result = calibrate_verdicts(predicted, gold)

        assert result["accuracy"] == 1.0
        assert result["dataset_size_pass"] is False
        assert result["pass"] is False


class TestAggregateMetrics:
    def test_empty_results_fail_all_metrics(self) -> None:
        result = aggregate_case_results([])

        assert result["case_count"] == 0
        assert result["hallucination"]["pass"] is False
        assert result["adaptation"]["pass"] is False
        assert result["coverage"]["pass"] is False
        assert result["all_pass"] is False

    def test_aggregate_uses_weighted_denominators_and_threshold_boundaries(self) -> None:
        cases = [
            {
                "all_pass": False,
                "profile_id": "profile-a",
                "hallucination": {
                    "hallucination_count": 1,
                    "unverifiable_count": 0,
                    "total": 10,
                },
                "adaptation": {"rate": 0.80, "ground_truth_provided": True},
                "coverage": {
                    "covered": 8,
                    "total_critical_high": 10,
                    "ground_truth_provided": True,
                },
            },
            {
                "all_pass": True,
                "profile_id": "profile-b",
                "hallucination": {
                    "hallucination_count": 0,
                    "unverifiable_count": 0,
                    "total": 90,
                },
                "adaptation": {"rate": 0.90, "ground_truth_provided": True},
                "coverage": {
                    "covered": 1,
                    "total_critical_high": 0,
                    "ground_truth_provided": True,
                },
            },
            {
                "profile_id": "profile-a",
                "is_negative": True,
                "negative_pass": True,
            },
        ]

        result = aggregate_case_results(
            cases,
            hallucination_threshold=0.05,
            adaptation_target=0.85,
            coverage_target=0.80,
            minimum_cases=3,
            minimum_profiles=2,
            minimum_negative_cases=1,
            maximum_negative_cases=1,
        )

        # 幻觉率按断言分母加权：1/100，而不是两个用例比率的算术平均。
        assert result["hallucination"]["rate"] == 0.01
        assert result["hallucination"]["pass"] is True
        # 适配率取用例均值，等于阈值时通过。
        assert result["adaptation"]["rate"] == 0.85
        assert result["adaptation"]["pass"] is True
        # 覆盖率按知识点分母加权；total=0 的畸形输入不能凭空增加分子。
        assert result["coverage"]["rate"] == 0.8
        assert result["coverage"]["pass"] is True
        assert result["case_count"] == 3
        assert result["case_passed"] == 1
        assert result["negative_case_count"] == 1
        assert result["negative_cases_pass"] is True
        assert result["dataset_requirements"]["pass"] is True
        assert result["all_pass"] is True

    def test_aggregate_hallucination_five_percent_boundary_fails(self) -> None:
        result = aggregate_case_results(
            [
                {
                    "all_pass": False,
                    "hallucination": {
                        "hallucination_count": 1,
                        "unverifiable_count": 0,
                        "total": 20,
                    },
                    "adaptation": {"rate": 1.0},
                    "coverage": {"covered": 1, "total_critical_high": 1},
                }
            ],
            hallucination_threshold=0.05,
        )

        assert result["hallucination"]["rate"] == 0.05
        assert result["hallucination"]["pass"] is False
        assert result["all_pass"] is False


class TestMetricConfiguration:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"hallucination_threshold": -0.01},
            {"hallucination_threshold": 1.01},
            {"adaptation_target": -0.01},
            {"coverage_target": 1.01},
        ],
    )
    def test_thresholds_must_be_probabilities(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="must be between 0 and 1"):
            EvaluationMetrics(**kwargs)

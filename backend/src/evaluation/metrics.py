"""Phase 3 三项硬指标评估。

本模块只做确定性计算，不调用 LLM。三个指标均以外部真值为基准：

* 幻觉率：Agent3 的逐断言三态结果；
* 适配率：画像预先标注的应得难度和学习风格；
* 覆盖率：画像中的 critical/high 盲区及核心知识点别名。

这样可以避免“模型给自己打分”，并让同一份输入在任意机器上得到相同结果。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from loguru import logger

from ..config import settings

_VALID_VERDICTS = {"accurate", "hallucination", "unverifiable", "partially_supported", "skip"}
_VALID_STYLES = {"theory_first", "practice_first", "visual", "project_based"}
_TARGET_PRIORITIES = {"critical", "high", "core"}
_DIFFICULTY_LEVELS = {
    "beginner": 0,
    "basic": 0,
    "introductory": 0,
    "初级": 0,
    "入门": 0,
    "intermediate": 1,
    "medium": 1,
    "中级": 1,
    "advanced": 2,
    "expert": 2,
    "进阶": 2,
    "高级": 2,
}


def _to_mapping(value: Any) -> dict[str, Any]:
    """把 Pydantic 模型或 mapping 转成普通字典。"""

    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        return dict(legacy_dict())
    return {}


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _normalise_text(value: Any) -> str:
    text = _to_text(value).casefold()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def _normalise_difficulty(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(getattr(value, "value", value)).strip().casefold()
    return _DIFFICULTY_LEVELS.get(raw)


def _normalise_style(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value)).strip().casefold()


def _alias_is_covered(alias: Any, raw_text: str, normalised_text: str) -> bool:
    """匹配知识点别名；英文短词使用边界，避免 RO 命中 RobotStudio。"""

    text = str(alias or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+/-]*", text):
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(text)}(?![A-Za-z0-9])",
                raw_text,
                flags=re.IGNORECASE,
            )
        )
    key = _normalise_text(text)
    return bool(key and key in normalised_text)


def _iter_fact_items(value: Any) -> Iterable[dict[str, Any]]:
    """兼容单份 fact_check、audit report 列表和 Pydantic 输出。"""

    if value is None:
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for entry in value:
            yield from _iter_fact_items(entry)
        return

    item = _to_mapping(value)
    if not item:
        return

    # 审核报告顶层也有 verdict=approved/needs_revision；必须优先下钻，
    # 不能把报告结论误当成一条事实断言。
    if "fact_check" in item:
        yield from _iter_fact_items(item["fact_check"])
        return
    if "audit_result" in item:
        yield from _iter_fact_items(item["audit_result"])
        return
    if "items" in item:
        yield from _iter_fact_items(item["items"])
        return
    if "claims" in item:
        yield from _iter_fact_items(item["claims"])
        return
    if "verdict" in item or "is_accurate" in item:
        yield item


def _resource_text(resource: Mapping[str, Any]) -> str:
    return "\n".join(
        part
        for part in (
            _to_text(resource.get("title")),
            _to_text(resource.get("content")),
            _to_text(resource.get("summary")),
        )
        if part
    )


def _style_score_from_content(content: str, expected_style: str) -> float:
    """用可解释的格式信号估算资源风格，返回 0~1。"""

    lowered = content.casefold()
    if not lowered.strip():
        return 0.0

    practice_markers = (
        "实操",
        "操作步骤",
        "练习",
        "示教",
        "调试",
        "故障排查",
        "注意事项",
        "动手",
        "步骤",
    )
    theory_markers = (
        "原理",
        "定义",
        "概念",
        "机制",
        "运动学",
        "坐标系",
        "理论",
        "为什么",
    )
    visual_markers = ("<img", "```mermaid", "流程图", "示意图", "如图", "|---")
    project_markers = ("项目目标", "项目任务", "验收标准", "完整项目", "综合实训", "里程碑")

    if expected_style == "practice_first":
        signals = sum(marker in lowered for marker in practice_markers)
        signals += int("```" in lowered)
        signals += int(
            bool(
                re.search(
                    r"(?:^|\n)\s*(?:\d+[.)、]|步骤[一二三四五六七八九十])",
                    content,
                )
            )
        )
        return min(signals / 3.0, 1.0)

    if expected_style == "theory_first":
        signals = sum(marker in lowered for marker in theory_markers)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        signals += int(any(len(p) >= 120 for p in paragraphs))
        return min(signals / 3.0, 1.0)

    if expected_style == "visual":
        signals = sum(marker in lowered for marker in visual_markers)
        signals += int(bool(re.search(r"!\[[^\]]*\]\([^)]*\)", content)))
        return min(signals / 2.0, 1.0)

    if expected_style == "project_based":
        signals = sum(marker in lowered for marker in project_markers)
        signals += int(bool(re.search(r"(?:^|\n)\s*(?:\d+[.)、]|步骤)", content)))
        return min(signals / 3.0, 1.0)

    return 0.0


def _extract_core_aliases(core_knowledge_map: Any) -> dict[str, set[str]]:
    """从宽松的核心知识点 JSON 结构中提取 topic→aliases。"""

    aliases: dict[str, set[str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            item = dict(node)
            topic = item.get("topic") or item.get("name") or item.get("knowledge_point")
            level = str(item.get("level") or item.get("priority") or "").casefold()
            if topic and (not level or level in _TARGET_PRIORITIES or level == "high"):
                values = {str(topic)}
                raw_aliases = item.get("aliases") or item.get("keywords") or []
                if isinstance(raw_aliases, str):
                    raw_aliases = [raw_aliases]
                if isinstance(raw_aliases, Sequence):
                    values.update(str(alias) for alias in raw_aliases if alias)
                # 画像可能使用 canonical topic，也可能使用任一别名；所有 key
                # 都指回同一组词，避免 alias 画像无法命中核心清单。
                for value in values:
                    key = _normalise_text(value)
                    if key:
                        aliases.setdefault(key, set()).update(values)
            for child in item.values():
                walk(child)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for child in node:
                walk(child)

    walk(core_knowledge_map)
    return aliases


class EvaluationMetrics:
    """三项指标评估器；阈值默认从全局 Settings 读取。"""

    def __init__(
        self,
        hallucination_threshold: float | None = None,
        adaptation_target: float | None = None,
        coverage_target: float | None = None,
    ) -> None:
        self.hallucination_threshold = (
            settings.HALLUCINATION_THRESHOLD
            if hallucination_threshold is None
            else hallucination_threshold
        )
        self.adaptation_target = (
            settings.ADAPTATION_TARGET if adaptation_target is None else adaptation_target
        )
        self.coverage_target = (
            settings.COVERAGE_TARGET if coverage_target is None else coverage_target
        )
        for name, value in (
            ("hallucination_threshold", self.hallucination_threshold),
            ("adaptation_target", self.adaptation_target),
            ("coverage_target", self.coverage_target),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    async def compute_all(
        self,
        fact_check: Any,
        diagnosis: Any,
        resources: Sequence[Any],
        *,
        expected_profile: Any | None = None,
        expected_gaps: Any | None = None,
        core_knowledge_map: Any | None = None,
    ) -> dict[str, Any]:
        """计算全部指标；保留 async 接口以便直接接入现有流水线。"""

        hallucination = self.compute_hallucination(fact_check)
        expected = _to_mapping(expected_profile)
        adaptation = self.compute_adaptation(
            diagnosis,
            resources,
            expected_profile=expected_profile,
        )
        coverage = self.compute_coverage(
            diagnosis,
            resources,
            core_knowledge_map=core_knowledge_map,
            expected_gaps=(
                expected_gaps
                if expected_gaps is not None
                else (
                    expected.get("expected_skill_gaps") or expected.get("expected_gaps")
                    if expected_profile is not None
                    else None
                )
            ),
        )
        all_pass = bool(hallucination["pass"] and adaptation["pass"] and coverage["pass"])
        suggestions: list[str] = []
        if not hallucination["pass"]:
            suggestions.append(
                f"幻觉率 {hallucination['rate']:.1%} 未满足 < {self.hallucination_threshold:.1%}；"
                "检查 hallucination/unverifiable 断言并补齐权威 KB 来源。"
            )
        if not adaptation["pass"]:
            suggestions.append(
                f"适配率 {adaptation['rate']:.1%} 未满足 ≥ {self.adaptation_target:.1%}；"
                "按画像标准答案调整资源难度或内容呈现风格。"
            )
        if not coverage["pass"]:
            suggestions.append(
                f"覆盖率 {coverage['rate']:.1%} 未满足 ≥ {self.coverage_target:.1%}；"
                f"优先补充盲区：{', '.join(coverage['uncovered_topics']) or '未提供有效盲区'}。"
            )

        result = {
            "hallucination": hallucination,
            "adaptation": adaptation,
            "coverage": coverage,
            "all_pass": all_pass,
            "suggestions": suggestions,
            "thresholds": {
                "hallucination_lt": self.hallucination_threshold,
                "adaptation_gte": self.adaptation_target,
                "coverage_gte": self.coverage_target,
            },
        }
        logger.info(
            "[Evaluation] hallucination={:.2%}, adaptation={:.2%}, coverage={:.2%}, all_pass={}",
            hallucination["rate"],
            adaptation["rate"],
            coverage["rate"],
            all_pass,
        )
        return result

    def compute_hallucination(self, fact_check: Any) -> dict[str, Any]:
        """幻觉率 = (hallucination + unverifiable) / 有效事实断言总数。

        partially_supported 核心事实成立，不计入坏样本分子（仅进分母）。
        """

        counts = {
            "accurate": 0,
            "hallucination": 0,
            "unverifiable": 0,
            "partially_supported": 0,
            "skip": 0,
        }
        invalid_count = 0
        for item in _iter_fact_items(fact_check):
            verdict = str(item.get("verdict") or "").strip().casefold()
            if not verdict and "is_accurate" in item:
                accurate = item.get("is_accurate")
                if accurate is True:
                    verdict = "accurate"
                elif accurate is False:
                    verdict = "hallucination"
                else:
                    # is_accurate=None 且无 verdict：保守按 unverifiable（旧兼容）
                    # 注意：partially_supported 的 item 自带 verdict 字段，
                    # 不会落入此分支，仍走 verdict 分支正确计数。
                    verdict = "unverifiable"
            if verdict not in _VALID_VERDICTS:
                # 未知标签不能静默从分母消失，否则会人为压低幻觉率。
                verdict = "unverifiable"
                invalid_count += 1
            counts[verdict] += 1

        total = (
            counts["accurate"]
            + counts["hallucination"]
            + counts["unverifiable"]
            + counts["partially_supported"]
        )
        numerator = counts["hallucination"] + counts["unverifiable"]
        rate = numerator / total if total else 0.0
        return {
            "rate": round(rate, 4),
            "pass": bool(total and rate < self.hallucination_threshold),
            "hallucination_count": counts["hallucination"],
            "unverifiable_count": counts["unverifiable"],
            "partially_supported_count": counts["partially_supported"],
            "accurate_count": counts["accurate"],
            "skip_count": counts["skip"],
            "invalid_verdict_count": invalid_count,
            "total": total,
            "reason": None if total else "no_fact_claims",
        }

    def compute_adaptation(
        self,
        diagnosis: Any,
        resources: Sequence[Any],
        *,
        expected_profile: Any | None = None,
    ) -> dict[str, Any]:
        """适配率 = (难度匹配 + 风格匹配) / 2。"""

        del diagnosis  # Phase 3 评测禁止使用模型自己的 diagnosis 充当真值。
        expected = _to_mapping(expected_profile)
        expected_difficulty_raw = expected.get("expected_difficulty") or expected.get(
            "recommended_difficulty"
        )
        expected_style_raw = expected.get("expected_learning_style") or expected.get(
            "learning_style"
        )
        expected_level = _normalise_difficulty(expected_difficulty_raw)
        expected_style = _normalise_style(expected_style_raw)
        resource_data = [_to_mapping(resource) for resource in resources]
        resource_data = [resource for resource in resource_data if resource]

        if not resource_data or expected_level is None or expected_style not in _VALID_STYLES:
            missing: list[str] = []
            if not resource_data:
                missing.append("resources")
            if expected_level is None:
                missing.append("expected_difficulty")
            if not expected_style:
                missing.append("expected_learning_style")
            elif expected_style not in _VALID_STYLES:
                missing.append("valid_expected_learning_style")
            return {
                "rate": 0.0,
                "pass": False,
                "difficulty_match": 0.0,
                "style_match": 0.0,
                "resource_count": len(resource_data),
                "ground_truth_provided": bool(expected_profile),
                "missing": missing,
                "details": [],
            }

        difficulty_scores: list[float] = []
        style_scores: list[float] = []
        details: list[dict[str, Any]] = []
        for index, resource in enumerate(resource_data):
            actual_raw = resource.get("difficulty_level") or resource.get("difficulty")
            actual_level = _normalise_difficulty(actual_raw)
            if actual_level is None:
                difficulty_score = 0.0
            else:
                gap = abs(expected_level - actual_level)
                difficulty_score = 1.0 if gap == 0 else 0.5 if gap == 1 else 0.0

            explicit_style = _normalise_style(
                resource.get("learning_style") or resource.get("style")
            )
            if explicit_style:
                style_score = 1.0 if explicit_style == expected_style else 0.0
                style_source = "explicit"
            else:
                style_score = _style_score_from_content(
                    _resource_text(resource),
                    expected_style,
                )
                style_source = "content_rules"

            difficulty_scores.append(difficulty_score)
            style_scores.append(style_score)
            details.append(
                {
                    "resource_index": index,
                    "resource_id": resource.get("resource_id") or resource.get("id"),
                    "actual_difficulty": actual_raw,
                    "difficulty_score": round(difficulty_score, 4),
                    "style_score": round(style_score, 4),
                    "style_source": style_source,
                }
            )

        difficulty_match = sum(difficulty_scores) / len(difficulty_scores)
        style_match = sum(style_scores) / len(style_scores)
        rate = (difficulty_match + style_match) / 2.0
        return {
            "rate": round(rate, 4),
            "pass": rate >= self.adaptation_target,
            "difficulty_match": round(difficulty_match, 4),
            "style_match": round(style_match, 4),
            "resource_count": len(resource_data),
            "expected_difficulty": str(
                getattr(expected_difficulty_raw, "value", expected_difficulty_raw)
            ),
            "expected_learning_style": expected_style,
            "ground_truth_provided": True,
            "missing": [],
            "details": details,
        }

    def compute_coverage(
        self,
        diagnosis: Any,
        resources: Sequence[Any],
        *,
        core_knowledge_map: Any | None = None,
        expected_gaps: Any | None = None,
    ) -> dict[str, Any]:
        """覆盖率 = 已覆盖的 critical/high 盲区 / 全部 critical/high 盲区。"""

        ground_truth_provided = expected_gaps is not None
        if ground_truth_provided:
            gaps = expected_gaps or []
        else:
            diagnosis_data = _to_mapping(diagnosis)
            gaps = diagnosis_data.get("skill_gaps") or []
        if not isinstance(gaps, Sequence) or isinstance(gaps, (str, bytes, bytearray)):
            gaps = []
        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_gap in gaps:
            gap = _to_mapping(raw_gap)
            priority = str(gap.get("priority") or "").strip().casefold()
            topic = str(gap.get("topic") or gap.get("knowledge_point") or "").strip()
            if priority not in {"critical", "high"} or not topic:
                continue
            key = _normalise_text(topic)
            if not key or key in seen:
                continue
            seen.add(key)
            targets.append({"topic": topic, "key": key, "aliases": set()})

        if not targets:
            return {
                "rate": 0.0,
                "pass": False,
                "covered": 0,
                "total_critical_high": 0,
                "covered_topics": [],
                "uncovered_topics": [],
                "not_applicable": True,
                "ground_truth_provided": ground_truth_provided,
                "reason": "no_critical_high_skill_gaps",
            }

        map_aliases = _extract_core_aliases(core_knowledge_map)
        for target in targets:
            target["aliases"].add(target["topic"])
            target["aliases"].update(map_aliases.get(target["key"], set()))

        resource_data = [_to_mapping(resource) for resource in resources]
        resource_data = [resource for resource in resource_data if resource]
        combined_raw_text = "\n".join(_resource_text(resource) for resource in resource_data)
        combined_text = _normalise_text(combined_raw_text)
        covered_topics: list[str] = []
        uncovered_topics: list[str] = []
        for target in targets:
            # target_skill_gaps 是生成器的“计划覆盖”字段，不是实际覆盖证据；
            # 只认可标题/正文中真实出现的 canonical topic 或别名。
            is_covered = any(
                _alias_is_covered(alias, combined_raw_text, combined_text)
                for alias in target["aliases"]
            )
            if is_covered:
                covered_topics.append(target["topic"])
            else:
                uncovered_topics.append(target["topic"])

        covered = len(covered_topics)
        total = len(targets)
        rate = covered / total
        return {
            "rate": round(rate, 4),
            "pass": ground_truth_provided and rate >= self.coverage_target,
            "covered": covered,
            "total_critical_high": total,
            "covered_topics": covered_topics,
            "uncovered_topics": uncovered_topics,
            "not_applicable": False,
            "ground_truth_provided": ground_truth_provided,
            "reason": None if ground_truth_provided else "external_expected_gaps_required",
        }


def calibrate_verdicts(
    predicted: Any,
    gold_items: Sequence[Any],
    *,
    minimum_accuracy: float = 0.90,
    minimum_gold_items: int = 50,
) -> dict[str, Any]:
    """用人工金标准标定 Agent3 三态判定准确率。"""

    predictions = list(_iter_fact_items(predicted))

    def key_for(item: Mapping[str, Any], index: int) -> str:
        return str(
            item.get("claim_id")
            or item.get("id")
            or item.get("claim")
            or item.get("statement")
            or f"__index_{index}"
        )

    predicted_by_key = {key_for(item, index): item for index, item in enumerate(predictions)}
    correct = 0
    missing: list[str] = []
    confusion: dict[str, dict[str, int]] = {}
    used_keys: set[str] = set()
    for index, raw_gold in enumerate(gold_items):
        gold = _to_mapping(raw_gold)
        key = key_for(gold, index)
        expected = str(gold.get("expected_verdict") or gold.get("verdict") or "").casefold()
        predicted_item = predicted_by_key.get(key)
        if predicted_item is None:
            missing.append(key)
            continue
        used_keys.add(key)
        actual = str(predicted_item.get("verdict") or "unverifiable").casefold()
        confusion.setdefault(expected, {}).setdefault(actual, 0)
        confusion[expected][actual] += 1
        if actual == expected:
            correct += 1

    total_gold = len(gold_items)
    accuracy = correct / total_gold if total_gold else 0.0
    unexpected = sorted(set(predicted_by_key) - used_keys)
    return {
        "accuracy": round(accuracy, 4),
        "pass": bool(total_gold >= minimum_gold_items and accuracy >= minimum_accuracy),
        "correct": correct,
        "total_gold": total_gold,
        "matched": total_gold - len(missing),
        "missing_prediction_keys": missing,
        "unexpected_prediction_keys": unexpected,
        "confusion_matrix": confusion,
        "minimum_accuracy": minimum_accuracy,
        "minimum_gold_items": minimum_gold_items,
        "dataset_size_pass": total_gold >= minimum_gold_items,
    }


def aggregate_case_results(
    case_results: Sequence[Mapping[str, Any]],
    *,
    hallucination_threshold: float | None = None,
    adaptation_target: float | None = None,
    coverage_target: float | None = None,
    minimum_cases: int = 50,
    minimum_profiles: int = 3,
    minimum_negative_cases: int = 3,
    maximum_negative_cases: int = 5,
) -> dict[str, Any]:
    """汇总 Phase 3 用例，并硬校验样本量及负样本数量。"""

    evaluator = EvaluationMetrics(
        hallucination_threshold=hallucination_threshold,
        adaptation_target=adaptation_target,
        coverage_target=coverage_target,
    )
    hallucination_bad = 0
    hallucination_total = 0
    coverage_covered = 0
    coverage_total = 0
    adaptation_rates: list[float] = []
    case_passed = 0
    positive_case_count = 0
    negative_case_count = 0
    negative_case_passed = 0
    profile_ids: set[str] = set()
    adaptation_ground_truth_cases = 0
    coverage_ground_truth_cases = 0
    for result in case_results:
        profile_id = str(result.get("profile_id") or "").strip()
        if profile_id:
            profile_ids.add(profile_id)
        if bool(result.get("is_negative")):
            negative_case_count += 1
            negative_case_passed += int(
                bool(result.get("negative_pass") or result.get("expected_behavior_pass"))
            )
            continue

        positive_case_count += 1
        hallucination = _to_mapping(result.get("hallucination"))
        adaptation = _to_mapping(result.get("adaptation"))
        coverage = _to_mapping(result.get("coverage"))
        hallucination_bad += int(hallucination.get("hallucination_count") or 0)
        hallucination_bad += int(hallucination.get("unverifiable_count") or 0)
        hallucination_total += int(hallucination.get("total") or 0)
        if adaptation.get("rate") is not None:
            adaptation_rates.append(float(adaptation["rate"]))
        adaptation_ground_truth_cases += int(bool(adaptation.get("ground_truth_provided")))
        coverage_case_total = max(
            int(coverage.get("total_critical_high") or 0),
            0,
        )
        if coverage_case_total:
            coverage_case_covered = max(int(coverage.get("covered") or 0), 0)
            coverage_covered += min(coverage_case_covered, coverage_case_total)
            coverage_total += coverage_case_total
        coverage_ground_truth_cases += int(bool(coverage.get("ground_truth_provided")))
        case_passed += int(bool(result.get("all_pass")))

    hallucination_rate = hallucination_bad / hallucination_total if hallucination_total else 0.0
    adaptation_rate = sum(adaptation_rates) / len(adaptation_rates) if adaptation_rates else 0.0
    coverage_rate = coverage_covered / coverage_total if coverage_total else 0.0
    hallucination_pass = bool(
        hallucination_total and hallucination_rate < evaluator.hallucination_threshold
    )
    adaptation_pass = bool(adaptation_rates and adaptation_rate >= evaluator.adaptation_target)
    coverage_pass = bool(coverage_total and coverage_rate >= evaluator.coverage_target)
    size_checks = {
        "minimum_cases": len(case_results) >= minimum_cases,
        "minimum_profiles": len(profile_ids) >= minimum_profiles,
        "negative_cases": (minimum_negative_cases <= negative_case_count <= maximum_negative_cases),
    }
    truth_checks = {
        "adaptation_external_truth": (
            positive_case_count > 0 and adaptation_ground_truth_cases == positive_case_count
        ),
        "coverage_external_truth": (
            positive_case_count > 0 and coverage_ground_truth_cases == positive_case_count
        ),
    }
    dataset_requirements_pass = all(size_checks.values()) and all(truth_checks.values())
    negative_cases_pass = bool(negative_case_count and negative_case_passed == negative_case_count)
    metrics_pass = hallucination_pass and adaptation_pass and coverage_pass
    return {
        "case_count": len(case_results),
        "case_passed": case_passed,
        "positive_case_count": positive_case_count,
        "negative_case_count": negative_case_count,
        "negative_case_passed": negative_case_passed,
        "profile_count": len(profile_ids),
        "hallucination": {
            "rate": round(hallucination_rate, 4),
            "pass": hallucination_pass,
            "bad_claims": hallucination_bad,
            "total_claims": hallucination_total,
        },
        "adaptation": {
            "rate": round(adaptation_rate, 4),
            "pass": adaptation_pass,
            "evaluated_cases": len(adaptation_rates),
        },
        "coverage": {
            "rate": round(coverage_rate, 4),
            "pass": coverage_pass,
            "covered_topics": coverage_covered,
            "total_topics": coverage_total,
        },
        "dataset_requirements": {
            "pass": dataset_requirements_pass,
            "checks": size_checks,
            "ground_truth_checks": truth_checks,
            "required": {
                "minimum_cases": minimum_cases,
                "minimum_profiles": minimum_profiles,
                "negative_cases": [minimum_negative_cases, maximum_negative_cases],
            },
        },
        "negative_cases_pass": negative_cases_pass,
        "metrics_pass": metrics_pass,
        "all_pass": (dataset_requirements_pass and negative_cases_pass and metrics_pass),
    }

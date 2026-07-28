"""三项硬指标自动评估模块（第二阶段填肉）。

评分标准直接对应的三个硬指标：
  1. 幻觉率（Hallucination Rate）— 要求 < 5%
  2. 适配率（Adaptation Rate）  — 要求 ≥ 85%
  3. 覆盖率（Coverage Rate）    — 要求 ≥ 90%

角色：人员4 — 质量量化。

══════════════════════════════════════════════
第一阶段（当前）：接口骨架 + 数据结构定义
第二阶段（Task 2.4）：完整计算逻辑实现
══════════════════════════════════════════════
"""
from __future__ import annotations

import re
from typing import Any

from loguru import logger

from ..config import settings


class EvaluationMetrics:
    """三项硬指标评估引擎。

    输入：
      - fact_check:  Agent 3 结构化事实核查输出（FactCheckResult / dict）
      - diagnosis:   Agent 1 学情诊断输出（含 skill_gaps、learning_style、recommended_difficulty）
      - resources:   Agent 2 生成的资源列表（list[GeneratedResource] / list[dict]）

    输出：
      - hallucination: 幻觉率 + pass 标记
      - adaptation:    适配率 + pass 标记
      - coverage:      覆盖率 + pass 标记
      - all_pass:      三项是否全部达标
      - suggestions:   不达标时的改进建议

    阈值来源：settings.HALLUCINATION_THRESHOLD / ADAPTATION_TARGET / COVERAGE_TARGET
    """

    # ═══════════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════════

    async def compute_all(
        self,
        fact_check: dict,
        diagnosis: dict,
        resources: list[dict],
    ) -> dict:
        """计算全部三项指标并返回汇总结果。

        Args:
            fact_check: Agent 3 的输出（或模拟数据）。
                必须包含: items (list), 每个 item 含 verdict (accurate/hallucination/unverifiable)
            diagnosis:  Agent 1 的输出。
                必须包含: skill_gaps, learning_style, recommended_difficulty
            resources:  Agent 2 的输出。
                每个资源含: content, difficulty_level, resource_type

        Returns:
            dict:
                - hallucination:  {rate, pass, ...}
                - adaptation:     {rate, pass, ...}
                - coverage:       {rate, pass, ...}
                - all_pass:       bool (三项都达标)
                - suggestions:    list[str] (不达标时给出改进建议)
        """
        hallucination = await self._compute_hallucination(fact_check)
        adaptation = await self._compute_adaptation(diagnosis, resources)
        coverage = await self._compute_coverage(diagnosis, resources)

        all_pass = (
            hallucination.get("pass", False)
            and adaptation.get("pass", False)
            and coverage.get("pass", False)
        )

        suggestions: list[str] = []
        if not hallucination.get("pass"):
            suggestions.append(
                f"幻觉率 {hallucination.get('rate', 0):.1%} 超标 "
                f"(阈值 < {settings.HALLUCINATION_THRESHOLD:.0%})，"
                f"建议加强 Agent 3 审核 + RAG 溯源约束"
            )
        if not adaptation.get("pass"):
            suggestions.append(
                f"适配率 {adaptation.get('rate', 0):.1%} 不达标 "
                f"(要求 ≥ {settings.ADAPTATION_TARGET:.0%})，"
                f"建议调整难度匹配或风格适配"
            )
        if not coverage.get("pass"):
            suggestions.append(
                f"覆盖率 {coverage.get('rate', 0):.1%} 不达标 "
                f"(要求 ≥ {settings.COVERAGE_TARGET:.0%})，"
                f"建议增补 critical/high 盲区覆盖"
            )

        logger.info(
            f"[评估] 幻觉率={hallucination.get('rate', 0):.2%} "
            f"适配率={adaptation.get('rate', 0):.2%} "
            f"覆盖率={coverage.get('rate', 0):.2%} "
            f"全部达标={all_pass}"
        )

        return {
            "hallucination": hallucination,
            "adaptation": adaptation,
            "coverage": coverage,
            "all_pass": all_pass,
            "suggestions": suggestions,
        }

    # ═══════════════════════════════════════════════════════════
    # 三项指标计算（骨架 — 第二阶段填肉）
    # ═══════════════════════════════════════════════════════════

    async def _compute_hallucination(self, fact_check: dict) -> dict:
        """计算幻觉率。

        公式：幻觉率 = (hallucination_count + unverifiable_count) / total_claims
        要求：< 5%（HALLUCINATION_THRESHOLD）

        Args:
            fact_check: {
                "items": [
                    {"claim": "...", "verdict": "accurate|hallucination|unverifiable", ...},
                    ...
                ]
            }

        Returns:
            {
                "rate": float,               # 幻觉率 (0-1)
                "pass": bool,                # 是否达标
                "hallucination_count": int,  # 幻觉断言数
                "unverifiable_count": int,   # 无法验证断言数
                "accurate_count": int,       # 准确断言数
                "total": int,                # 总断言数
            }
        """
        items = fact_check.get("items", [])
        total = len(items)

        if total == 0:
            return {
                "rate": 0.0,
                "pass": True,
                "hallucination_count": 0,
                "unverifiable_count": 0,
                "accurate_count": 0,
                "total": 0,
            }

        # 真实计算（已可直接使用，因为输入结构已确定）
        hallucination_count = sum(
            1 for item in items
            if item.get("verdict") == "hallucination"
            or item.get("is_accurate") is False
        )
        unverifiable_count = sum(
            1 for item in items
            if item.get("verdict") == "unverifiable"
        )
        accurate_count = total - hallucination_count - unverifiable_count

        rate = (hallucination_count + unverifiable_count) / total if total > 0 else 0.0
        passed = rate < settings.HALLUCINATION_THRESHOLD

        return {
            "rate": round(rate, 4),
            "pass": passed,
            "hallucination_count": hallucination_count,
            "unverifiable_count": unverifiable_count,
            "accurate_count": accurate_count,
            "total": total,
        }

    async def _compute_adaptation(self, diagnosis: dict, resources: list[dict]) -> dict:
        """计算适配率。

        适配率 = 难度匹配分 + 风格匹配分（归一化到 0-1）
          - 难度匹配：完全匹配=1.0 / 差1级=0.5 / 差2级=0.0
          - 风格匹配：practice_first 有足够代码示例=0.5 / theory_first 有足够理论段落=0.5
        要求：≥ 85%（ADAPTATION_TARGET）

        Args:
            diagnosis: 含 recommended_difficulty, learning_style
            resources: 含 difficulty_level, content

        Returns:
            {
                "rate": float,              # 适配率 (0-1)
                "pass": bool,               # 是否达标
                "difficulty_match": float,  # 难度匹配分
                "style_match": float,       # 风格匹配分
                "detail": str,              # 评估详情
            }
        """
        # TODO 第二阶段：风格匹配可升级为 LLM 语义判断
        if not resources:
            return {
                "rate": 0.0,
                "pass": False,
                "difficulty_match": 0.0,
                "style_match": 0.0,
                "detail": "无资源可评估",
            }

        learner_difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "practice_first")

        # 难度匹配
        difficulty_levels = {"beginner": 0, "intermediate": 1, "advanced": 2}
        learner_level = difficulty_levels.get(learner_difficulty, 0)

        total_diff_score = 0.0
        for r in resources:
            res_level = difficulty_levels.get(r.get("difficulty_level", "beginner"), 0)
            gap = abs(learner_level - res_level)
            if gap == 0:
                total_diff_score += 1.0
            elif gap == 1:
                total_diff_score += 0.5
            # gap >= 2 → 0.0

        difficulty_match = total_diff_score / len(resources) if resources else 0.0

        # 风格匹配：检测代码块/理论段落比例
        style_match = _estimate_style_match(resources, learning_style)

        rate = (difficulty_match + style_match) / 2.0
        passed = rate >= settings.ADAPTATION_TARGET

        return {
            "rate": round(rate, 4),
            "pass": passed,
            "difficulty_match": round(difficulty_match, 4),
            "style_match": round(style_match, 4),
            "detail": _format_adaptation_detail(
                difficulty_match, style_match, learner_difficulty, learning_style
            ),
        }

    async def _compute_coverage(self, diagnosis: dict, resources: list[dict]) -> dict:
        """计算盲区覆盖率。

        公式：覆盖率 = 资源中覆盖的 critical/high 盲区数 / 总 critical/high 盲区数
        要求：≥ 90%（COVERAGE_TARGET）

        覆盖判定：资源 content 或 title 中包含盲区 topic 关键词（大小写不敏感）。

        Args:
            diagnosis: 含 skill_gaps (list[{topic, priority, ...}])
            resources: 含 content, title, target_skill_gaps

        Returns:
            {
                "rate": float,             # 覆盖率 (0-1)
                "pass": bool,              # 是否达标
                "covered": int,            # 已覆盖的 critical/high 盲区数
                "total_critical_high": int,# 总 critical/high 盲区数
                "uncovered": list[str],    # 未覆盖的盲区 topic 列表
            }
        """
        # TODO 第二阶段：关键词匹配可升级为 LLM 语义匹配
        skill_gaps = diagnosis.get("skill_gaps", [])

        # 筛选 critical + high 盲区
        critical_high = [
            g for g in skill_gaps
            if g.get("priority") in ("critical", "high")
        ]

        if not critical_high:
            return {
                "rate": 1.0,
                "pass": True,
                "covered": 0,
                "total_critical_high": 0,
                "uncovered": [],
            }

        # 合并所有资源文本
        all_text = " ".join(
            r.get("content", "") + " " + r.get("title", "")
            for r in resources
        ).lower()

        # 检查每个盲区是否被覆盖
        covered_topics: list[str] = []
        uncovered_topics: list[str] = []

        for gap in critical_high:
            topic = gap.get("topic", "")
            # 直接关键词匹配
            if topic.lower() in all_text:
                covered_topics.append(topic)
            else:
                uncovered_topics.append(topic)

        covered = len(covered_topics)
        total = len(critical_high)
        rate = covered / total if total > 0 else 1.0
        passed = rate >= settings.COVERAGE_TARGET

        return {
            "rate": round(rate, 4),
            "pass": passed,
            "covered": covered,
            "total_critical_high": total,
            "uncovered": uncovered_topics,
        }


# ═══════════════════════════════════════════════════════════
# 私有辅助
# ═══════════════════════════════════════════════════════════


def _estimate_style_match(resources: list[dict], learning_style: str) -> float:
    """估算风格匹配度。

    practice_first → 检查代码块比例是否足够（≥30% 资源含代码块）
    theory_first   → 检查理论段落比例是否足够（≥30% 资源含长段落）
    visual         → 检查是否有图表/示意图标记
    project_based  → 检查是否有实操步骤/项目说明

    Returns:
        float: 0.0 ~ 0.5 的风格匹配分
    """
    if not resources:
        return 0.0

    if learning_style == "practice_first":
        # 检查有多少资源包含代码块（``` 标记）
        code_resources = sum(
            1 for r in resources
            if "```" in r.get("content", "")
        )
        ratio = code_resources / len(resources)
        return 0.5 * min(ratio / 0.3, 1.0)  # 30% 为满分线

    elif learning_style == "theory_first":
        # 检查有多少资源包含较长理论段落（>500 字符的非代码段落）
        theory_count = 0
        for r in resources:
            content = r.get("content", "")
            # 移除代码块
            text_only = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            # 检查是否有 >500 字符的段落
            paragraphs = [p.strip() for p in text_only.split("\n\n") if p.strip()]
            if any(len(p) > 500 for p in paragraphs):
                theory_count += 1
        ratio = theory_count / len(resources)
        return 0.5 * min(ratio / 0.3, 1.0)

    elif learning_style == "visual":
        # 检查图片/图表引用标记
        visual_markers = ("![]", "<img", "```mermaid", "图表", "图示", "如图")
        visual_count = sum(
            1 for r in resources
            if any(m in r.get("content", "") for m in visual_markers)
        )
        ratio = visual_count / len(resources)
        return 0.5 * min(ratio / 0.3, 1.0)

    elif learning_style == "project_based":
        # 检查实操步骤/项目说明
        project_markers = ("## 步骤", "实操", "项目说明", "动手", "练习")
        project_count = sum(
            1 for r in resources
            if any(m in r.get("content", "") for m in project_markers)
        )
        ratio = project_count / len(resources)
        return 0.5 * min(ratio / 0.3, 1.0)

    return 0.25  # 未知风格给一半


def _format_adaptation_detail(
    difficulty_match: float,
    style_match: float,
    learner_difficulty: str,
    learning_style: str,
) -> str:
    """格式化适配率详情说明。"""
    parts = [
        f"学习者难度={learner_difficulty}, 风格={learning_style}",
        f"难度匹配={difficulty_match:.2f}, 风格匹配={style_match:.2f}",
    ]
    if difficulty_match < 0.8:
        parts.append("[WARN] difficulty match low")
    if style_match < 0.3:
        parts.append("[WARN] style match low, consider adjusting content format")
    return "; ".join(parts)

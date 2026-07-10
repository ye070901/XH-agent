"""
评估模块 — 自动计算三项硬指标。
角色7 在此实现。

评分标准要求的三个定量指标：
1. 幻觉率 < 5%（专业知识谬误率）
2. 学习者画像-资源难度适配准确率 ≥ 85%
3. 核心知识点覆盖率 ≥ 90%
"""
from loguru import logger


class MetricsEvaluator:
    """自动评估器 — 交之前跑一遍，知道自己的分数"""

    def evaluate(
        self,
        audit_reports: list[dict],
        diagnosis_result: dict,
        generated_resources: list[dict],
    ) -> dict:
        """
        计算三项核心指标。

        Returns:
            dict: {
                "hallucination_rate": float,       # 幻觉率（越低越好, <5%）
                "adaptation_accuracy": float,       # 难度适配率（越高越好, ≥85%）
                "knowledge_coverage": float,        # 知识点覆盖率（越高越好, ≥90%）
                "overall_score": float,             # 综合分数（实用价值30分对应）
                "passed": bool,                     # 是否三项全部达标
                "details": dict,                    # 详细数据
            }
        """
        h_rate = self._calc_hallucination_rate(audit_reports)
        a_rate = self._calc_adaptation(audit_reports, diagnosis_result)
        k_rate = self._calc_coverage(audit_reports, diagnosis_result, generated_resources)

        all_passed = (h_rate < 0.05) and (a_rate >= 0.85) and (k_rate >= 0.90)

        return {
            "hallucination_rate": round(h_rate, 4),
            "hallucination_passed": h_rate < 0.05,
            "adaptation_accuracy": round(a_rate, 4),
            "adaptation_passed": a_rate >= 0.85,
            "knowledge_coverage": round(k_rate, 4),
            "coverage_passed": k_rate >= 0.90,
            "all_passed": all_passed,
            "practical_value_score": self._estimate_score(h_rate, a_rate, k_rate),
            "details": {
                "total_claims_reviewed": self._count_claims(audit_reports),
                "total_hallucinations": self._count_hallucinations(audit_reports),
                "resources_generated": len(generated_resources),
                "target_gaps": len(diagnosis_result.get("skill_gaps", [])),
            },
        }

    def _calc_hallucination_rate(self, audit_reports: list[dict]) -> float:
        """幻觉率 = 错误断言数 / 总断言数"""
        total_claims = 0
        total_hallucinations = 0
        for report in audit_reports:
            fact_check = report.get("fact_check", {})
            total_claims += len(fact_check.get("items", []))
            total_hallucinations += fact_check.get("hallucination_count", 0)
        if total_claims == 0:
            return 1.0  # 没有审查任何断言 → 幻觉率100%（最差）
        return total_hallucinations / total_claims

    def _calc_adaptation(
        self, audit_reports: list[dict], diagnosis: dict
    ) -> float:
        """难度适配率 = 难度匹配的资源数 / 总资源数"""
        if not audit_reports:
            return 0.0
        matched = sum(
            1 for r in audit_reports
            if r.get("difficulty_match", {}).get("is_match", False)
        )
        return matched / len(audit_reports)

    def _calc_coverage(
        self, audit_reports: list[dict], diagnosis: dict, resources: list[dict]
    ) -> float:
        """知识覆盖率 = 被覆盖的知识点数 / 目标知识点总数"""
        target_gaps = diagnosis.get("skill_gaps", [])
        if not target_gaps:
            return 1.0

        # 从资源中提取覆盖的知识点
        covered_topics = set()
        for resource in resources:
            for gap_topic in resource.get("target_skill_gaps", []):
                covered_topics.add(gap_topic.lower())

        target_topics = {g.get("topic", "").lower() for g in target_gaps}
        if not target_topics:
            return 1.0

        return len(covered_topics & target_topics) / len(target_topics)

    def _estimate_score(
        self, h_rate: float, a_rate: float, k_rate: float
    ) -> int:
        """根据指标估算实用价值分数（满分30）"""
        score = 30
        if h_rate >= 0.05:
            score -= int((h_rate - 0.05) * 200)  # 每超1%扣2分
        if a_rate < 0.85:
            score -= int((0.85 - a_rate) * 100)
        if k_rate < 0.90:
            score -= int((0.90 - k_rate) * 100)
        return max(0, min(30, score))

    def _count_claims(self, reports: list[dict]) -> int:
        return sum(len(r.get("fact_check", {}).get("items", [])) for r in reports)

    def _count_hallucinations(self, reports: list[dict]) -> int:
        return sum(r.get("fact_check", {}).get("hallucination_count", 0) for r in reports)


# 全局单例
evaluator = MetricsEvaluator()

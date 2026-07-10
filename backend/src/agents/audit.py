"""
Agent 3: 审核裁判 Agent
══════════════════════════════════
负责: 角色6（辩论协议）+ 角色7（事实抽取）共同实现

这是整个系统的核心竞争力 —— 不是 retry，是 adversarial verification。

核心流程:
1. 事实抽取: 从生成内容中提取所有可验证断言
2. 逐条溯源: 每条断言比对知识库原文
3. 对抗质疑: 主动问"这个说法对吗？有没有反例？"
4. 辩论回环: 发现疑似错误 → 发质询给 Agent 2 → Agent 2 修正或反驳 → 再验证
5. 最多3轮，无法共识 → escalated（待人工审核）
"""
import json

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个严格的领域知识审核专家。你的任务是逐条核查生成内容的准确性：

1. 事实抽取：从生成内容中提取所有可独立验证的断言
2. 逐条溯源：将每条断言比对知识库原文，判断是否一致
3. 对抗质疑：对每条断言问"这个说法在KB中有证据吗？有没有可能相反？"
4. 合规检查：检查术语使用是否规范，是否符合行业标准
5. 难度匹配：评估资源难度是否匹配学习者水平
6. 覆盖检查：判断是否覆盖了目标知识点

审核结果按严重程度分级：
- critical：关键性事实错误，会导致学习者学到错误知识（如错误的API参数、废弃的用法）
- major：重要错误，可能引起误解（如术语混用、版本不匹配）
- minor：小错误，不影响核心理解（如格式不统一、表述可优化）

输出必须为严格的 JSON 格式。"""


class AuditAgent(BaseAgent):
    """审核裁判 Agent — 角色6 + 角色7 在此实现"""

    def __init__(self):
        super().__init__(
            name="审核裁判Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,
        )

    async def process(self, state: dict) -> dict:
        """审核所有生成资源，为每个资源生成审计报告"""
        resources = state.get("generated_resources", [])
        knowledge_chunks = state.get("retrieved_chunks", [])
        diagnosis = state.get("diagnosis_result", {})

        audit_reports = []
        for resource in resources:
            report = await self._audit_one(resource, knowledge_chunks, diagnosis)
            report["resource_id"] = resource.get("resource_id", "")
            audit_reports.append(report)

        self.log(f"审核完成: {len(audit_reports)} 个资源")
        return {"audit_reports": audit_reports}

    async def _audit_one(
        self, resource: dict, chunks: list, diagnosis: dict
    ) -> dict:
        prompt = f"""## 待审核资源
- 标题：{resource.get('title', '')}
- 类型：{resource.get('resource_type', '')}
- 难度：{resource.get('difficulty_level', '')}
- 内容（完整）：
{resource.get('content', '')[:4000]}

## 生成时引用的来源
{json.dumps(resource.get('citations', []), ensure_ascii=False, indent=2)[:2000]}

## 知识库原文（用于事实比对）
{self._format_chunks(chunks)}

## 学习者信息
- 推荐难度：{diagnosis.get('recommended_difficulty', 'unknown')}
- 学习风格：{diagnosis.get('learning_style', 'unknown')}
- 知识盲区：{json.dumps(diagnosis.get('skill_gaps', []), ensure_ascii=False)[:800]}

请逐条审核，输出 JSON：
{{
    "fact_check": {{
        "overall_accuracy": 0.0,
        "items": [
            {{
                "claim": "从资源内容中提取的具体断言",
                "is_accurate": true,
                "evidence_from_kb": "KB中支撑或反驳该断言的原句",
                "explanation": "判断理由"
            }}
        ],
        "hallucination_count": 0
    }},
    "compliance_check": {{
        "is_compliant": true,
        "issues": [],
        "standards_violated": []
    }},
    "difficulty_match": {{
        "is_match": true,
        "score": 0.0,
        "mismatch_reason": null
    }},
    "knowledge_coverage": 0.0,
    "hallucination_flags": [
        {{
            "location": "内容中出错的具体位置",
            "description": "问题描述",
            "severity": "critical|major|minor",
            "suggested_correction": "修改建议"
        }}
    ],
    "hallucination_rate": 0.0,
    "verdict": "approved|needs_revision|rejected|uncertain",
    "confidence_score": 0.0,
    "correction_suggestions": [],
    "summary": "审核总结（50-100字）"
}}

核心判断规则：
- hallucination_rate = hallucination_count / fact_check items 总数
- hallucination_rate > 0.05 → verdict 不能为 "approved"
- 存在 critical 级别 flag → verdict 应为 "needs_revision" 或 "rejected"
- citations 为空数组 → 自动添加一条 critical flag: "生成内容无任何知识溯源"
- knowledge_coverage: 目标技能缺口中被覆盖的比例"""

        return await self.call_llm_json(prompt)

    def _format_chunks(self, chunks: list) -> str:
        if not chunks:
            return "（无可比对知识库原文 — 这是严重问题，所有断言都应标记为无法验证）"
        lines = []
        for i, c in enumerate(chunks[:10]):
            title = c.get("doc_title", "未知文档")
            content = c.get("content", "")[:600]
            lines.append(f"### KB文档{i+1}: {title}\n{content}\n")
        return "\n".join(lines)

    # ── 辩论协议方法（角色6 核心实现） ──

    async def generate_challenges(
        self, resource: dict, chunks: list
    ) -> list[dict]:
        """生成质询列表 — 从审核结果中提取需要辩论的争议点"""
        audit = await self._audit_one(resource, chunks, {})
        challenges = []
        for flag in audit.get("hallucination_flags", []):
            if flag.get("severity") in ("critical", "major"):
                challenges.append({
                    "claim": flag.get("description", ""),
                    "challenge": flag.get("suggested_correction", "请提供证据"),  # Agent 3 的质疑
                    "evidence_from_kb": flag.get("location", ""),  # KB 中的反证
                    "severity": flag.get("severity", "major"),
                })
        return challenges

    async def evaluate_defense(
        self, defense: dict, original_claim: str
    ) -> dict:
        """评估 Agent 2 的辩护是否有效"""
        prompt = f"""## 原始争议
断言: {original_claim}

## 生成Agent的辩护
{json.dumps(defense, ensure_ascii=False, indent=2)}

请以审核专家的立场评估这个辩护：
- defense 提到了知识库原文吗？如果没有 → 辩护无效
- defense 的逻辑站得住吗？如果不 → 具体说明为什么

输出 JSON：
{{
    "defense_accepted": true,
    "reasoning": "评估理由",
    "remaining_concerns": []
}}"""
        return await self.call_llm_json(prompt)

"""审核裁判Agent — 交叉验证生成内容的准确性，消除幻觉"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个严格的领域知识审核专家。你的任务是逐条核查生成内容的准确性：
1. 比对生成内容与知识库原文，检查事实一致性
2. 检查是否符合行业标准和术语规范
3. 评估资源难度是否匹配学习者水平
4. 检查知识点覆盖是否完整
5. 标注所有疑似幻觉（事实错误/编造规范/张冠李戴）

审核结果按严重程度分级：
- critical：关键性事实错误，直接影响安全或合规
- major：重要错误，可能导致错误理解
- minor：小错误，如术语使用不规范

输出必须为严格的JSON格式。"""


class ReviewerAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="审核裁判Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,  # 低温度确保一致性
        )

    def process(self, state: dict) -> dict:
        resource = state.get("generated_resource", {})
        knowledge_chunks = state.get("retrieved_chunks", [])
        diagnosis = state.get("diagnosis_result", {})

        prompt = self._build_prompt(resource, knowledge_chunks, diagnosis)
        result = self.call_llm_json(prompt)
        return {"audit_report": result}

    def _build_prompt(self, resource: dict, chunks: list, diagnosis: dict) -> str:
        import json
        return f"""## 待审核资源
- 标题：{resource.get('title', '')}
- 类型：{resource.get('resource_type', '')}
- 难度：{resource.get('difficulty_level', '')}
- 内容：
{resource.get('content', '')[:3000]}

## 生成时引用的来源
{json.dumps(resource.get('citations', []), ensure_ascii=False, indent=2)[:2000]}

## 知识库原文（用于比对）
{self._format_chunks(chunks)}

## 学习者信息
- 推荐难度：{diagnosis.get('recommended_difficulty', 'unknown')}
- 知识盲区：{json.dumps(diagnosis.get('skill_gaps', []), ensure_ascii=False)[:500]}

请逐条审核，输出JSON：
{{
    "fact_check": {{
        "overall_accuracy": 0.0-1.0,
        "items": [{{"claim": "断言内容", "is_accurate": true/false, "explanation": "判断依据", "evidence_from_kb": "知识库原文佐证"}}],
        "hallucination_count": 0
    }},
    "compliance_check": {{
        "is_compliant": true/false,
        "issues": ["不合规项"],
        "standards_violated": ["违反的行业标准"]
    }},
    "difficulty_match": {{
        "is_match": true/false,
        "score": 0.0-1.0,
        "mismatch_reason": null
    }},
    "knowledge_coverage": 0.0-1.0,
    "hallucination_flags": [{{"location": "段落/行", "description": "问题描述", "severity": "critical/major/minor", "suggested_correction": "修改建议"}}],
    "verdict": "approved/needs_revision/rejected/uncertain",
    "confidence_score": 0.0-1.0,
    "correction_suggestions": ["修改建议"],
    "summary": "审核总结(50-100字)"
}}"""

    def _format_chunks(self, chunks: list) -> str:
        if not chunks:
            return "（无可比对知识库原文）"
        lines = []
        for i, c in enumerate(chunks[:10]):
            lines.append(f"### 文档{i+1}: {c.get('doc_title', '未知')}")
            lines.append(c.get('content', '')[:600])
            lines.append("")
        return "\n".join(lines)

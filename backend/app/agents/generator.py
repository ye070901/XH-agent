"""领域知识生成Agent — RAG增强生成个性化学习资源"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个垂直领域的知识专家和教育内容创作者。你的任务是：
1. 基于领域知识库检索结果，生成高保真的学习资源
2. 每条专业断言必须引用知识库原文（citation）
3. 针对学习者的知识盲区定制内容
4. 按指定难度等级调整内容深度

生成资源类型：
- lecture（定制讲义）：系统性理论讲解，含知识溯源
- guide（实操指南）：分步操作手册，含真实场景
- quiz（分阶测试题）：选择题/填空题/实操题，分基础/进阶/挑战三级

输出必须为严格的JSON格式。"""


class GeneratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="领域知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    def process(self, state: dict) -> dict:
        diagnosis = state.get("diagnosis_result", {})
        knowledge_chunks = state.get("retrieved_chunks", [])
        resource_type = state.get("resource_type", "lecture")

        prompt = self._build_prompt(diagnosis, knowledge_chunks, resource_type)
        result = self.call_llm_json(prompt)
        return {"generated_resource": result}

    def _build_prompt(self, diagnosis: dict, chunks: list, rtype: str) -> str:
        gaps = diagnosis.get("skill_gaps", [])
        difficulty = diagnosis.get("recommended_difficulty", "beginner")

        chunks_text = ""
        for i, c in enumerate(chunks[:10]):
            chunks_text += f"\n### 参考资料{i+1} (来自{c.get('doc_title', '未知')})\n{c.get('content', '')[:500]}\n"

        return f"""## 学习者信息
- 知识盲区：{json.dumps(gaps, ensure_ascii=False)}
- 推荐难度：{difficulty}
- 学习风格：{diagnosis.get('learning_style', 'unknown')}

## 领域知识库检索结果
{chunks_text if chunks_text else '(无检索结果，请基于通用知识生成，并在citations中标注为"通用知识")'}

## 生成任务
请生成一份{rtype}类型的个性化学习资源。

输出JSON：
{{
    "title": "资源标题",
    "content": "Markdown格式的完整内容",
    "citations": [{{"ref_index": 1, "cite_text": "引用的原文片段", "usage": "在正文中的使用位置"}}],
    "difficulty_level": "beginner/intermediate/advanced",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["关键要点1", "关键要点2"]
}}

要求：
1. 每条专业断言必须有citation
2. 内容难度匹配学习者的recommended_difficulty
3. 用Markdown格式，代码块```标注语言
4. 面向target skill gaps中的知识点"""

"""
Agent 2: 领域知识生成 Agent
══════════════════════════════════
负责: 角色5 实现
输入: state["diagnosis_result"] + state["retrieved_chunks"]
输出: state["generated_resources"] (list of GeneratedResource)

核心约束: 内容从知识库检索，表达方式由 LLM 适配。两者不混。
每条专业断言必须有 citation，无 citation 的断言将被 Agent 3 标记为疑似幻觉。
"""
import uuid

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个垂直领域的知识专家和教育内容创作者。你的任务是：
1. 基于领域知识库检索结果（retrieved_chunks），生成高保真的个性化学习资源
2. 每条专业断言必须引用知识库原文（citation），标注文档编号和原文片段
3. 针对学习者的知识盲区（skill_gaps）定制内容
4. 按指定难度等级调整表达深度和示例复杂度

生成资源类型：
- lecture（定制讲义）：系统性理论讲解，含知识溯源
- guide（实操指南）：分步操作手册，含真实代码示例和命令行
- quiz（分阶测试题）：选择题/填空题/实操题，各含基础/进阶/挑战三级

核心规则：
- 你不能编造不在知识库中的专业事实
- 如果知识库没有覆盖某个知识点，请诚实标注"通用知识参考"而非伪造 citation
- 个性化体现在表达方式、示例选择、路径顺序，而非专业内容的准确性

输出必须为严格的 JSON 格式。"""


class GenerationAgent(BaseAgent):
    """领域知识生成 Agent — 角色5 在此实现"""

    def __init__(self):
        super().__init__(
            name="知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    async def process(self, state: dict) -> dict:
        diagnosis = state.get("diagnosis_result", {})
        knowledge_chunks = state.get("retrieved_chunks", [])
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])

        resources = []
        for rtype in resource_types:
            s = {**state, "resource_type": rtype}
            result = await self._generate_one(diagnosis, knowledge_chunks, rtype)
            if result:
                result["resource_type"] = rtype
                result["resource_id"] = str(uuid.uuid4())
                resources.append(result)

        self.log(f"生成完成: {len(resources)} 个资源")
        return {"generated_resources": resources}

    async def _generate_one(
        self, diagnosis: dict, chunks: list, rtype: str
    ) -> dict:
        gaps = diagnosis.get("skill_gaps", [])
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "unknown")

        # 格式化知识库内容
        chunks_text = ""
        for i, c in enumerate(chunks[:10]):
            title = c.get("doc_title", "未知文档")
            content = c.get("content", "")[:600]
            chunks_text += f"\n### KB文档{i+1}: {title}\n{content}\n"

        prompt = f"""## 学习者画像
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}
- 推荐难度：{difficulty}
- 学习风格：{learning_style}

## 领域知识库检索结果（这是你生成内容的唯一专业依据）
{chunks_text if chunks_text else '（无KB检索结果。这种情况下你不能生成专业内容，请返回 {"error": "no_knowledge_base"} ）'}

## 生成任务
请生成一份 {rtype} 类型的个性化学习资源。

输出 JSON：
{{
    "title": "资源标题",
    "content": "Markdown 格式的完整内容（含代码示例和命令行时用 `````` 标注语言类型）",
    "citations": [
        {{
            "ref_index": 1,
            "original_text": "从KB原文中逐字引用的片段",
            "usage": "在正文中的使用位置说明"
        }}
    ],
    "difficulty_level": "{difficulty}",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["关键要点1", "关键要点2", "关键要点3"]
}}

要求：
1. content 中每条专业断言后标注引用编号如 [ref:1]
2. citations 不能为空（除非 KB 无相关内容）
3. 代码示例和命令行的语言/框架版本要与 KB 保持一致
4. 内容难度匹配 {difficulty}，示例数量适配 {learning_style} 学习风格"""

        return await self.call_llm_json(prompt)

    def _fmt_gaps(self, gaps: list) -> str:
        if not gaps:
            return "无特定知识盲区"
        return "\n".join(
            f"- [{g.get('priority', '?')}] {g.get('topic', '未知')} "
            f"(当前{g.get('current_level', 0):.1f} → 目标{g.get('target_level', 1.0):.1f}): "
            f"{g.get('reason', '')}"
            for g in gaps[:5]
        )

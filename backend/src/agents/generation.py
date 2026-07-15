"""
Agent 2: 领域知识生成 Agent
══════════════════════════════════
负责: 角色5 实现

MVP 版本: 直接用 LLM 自身知识生成内容（不依赖外部知识库）
Phase 2 版本: 接入 RAG 知识库，约束生成 + 溯源

输入: state["diagnosis_result"] + state["resource_types"]
输出: state["generated_resources"] (list of GeneratedResource)
"""
import uuid

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个垂直领域的知识专家和教育内容创作者。你的任务是：
1. 根据学习者的知识盲区（skill_gaps）和推荐难度，用你的专业知识生成个性化学习资源
2. 生成的内容必须准确、实用，代码示例可以直接运行
3. 个性化体现在：解释深度、示例复杂度、学习路径建议

生成资源类型：
- lecture（定制讲义）：系统性理论讲解，含代码示例
- guide（实操指南）：分步操作手册，含真实命令行和完整代码
- quiz（分阶测试题）：选择题/填空题/实操题，分基础/进阶/挑战三级

重要规则：
- 学情盲区标注了 critical 的知识点 → 这是本次生成必须覆盖的核心内容
- 难度匹配学习者水平：beginner 多用比喻和注释，advanced 减少解释直接给代码
- learning_style 为 practice_first 时多给实操示例，theory_first 时先讲原理

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
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])

        resources = []
        for rtype in resource_types:
            result = await self._generate_one(diagnosis, rtype)
            if result:
                result["resource_type"] = rtype
                result["resource_id"] = str(uuid.uuid4())
                resources.append(result)

        self.log(f"生成完成: {len(resources)} 个资源")
        return {"generated_resources": resources}

    async def _generate_one(self, diagnosis: dict, rtype: str) -> dict:
        gaps = diagnosis.get("skill_gaps", [])
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "unknown")
        learning_goal = diagnosis.get("summary", "")

        prompt = f"""## 学习者画像
- 学习目标总结：{learning_goal}
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}
- 推荐难度：{difficulty}
- 学习风格：{learning_style}

## 生成任务
请用你的专业知识，生成一份 {rtype} 类型的个性化学习资源。

输出 JSON：
{{
    "title": "资源标题（要具体、有吸引力）",
    "content": "Markdown 格式的完整内容（含代码示例和命令行时用 `````` 标注语言类型）",
    "difficulty_level": "{difficulty}",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["学完你能掌握什么1", "学完你能掌握什么2", "学完你能掌握什么3"]
}}

要求：
1. 内容必须准确——这是教育场景，教错了比不教更糟
2. 代码示例完整可运行，命令行标注操作系统（Windows/Linux/Mac）
3. 难度匹配 {difficulty} 水平：
   - beginner: 多用生活类比，每行代码加注释
   - intermediate: 适当减少注释，引入进阶概念
   - advanced: 精简解释，给高质量代码和架构思考
4. 学习风格为 {learning_style}：
   - practice_first: 先给代码再解释原理
   - theory_first: 先讲清楚为什么再给代码
5. 优先覆盖 critical 和 high 优先级的知识盲区"""

        return await self.call_llm_json(prompt)

    def _fmt_gaps(self, gaps: list) -> str:
        if not gaps:
            return "学习者未提供具体知识盲区，请根据学习目标生成通用的入门内容"
        return "\n".join(
            f"- [{g.get('priority', '?')}] {g.get('topic', '未知')} "
            f"(当前{g.get('current_level', 0):.1f} → 目标{g.get('target_level', 1.0):.1f}): "
            f"{g.get('reason', '')}"
            for g in gaps[:5]
        )

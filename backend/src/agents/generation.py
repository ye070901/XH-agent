"""
Agent 2: 领域知识生成 Agent
══════════════════════════════════
负责: 角色5 实现

MVP 版本: 直接用 LLM 自身知识生成内容（不依赖外部知识库）
Phase 2b: 接入 RAG 知识库，约束生成 + 溯源（本期不实现，见 process() 标记）

输入: state["diagnosis_result"] + state["resource_types"]
输出: state["generated_resources"]（list[dict]，最多 3 条）
      每条资源字段与 schemas.GeneratedResource 对齐:
      resource_id / learner_id / resource_type / title / content(markdown) /
      citations / difficulty_level / target_skill_gaps / estimated_duration_minutes /
      prerequisites / key_takeaways
"""

from __future__ import annotations

import uuid

from .base import BaseAgent
from .event_bus import event_bus

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

输出必须为严格的 JSON 格式。

【你仅处理工业机器人故障诊断相关任务，领域包含FANUC、KUKA、ABB工业机器人、示教器、机器人故障代码；拒绝回答和机器人故障无关的问题。】"""


class GenerationAgent(BaseAgent):
    """领域知识生成 Agent — 角色5 在此实现"""

    REQUIRED_STATE_KEYS = {"diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "learner_data",
        "resource_types",
        "task_id",
        "agent_log",
        "status",
        "learner_id",  # schemas.GeneratedResource.learner_id，从 state 透传
    }

    # 单次生成资源数量上限，防止 token 过度消耗
    MAX_RESOURCES = 3

    def __init__(self):
        super().__init__(
            name="知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    async def run(self, state: dict) -> dict:
        """统一入口：读取 diagnosis_result + resource_types → 生成 → 写回 state。

        EventBus 埋点：
          ① 函数最开头发布 ``agent.start``
          ② return 之前发布 ``agent.done``
        """
        event_bus.publish("agent.start", {"agent_name": self.__class__.__name__})

        state.setdefault("agent_log", [])
        diagnosis_result = state.get("diagnosis_result", {})
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])
        learner_id = state.get("learner_id", "")

        resources = await self.process(diagnosis_result, resource_types, learner_id)
        state["generated_resources"] = resources

        state["agent_log"].append(
            {
                "agent": self.name,
                "level": "info",
                "stage": "complete",
                "message": f"生成完成: {len(resources)} 个资源",
            }
        )
        self.log(f"生成完成: {len(resources)} 个资源")

        event_bus.publish("agent.done", {"agent_name": self.__class__.__name__})
        return state

    async def process(
        self,
        diagnosis_result: dict,
        resource_types: list[str],
        learner_id: str = "",
    ) -> list[dict]:
        """根据诊断结果与资源类型，生成个性化学习资源（最多 3 条）。

        Args:
            diagnosis_result: Agent1 学情诊断结果 dict
                              （含 skill_gaps / recommended_difficulty /
                              learning_style / summary）
            resource_types:   请求的资源类型列表（lecture / guide / quiz）
            learner_id:       学习者 ID，透传到每条资源的
                              schemas.GeneratedResource.learner_id

        Returns:
            list[dict]: 每条字段与 schemas.GeneratedResource 对齐
                        （resource_id / resource_type / title / content /
                        difficulty_level / citations / target_skill_gaps /
                        estimated_duration_minutes / prerequisites /
                        key_takeaways / learner_id）；
                        单个类型生成失败则跳过。
        """
        gaps = diagnosis_result.get("skill_gaps", [])
        difficulty = diagnosis_result.get("recommended_difficulty", "beginner")
        learning_style = diagnosis_result.get("learning_style", "unknown")
        learning_goal = diagnosis_result.get("summary", "")

        # schemas.GeneratedResource.target_skill_gaps：本次生成覆盖的盲区知识点
        target_skill_gaps = [g.get("topic", "") for g in gaps if g.get("topic")]

        # Phase 2b接入：此处将接入 RAG 知识库检索（retrieved_chunks），
        # 用 KB 原文约束生成 + 溯源标注。MVP 阶段只用 LLM 自身知识，不做 RAG 检索。

        resources: list[dict] = []
        for rtype in resource_types[: self.MAX_RESOURCES]:
            prompt = self._build_prompt(
                gaps=gaps,
                difficulty=difficulty,
                learning_style=learning_style,
                learning_goal=learning_goal,
                rtype=rtype,
            )
            result = await self.call_llm_json(prompt)
            if not result or result.get("_parse_error"):
                self.log(f"⚠️ {rtype} 类型资源生成解析失败，跳过")
                continue
            resources.append(
                self._build_resource(rtype, difficulty, result, target_skill_gaps, learner_id)
            )

        return resources

    def _build_prompt(
        self,
        gaps: list[dict],
        difficulty: str,
        learning_style: str,
        learning_goal: str,
        rtype: str,
    ) -> str:
        """构建单类型资源的生成 prompt。"""
        return f"""## 学习者画像
- 学习目标总结：{learning_goal}
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}
- 推荐难度：{difficulty}
- 学习风格：{learning_style}

## 生成任务
请用你的专业知识，生成一份 {rtype} 类型的个性化学习资源。

## 输出 JSON
{{
    "title": "资源标题（要具体、有吸引力）",
    "content": "Markdown 格式的完整内容（含代码示例和命令行时用 `````` 标注语言类型）",
    "difficulty_level": "{difficulty}",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["学完你能掌握什么1", "学完你能掌握什么2", "学完你能掌握什么3"]
}}

## 硬性要求
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

    def _build_resource(
        self,
        rtype: str,
        recommended_difficulty: str,
        result: dict,
        target_skill_gaps: list[str] | None = None,
        learner_id: str = "",
    ) -> dict:
        """把 LLM 返回的结果规整为 schemas.GeneratedResource 对齐的字段结构。

        字段名与 schemas.py 的 GeneratedResource 严格一致：
        resource_id / learner_id / resource_type / title / content /
        citations / difficulty_level / target_skill_gaps /
        estimated_duration_minutes / prerequisites / key_takeaways。
        """
        return {
            "resource_id": str(uuid.uuid4()),
            "learner_id": learner_id,
            "resource_type": rtype,
            "title": result.get("title", f"{rtype} 学习资源"),
            "content": result.get("content", ""),
            # MVP 阶段无 RAG 溯源，citations 为空数组
            # （schemas 注释：空数组 = 疑似未约束生成，Agent 3 将标记为 critical）
            "citations": result.get("citations", []),
            "difficulty_level": (
                result.get("difficulty_level")
                or result.get("difficulty")  # 兼容旧字段名
                or recommended_difficulty
            ),
            "target_skill_gaps": target_skill_gaps or [],
            "estimated_duration_minutes": result.get("estimated_duration_minutes", 30),
            "prerequisites": result.get("prerequisites", []),
            "key_takeaways": result.get("key_takeaways", []),
        }

    def _fmt_gaps(self, gaps: list[dict]) -> str:
        """格式化知识盲区列表为可读文本，最多展示前 5 条。"""
        if not gaps:
            return "学习者未提供具体知识盲区，请根据学习目标生成通用的入门内容"

        lines = []
        for g in gaps[:5]:
            priority = g.get("priority", "?")
            topic = g.get("topic", "未知")
            reason = g.get("reason", "")

            # float() 类型保护：LLM JSON 中的数值可能是 int/float/str
            try:
                curr_lv = float(g.get("current_level", 0.0))
            except (ValueError, TypeError):
                curr_lv = 0.0
            try:
                target_lv = float(g.get("target_level", 1.0))
            except (ValueError, TypeError):
                target_lv = 1.0

            lines.append(
                f"- [{priority}] {topic} (当前 {curr_lv:.1f} → 目标 {target_lv:.1f}): {reason}"
            )

        return "\n".join(lines)

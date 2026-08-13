"""
Agent 2: 领域知识生成 Agent（融合版）
══════════════════════════════════
负责: 角色5 实现

MVP 版本: 直接用 LLM 自身知识生成内容（不依赖外部知识库）
Phase 2 版本: 接入 RAG 知识库，约束生成 + 溯源

输入: state["diagnosis_result"] + state["resource_types"]
输出: state["generated_resources"] (list of GeneratedResource)

融合改进点:
  - Untitled-1.py: 资源数量上限、结构化内容模板、更清晰的 _fmt_gaps
  - 原 generation.py: prompt 代码块转义、项目代码风格
  - 新增: 循环容错（部分成功）、float() 类型保护、OPTIONAL_STATE_KEYS 补全
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
    """领域知识生成 Agent — 角色5 在此实现

    根据学情诊断结果（diagnosis_result），为每种请求的资源类型
    （lecture / guide / quiz）生成一份个性化学习资源。

    资源数量上限为 3，防止单次请求过度消耗 token。
    单个资源生成失败不影响其他资源（部分成功）。
    """

    REQUIRED_STATE_KEYS = {"diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "learner_data",
        "resource_types",
        "retrieved_chunks",  # Phase 2 RAG 知识库检索结果，MVP 阶段可选
        "task_id",
        "agent_log",
        "status",
    }

    # 资源数量上限，防止 token 过度消耗
    MAX_RESOURCES = 3

    def __init__(self):
        super().__init__(
            name="知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    async def process(self, state: dict) -> dict:
        """生成个性化学习资源。

        对每种请求的资源类型分别调用 LLM 生成一份资源。
        单个资源生成失败时记录错误但不阻断其他资源的生成（部分成功）。
        """
        diagnosis = state.get("diagnosis_result", {})
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])
        retrieved_chunks = state.get("retrieved_chunks", [])

        # 安全上限：防止请求过多类型导致 token 爆炸
        resource_types = resource_types[: self.MAX_RESOURCES]

        resources = []
        errors = []
        learner_id = state.get("learner_id", "")
        # 本次生成覆盖的盲区知识点（与 schemas.GeneratedResource.target_skill_gaps 对齐）
        target_skill_gaps = [
            g.get("topic", "") for g in diagnosis.get("skill_gaps", []) if g.get("topic")
        ]
        for rtype in resource_types:
            try:
                result = await self._generate_one(diagnosis, rtype, retrieved_chunks)
                # 解析失败（_parse_error）或空内容同样按失败处理，不当作资源
                if not result or result.get("_parse_error"):
                    self.log(f"⚠️ {rtype} 类型资源生成解析失败，跳过")
                    errors.append({"resource_type": rtype, "error": "json_parse_failed"})
                    continue
                # 与 schemas.GeneratedResource 对齐：resource_id / learner_id /
                # resource_type 由本层补全，target_skill_gaps 从诊断结果推导
                result["resource_type"] = rtype
                result["resource_id"] = str(uuid.uuid4())
                result["learner_id"] = learner_id
                result.setdefault("target_skill_gaps", target_skill_gaps)
                resources.append(result)
            except Exception as e:
                # 单个资源生成失败不阻断其他资源
                self.log(f"⚠️ {rtype} 类型资源生成失败: {e}")
                errors.append({"resource_type": rtype, "error": str(e)})

        self.log(
            f"生成完成: {len(resources)}/{len(resource_types)} 个资源"
            + (f"，{len(errors)} 个失败" if errors else "")
        )
        return {
            "generated_resources": resources,
            **({"generation_errors": errors} if errors else {}),
        }

    async def _generate_one(
        self, diagnosis: dict, rtype: str, retrieved_chunks: list | None = None
    ) -> dict:
        """为单一资源类型生成内容。

        Args:
            diagnosis:        诊断结果 dict，含 skill_gaps / recommended_difficulty
                              / learning_style / summary
            rtype:            资源类型字符串（lecture / guide / quiz）
            retrieved_chunks: RAG 知识库检索结果列表

        Returns:
            LLM 返回的 dict；LLM 解析失败时返回 {}（由调用方过滤）。
        """
        gaps = diagnosis.get("skill_gaps", [])
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "unknown")
        learning_goal = diagnosis.get("summary", "")

        # ── 构建知识库上下文（RAG 约束生成）──
        kb_context = self._fmt_knowledge_base(retrieved_chunks or [])

        prompt = f"""## 学习者画像
- 学习目标总结：{learning_goal}
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}
- 推荐难度：{difficulty}
- 学习风格：{learning_style}

{kb_context}

## 生成任务
请**严格基于上述知识库参考资料**，生成一份 {rtype} 类型的个性化学习资源。

## 输出 JSON
{{
    "title": "资源标题（要具体、有吸引力）",
    "content": "Markdown 格式的完整内容（含代码示例和命令行时用 `````` 标注语言类型）",
    "citations": [
        {{"ref_index": 1, "original_text": "引用的原文片段", "usage": "在内容中的用途说明"}}
    ],
    "difficulty_level": "{difficulty}",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["学完你能掌握什么1", "学完你能掌握什么2", "学完你能掌握什么3"]
}}

## 硬性要求
1. 内容必须准确——这是教育场景，教错了比不教更糟
2. **内容必须基于上方知识库参考资料**，不得编造知识库中没有的技术细节
3. 代码示例完整可运行，命令行标注操作系统（Windows/Linux/Mac）
4. 难度匹配 {difficulty} 水平：
   - beginner: 多用生活类比，每行代码加注释
   - intermediate: 适当减少注释，引入进阶概念
   - advanced: 精简解释，给高质量代码和架构思考
5. 学习风格为 {learning_style}：
   - practice_first: 先给代码再解释原理
   - theory_first: 先讲清楚为什么再给代码
6. 三种资源固定内容结构：
   - lecture: 引言 → 3~4小节（概念+可运行代码）→ 总结
   - guide: 概述 → 前置准备 → 分步操作（命令+代码+预期输出）→ 常见问题
   - quiz: 基础选择题2道（含选项/标准答案/解析）→ 进阶题1道 → 挑战实操题1道
7. 优先覆盖 critical 和 high 优先级的知识盲区
8. citations 中至少引用 2 条知识库原文片段"""

        return await self.call_llm_json(prompt)

    def _fmt_gaps(self, gaps: list) -> str:
        """格式化知识盲区列表为可读文本，最多展示前 5 条。

        对数值字段做 float() 保护，防止 LLM 返回字符串类型
        导致 .1f 格式化报 TypeError。
        """
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

    @staticmethod
    def _fmt_knowledge_base(chunks: list) -> str:
        """将 RAG 检索到的知识库 chunks 格式化为 LLM prompt 中的参考资料。

        取前 6 条最相关的 chunk，去重（按 doc_title），
        每条截取前 500 字符防止 prompt 过长。
        """
        if not chunks:
            return "## 知识库参考资料\n（无可用知识库资料，请基于你的专业知识生成内容）"

        seen_titles: set[str] = set()
        unique_chunks: list[dict] = []
        for c in chunks:
            title = c.get("doc_title", "")
            if title not in seen_titles:
                seen_titles.add(title)
                unique_chunks.append(c)
            if len(unique_chunks) >= 6:
                break

        parts = ["## 知识库参考资料（以下是系统检索到的权威文档，请严格基于这些资料生成内容）"]
        for i, c in enumerate(unique_chunks, 1):
            title = c.get("doc_title", "未知文档")
            content = c.get("content", "")
            # 截取关键部分，防止 prompt 过长
            excerpt = content[:500] + ("…" if len(content) > 500 else "")
            parts.append(f"\n### 资料 {i}：{title}\n{excerpt}")

        return "\n".join(parts)

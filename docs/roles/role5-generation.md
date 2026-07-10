# CLAUDE.md — 角色5：知识生成 Agent

## 你的模块

`backend/src/agents/generation.py` — Agent 2：领域知识生成

## 你要做的事情

1. 完善 `GenerationAgent.process()` 的 RAG + 约束生成 prompt
2. 基于检索的 KB chunks 生成个性化资源（不能编造）
3. 实现多种资源类型：lecture / guide / quiz
4. 实现内容难度校准（根据 learner difficulty 调整表达深度）
5. 实现学习风格适配（theory_first → 先讲原理再举例；practice_first → 先看代码再解释）

## 你的接口

- 继承 `BaseAgent`
- 输入: `state["diagnosis_result"]` + `state["retrieved_chunks"]` + `state["resource_types"]`
- 输出: `state["generated_resources"]`

## 输出格式

每条资源:
```json
{
    "resource_id": "uuid",
    "resource_type": "lecture|guide|quiz",
    "title": "标题",
    "content": "Markdown 格式",
    "citations": [
        {
            "ref_index": 1,
            "original_text": "从 KB 逐字引用的原文",
            "usage": "在正文中的位置"
        }
    ],
    "difficulty_level": "beginner|intermediate|advanced",
    "target_skill_gaps": ["目标知识点"],
    "estimated_duration_minutes": 30,
    "prerequisites": ["前置知识点"]
}
```

## ⚠️ 最重要约束
- **citations 数组不能为空！** 空数组会被 Agent 3 标记为 critical 级幻觉
- 内容中的每条专业断言用 `[ref:N]` 标注对应的 citation
- 你不能编造不在 KB 中的"专业事实"
- 如果 KB 没有覆盖某个知识点，诚实标注"通用知识参考"

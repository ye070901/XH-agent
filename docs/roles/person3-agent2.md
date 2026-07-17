# 人3：Agent 2 — 知识生成

## 你要做什么

文件：`agents/generation.py`

继承人1 的 `BaseAgent`。拿人2 的诊断结果，用 LLM 自身知识生成个性化学习资源。

## 输入

`state["diagnosis_result"]` + `state["resource_types"]`

## 输出

`state["generated_resources"]` — 最多 3 份

```python
[
    {
        "resource_type": "lecture",
        "title": "LangGraph 入门讲义",
        "content": "## 1. 什么是 LangGraph\n\n...",   # Markdown
        "difficulty_level": "beginner",
        "estimated_duration_minutes": 30,
        "key_takeaways": ["要点1", "要点2"]
    },
    { "resource_type": "guide", ... },
    { "resource_type": "quiz", ... }
]
```

## 三种资源的 content 结构

| 类型 | 结构 |
|------|------|
| lecture | 引言 → 3-4 小节（概念 + 代码示例）→ 总结 |
| guide | 概述 → 前置准备 → 步骤1/2/3（命令 + 代码 + 预期输出）→ 常见问题 |
| quiz | 基础题2道（选择题 + 选项 + 答案✓ + 解析）→ 进阶题1道 → 挑战题1道 |

## 个性化怎么体现

- beginner：多注释、多比喻、不假设前置知识
- advanced：精简解释、给代码和架构思考
- practice_first：先代码再解释。theory_first：先原理再代码
- critical 和 high 盲区优先覆盖

## 你怎么测

- 同份诊断 × 三种类型 → 每种结构明显不同
- 换一份诊断 → 内容跟着变
- resource_types 只选一种 → 只生成一种

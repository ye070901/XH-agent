# 人4：Agent 4 — 保真修正

## 你要做什么

文件：`agents/correction.py`（主实现）+ `agents/agent4.py`（别名入口）

继承人1 的 `BaseAgent`。拿 Agent 2 生成的原始资源 + Agent 3 的审核报告 + RAG 知识库素材，逐条修正事实错误，输出合规准确的个性化学习资源。

Agent 4 与 Agent 2 由同一开发者编写，保证生成 prompt 和修正 prompt 的风格一致。

## 输入

| 字段 | 来源 | 说明 |
|------|------|------|
| `state["diagnosis_result"]` | Agent 1 | 学情诊断（skill_gaps / recommended_difficulty / learning_style） |
| `state["generated_resources"]` | Agent 2 | 原始学习资源列表 |
| `state["audit_result"]` | Agent 3 | 每份资源的审核报告（verdict / issues / fact_check） |
| `state["retrieved_chunks"]` | RAG 知识库 | 检索素材（doc_id / content / relevance_score），可选 |

## 输出

```python
{
    "corrected_resources": [
        {
            "resource_id": "uuid",
            "resource_type": "lecture",
            "title": "修正后的标题",
            "content": "修正后的 Markdown 完整内容",
            "difficulty_level": "beginner",
            "citations": [{"doc_id": "...", "chunk_index": 0, "original_text": "...", "relevance_score": 0.95}],
            "key_takeaways": ["要点1", "要点2", "要点3"],
            "_was_corrected": True,                     # 是否有任何修正
            "_correction_summary": "一句话概括修正内容"
        }
    ],
    "correction_log": [
        {
            "resource_id": "uuid",
            "resource_type": "lecture",
            "issue_index": 0,
            "severity": "error",
            "original_text": "修正前的错误文本片段",
            "corrected_text": "修正后的正确文本片段",
            "correction_basis": "knowledge_base",       # knowledge_base | consistency_check | difficulty_adjust
            "kb_source": "doc_rag.md @ chunk_3",        # 仅 knowledge_base 时有
            "action": "replaced"                        # replaced | adjusted | accepted | skipped | failed
        }
    ],
    "correction_stats": {
        "total_resources": 3,
        "resources_corrected": 2,
        "total_issues": 5,
        "errors_fixed": 3,
        "warnings_addressed": 1,
        "infos_applied": 1,
        "correction_time_ms": 4200
    }
}
```

## 修正策略矩阵

| severity | 策略 | 操作 |
|----------|------|------|
| **error** | 必须改 | 查 KB 原文替换错误断言，FactCheckItem `is_accurate=False` 自动提升为 error |
| **warning** | 尽量改 | 调整解释深度对齐难度、补充遗漏的 critical 盲区 |
| **info** | 可选改 | 不影响准确性的改进建议采纳，会引入新断言的跳过 |

## 关键约束

1. **只改有问题的部分** — 不重写整个资源，保留正确的段落/代码/示例
2. **KB 是真理基准** — 事实修正必须以 KB 原文为准，修改后重新标注 `[来源: {doc_id}]`
3. **KB 冲突并列** — 同主题 KB 中存在多个说法时 "说法A / 说法B" 并列，不自动选边
4. **不引入新事实断言** — 修正后额外检查是否有 KB 未覆盖的新技术声明，有则删除或标注 `[暂无权威参考]`
5. **降级模式** — `downgrade_mode=True` 且 KB 覆盖不足时，只做一致性修正（概念矛盾、API 不一致），禁止做事实判断

## 三种资源的 content 结构保持不变

| 类型 | 结构 |
|------|------|
| lecture | 引言 → 3-4 小节（概念 + 代码示例）→ 总结 |
| guide | 概述 → 前置准备 → 步骤1/2/3（命令 + 代码 + 预期输出）→ 常见问题 |
| quiz | 基础题2道（选择题 + 选项 + 答案✓ + 解析）→ 进阶题1道 → 挑战题1道 |

## 执行时序

```
Agent 1 诊断 ──► Agent 2 生成 ──► Agent 3 审核 ──► Agent 4 修正
                                                        │
                                          RAG 知识库 ───┘
```

Agent 4 必须等待 Agent 2 生成完成 **且** Agent 3 审核完成后才能启动。

## 你怎么测

- 造一份含错误（如 "LangGraph 是 Google 开发的"）的资源 + 对应的 error issue → 修正后错误消失
- 同份资源 × error / warning / info 混合 → 三种级别分别处理，error 全改
- `retrieved_chunks=[]` + `downgrade_mode=True` → 只做一致性修正，不做事实判断
- `audit_result=[]` → 无审核问题时原样返回
- 修正后再跑 Agent 3 → error 数 ≤ 0

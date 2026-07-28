# LangGraph 条件路由

## 什么是条件路由

条件路由是 LangGraph 实现**动态决策**的关键机制。它允许工作流根据当前状态的内容，在运行时选择不同的执行路径。这意味着同一个工作流可以根据不同的输入产生完全不同的执行序列。

## 条件路由的工作原理

条件路由由三个组件组成：

1. **路由函数**：接收当前状态，返回路由键（字符串）
2. **路由映射**：将路由键映射到目标节点名称
3. **条件边**：将上述两者绑定到源节点

```python
def router(state: AgentState) -> str:
    """根据审核结果决定下一步"""
    if state.get("needs_revision"):
        return "revise"
    if state.get("needs_human_review"):
        return "human_check"
    return "publish"

graph.add_conditional_edges(
    "auditor",           # 源节点
    router,              # 路由函数
    {                    # 路由映射
        "revise": "revision_node",
        "human_check": "human_node",
        "publish": "publish_node"
    }
)
```

## 路由函数的设计原则

### 返回值约定
路由函数必须返回**字符串**，该字符串必须是路由映射中的 key。如果返回的 key 不在映射中，LangGraph 会抛出异常。

### 状态只读
路由函数应该只**读取**状态，不修改状态。修改状态是节点的职责，路由函数保持纯粹有助于调试。

### 覆盖所有路径
路由函数必须覆盖所有可能的分支。建议始终包含一个默认分支（如错误处理节点）。

## 实际案例：内容审核工作流

```python
def audit_router(state: AuditState) -> str:
    """根据幻觉检测结果路由"""
    hallucination_rate = state.get("hallucination_rate", 0)
    has_factual_error = state.get("has_factual_error", False)
    review_count = state.get("review_count", 0)

    # 3 轮仍未通过 → 人工介入
    if review_count >= 3:
        return "human_review"

    # 有事实错误 → 返回修改
    if has_factual_error:
        return "revise_content"

    # 幻觉率过高 → 加强 RAG 约束后重试
    if hallucination_rate > 0.05:
        return "enhance_rag"

    # 全部通过 → 发布
    return "publish"

graph.add_conditional_edges("auditor", audit_router, {
    "revise_content": "content_reviser",
    "enhance_rag": "rag_enhancer",
    "human_review": "human_review_node",
    "publish": "publish_node"
})
```

## 嵌套条件路由

复杂场景下可以多层嵌套条件路由：

```
入口 → 诊断Agent → 判断难度
                    ├─ 初级 → 基础内容生成 → 判断是否需要补充
                    │                        ├─ 需要 → 补充生成
                    │                        └─ 不需要 → 审核
                    └─ 高级 → 进阶内容生成 → 审核
```

## 条件路由 vs 普通边的选择

| 场景 | 推荐方式 |
|------|---------|
| 固定执行顺序 | 普通边 `add_edge` |
| 根据数据动态选择 | 条件边 `add_conditional_edges` |
| 二分选择 | 条件边（只返回两种可能） |
| 多路选择 | 条件边（返回多种可能，各有映射） |

## 调试条件路由

在路由函数中加入日志，追踪每次路由决策：

```python
def router(state: dict) -> str:
    decision = "continue"
    if state.get("error"):
        decision = "error_handler"
    logger.info(f"[路由] 当前状态: error={state.get('error')}, 决策: {decision}")
    return decision
```

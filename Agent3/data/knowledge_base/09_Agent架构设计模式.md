# Agent 架构设计模式

## 什么是 Agent 架构

Agent 架构是指将复杂的 AI 系统分解为多个独立 Agent 的设计方法。每个 Agent 专注于一个特定的职责，Agent 之间通过定义好的接口进行通信和协作。

## 核心理念：关注点分离

关注点分离（Separation of Concerns）是多 Agent 架构的核心理念。以学习资源生成系统为例：

- **Agent 1（诊断 Agent）**：分析学习者当前水平，识别知识盲区
- **Agent 2（生成 Agent）**：基于诊断结果和知识库生成个性化学习资源
- **Agent 3（审核 Agent）**：检查生成内容的事实准确性、难度匹配度

每个 Agent 只做一件事，做到最好。这比一个超大 prompt 完成所有任务更可靠、更可控。

## 常见架构模式

### 1. 流水线模式（Pipeline）
Agent 按固定顺序执行，每个 Agent 的输出是下一个 Agent 的输入。

```
输入 → Agent 1 → Agent 2 → Agent 3 → 输出
```

**适用场景**：步骤之间有明确的依赖关系，如先诊断后生成。

**优点**：简单、可预测、易于调试。
**缺点**：不支持并行，一个 Agent 出错可能阻塞整个流程。

### 2. 辩论模式（Debate）
两个或多个 Agent 从不同角度审视同一个问题，通过多轮辩论达成共识。

```
Agent 质疑方 ⇄ Agent 应诉方 → 裁决 → 结论
```

**适用场景**：需要保证输出质量的关键决策，如事实核查。

**优点**：可通过对抗发现隐藏的错误，输出质量高。
**缺点**：执行时间长，需要设计裁决逻辑。

### 3. 路由模式（Router）
一个调度 Agent 根据输入内容动态选择执行哪个专业 Agent。

```
输入 → 路由器 → 根据任务类型分发
              ├─ 简单任务 → Agent A
              ├─ 复杂任务 → Agent B
              └─ 特殊任务 → Agent C
```

**适用场景**：任务类型多样，需要不同专业能力。

### 4. 层次模式（Hierarchical）
高级 Agent 制定计划，将子任务分配给低级 Agent 执行，最后汇总结果。

```
管理者 Agent
  ├─ 分配任务 → 执行 Agent 1
  ├─ 分配任务 → 执行 Agent 2
  └─ 汇总      → 结果整合
```

## 状态通信协议

在多 Agent 系统中，Agent 之间通过**共享状态字典**进行通信：

```python
state = {
    "task_id": "task_001",
    "diagnosis_result": {...},    # Agent 1 写入
    "generated_resources": [...], # Agent 2 写入
    "audit_result": [...],       # Agent 3 写入
    "agent_log": [...]           # 所有 Agent 的记录
}
```

## 错误隔离

一个 Agent 的故障不应导致整个系统崩溃。实现方式：
- 每个 Agent 内部 try/except 异常
- 错误信息写入 `state["agent_log"]`
- 编排器检查 `state["status"]` 决定是否继续
- 设置 fallback 策略（如降级到简单模式）

## Agent 设计原则

1. **单一职责**：一个 Agent 只做一件事
2. **无状态计算**：Agent 不保存内部状态，所有状态通过 state dict 传递
3. **确定性的输入输出**：相同输入 → 相同输出（给定相同 temperature）
4. **可观测性**：每个 Agent 记录决策日志
5. **独立可测试**：每个 Agent 可以单独测试，不依赖其他 Agent

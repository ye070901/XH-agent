# 多智能体系统架构设计

多智能体（Multi-Agent）系统是一种让多个 AI Agent 协同工作来完成复杂任务的架构模式。

## 为什么需要多 Agent？

### 单 Agent 的局限

单个 LLM 调用的问题：
- 复杂任务需要多个步骤，prompt 会变得很长
- 不同子任务需要不同的 prompt 策略（分析 vs 生成 vs 审核）
- 逻辑无法分支：不能根据中间结果决定下一步
- 缺乏自检机制：生成的内容没有独立的审核者

### 多 Agent 的核心价值

**关注点分离（Separation of Concerns）：** 每个 Agent 只做一件事，并且做到最好。

```
单体模式：LLM 同时做 [理解用户] + [检索知识] + [生成内容] + [检查错误]
                              ↑ 这些任务有互相矛盾的优化目标 ↑

多Agent模式：
  Agent 1（诊断）：专注"理解学习者"
  Agent 2（生成）：专注"基于知识库生成内容"
  Agent 3（审核）：专注"发现事实性错误"
```

## 常见架构模式

### 1. 顺序流水线（Sequential Pipeline）

```
Agent A → Agent B → Agent C → 最终输出
```

每个 Agent 的输出是下一个的输入。简单但缺乏互动。

### 2. 辩论/对抗模式（Debate / Adversarial）

```
Agent A 生成内容 → Agent B 提出质疑 → Agent A 回应/修正 → Agent B 再审查
    ↑                                                              │
    └──────────────── 最多 N 轮博弈 ←───────────────────────────────┘
```

两个 Agent 通过多轮辩论达成共识。这是最有效的幻觉防控机制。

### 3. 分层决策（Hierarchical）

```
        Supervisor Agent
       /        |        \
   Agent A   Agent B   Agent C
```

一个主管 Agent 负责分配任务和汇总结果。

## Agent 间通信方式

### 共享状态（Shared State）

所有 Agent 通过一个共同的 state 字典通信：

```python
state = {
    "user_query": "...",
    "agent_a_output": {...},
    "agent_b_output": {...},
}
```

优点：简单、可追踪
缺点：所有 Agent 需要约定 state 的键名

### 消息传递（Message Passing）

每个 Agent 向特定目标发送消息：

```python
send_message(
    from="audit_agent",
    to="generation_agent",
    content="请提供第3段断言的证据来源"
)
```

## 实现工具

### LangGraph

LangGraph 是目前最适合实现多 Agent 系统的框架：
- StateGraph：定义 Agent 节点和流程
- 条件路由：根据 Agent 输出决定下一个 Agent
- Checkpointer：状态持久化，支持断点恢复
- 内置支持人在回路（Human-in-the-Loop）

### 关键实现原则

1. **每个 Agent 的温度参数不同：** 诊断用低温（保证一致性），生成用中温（保证创造性），审核用极低温（保证判断一致）
2. **Agent 之间不直接调用：** 通过编排器（orchestrator）调度，降低耦合
3. **每个 Agent 可换不同的模型：** 诊断用快速便宜的模型，审核用最强的模型

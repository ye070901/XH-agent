# 多 Agent 通信协议

## 为什么需要通信协议

在多 Agent 系统中，Agent 之间需要交换信息、协商决策、解决分歧。没有统一的通信协议，每个 Agent 的输出格式不同，编排器难以串联。通信协议定义了 Agent 之间交互的标准化格式。

## 消息格式设计

### 基本消息结构
```json
{
    "from_agent": "审核Agent",
    "to_agent": "生成Agent",
    "message_type": "challenge",
    "round_number": 2,
    "content": {
        "claim": "被质疑的具体断言",
        "evidence": "知识库中反驳该断言的原文",
        "suggested_fix": "建议的修正方案"
    },
    "timestamp": "2026-07-27T16:00:00Z"
}
```

### 消息类型定义

| 类型 | 方向 | 含义 |
|------|------|------|
| `challenge` | 审核方 → 生成方 | 对某一断言提出质疑 |
| `defense` | 生成方 → 审核方 | 回应质疑，提供证据 |
| `accept` | 任意 → 任意 | 接受对方的修改建议 |
| `reject` | 任意 → 任意 | 拒绝对方的修改建议 |
| `delegate` | 编排器 → Agent | 分派任务 |
| `report` | Agent → 编排器 | 汇报执行结果 |

## 辩论协议

辩论是多 Agent 通信中最复杂的场景。标准辩论协议包含：

### 辩论角色
- **质疑方（Challenger）**：Agent 3（审核），负责提出质疑
- **应诉方（Respondent）**：Agent 2（生成），负责回应质疑
- **裁决方（Judge）**：代码规则或 LLM，负责判定胜负

### 辩论回合
每轮辩论包含三个步骤：
1. 质疑方提出 Challenge（指出问题 + 证据）
2. 应诉方做出 Response（concede / rebut / accept_challenge）
3. 裁决方判定（共识 / 继续辩论 / 标记待人工）

### 终止条件
- **concede**：一方承认错误 → 辩论结束
- **consensus_reached**：双方达成共识 → 辩论结束
- **max_rounds（3轮）**：达到最大轮数 → 标记为待人工审核

## 状态同步

所有 Agent 通过共享状态字典通信，避免点对点的复杂依赖：

```python
# 编排器写入
state["current_round"] = 2
state["debate_records"] = [...]
state["pending_claims"] = [...]

# Agent 3 写入质疑
state["pending_claims"].append({
    "claim": "...",
    "challenge": "...",
    "round": 2
})

# Agent 2 读取并回应
claim = state["pending_claims"][-1]
state["pending_claims"][-1]["response"] = "concede"
```

## WebSocket 实时通信

前端可视化需要实时展示 Agent 之间的通信过程：

```python
await websocket.send_json({
    "task_id": task_id,
    "from_agent": "审核Agent",
    "to_agent": "生成Agent",
    "message_type": "challenge",
    "message": "质疑第2个资源中的API名称错误"
})
```

## 通信原则

1. **异步优先**：Agent 间通信不阻塞对方
2. **幂等性**：重复发送同一条消息不应产生副作用
3. **可追溯**：每条消息有唯一 ID 和时间戳
4. **版本兼容**：协议升级应向后兼容

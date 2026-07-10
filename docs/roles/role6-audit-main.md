# CLAUDE.md — 角色6：审核裁判 Agent（主） — 辩论协议

## 你的模块

`backend/src/agents/audit.py` + `backend/src/debate/engine.py`

## 你要做的事情

1. 完善 `AuditAgent` 的事实抽取和对抗验证 prompt
2. 实现 `DebateEngine` 的完整多轮辩论逻辑（**不要降级成 retry！**）
3. 实现 Agent 3 发起质询的逻辑（`generate_challenges`）
4. 实现 Agent 3 评估 Agent 2 辩护的逻辑（`evaluate_defense`）
5. 实现共识判定策略（什么情况算共识？什么情况继续辩？什么情况 escalate？）

## 你的接口

- `AuditAgent.process(state)` → 审核报告
- `DebateEngine.run(resource, audit, chunks, gen_agent, aud_agent)` → 辩论记录

## 辩论协议（你的核心工作）

```
第 N 轮:
  Agent 3 发起质询 (证据: KB 中与断言矛盾的原文)
      ↓
  Agent 2 回应: accept_challenge(修正) / rebut(反驳) / concede(承认)
      ↓
  Agent 3 评估: defense_accepted? remaining_concerns?
      ↓
  共识达成 → 通过
  未共识 → 下一轮（最多3轮）
  3轮未共识 → escalate（标记 unresolved_claims）
```

## 关键约束

- **辩论不是 retry。** 不是"审核不过→重新生成"。是逐条对抗验证。
- 每次质询必须附带 KB 证据（没有证据的质疑是无效的）
- Agent 2 的辩护引用 KB 原文才算有效，只说"我认为..."不算
- 这是评审最关注的技术亮点，做到位 = 25 分创新分稳了

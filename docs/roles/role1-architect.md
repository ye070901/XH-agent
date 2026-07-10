# CLAUDE.md — 角色1：架构师 + LangGraph 调度

## 你的模块

`backend/src/graph/orchestrator.py` — LangGraph 工作流调度

## 你要做的事情

1. 完善 `AgentWorkflow` 的 LangGraph 状态图
2. 实现 3 个 Agent 节点的串联和条件路由
3. 实现辩论回环（review → debate → [plan] → finalize）
4. 实现 WebSocket 推送 Agent 状态变化（用于前端可视化）
5. 负责 dev 分支的 merge 和集成测试
6. 管理团队进度

## 你的接口

- 输入: `task_id, learner_data, resource_types`
- 输出: `WorkflowState` dict（含所有阶段结果）
- Agent 节点调用各 Agent 的 `process(state)` 方法
- 不要修改 Agent 内部的逻辑，只负责调度

## 关键约束

- 所有 Agent 通过 `state` 字典通信，键名见 `docs/INTERFACE_CONTRACT.md`
- 数据模型不要自己定义，统一用 `backend/src/schemas.py`
- LangGraph 不可用时必须 fallback 到顺序执行

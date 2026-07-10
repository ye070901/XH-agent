## 👤 角色8：前端 + 可视化

### 你要搭建的项目

React + TypeScript + Vite

### 三个核心可视化（评分标准 15 分）

1. **Agent 协同拓扑图** — 实时显示 3 个 Agent 的消息流向
2. **知识溯源图** — 每条生成内容的 [ref:N] 点击回溯 KB 原文
3. **学习路径规划图** — 知识状态变化可视化

### 后端 API

- `POST /api/profile` — 创建学习者画像
- `POST /api/generate` — 触发完整工作流
- `GET /api/task/{task_id}` — 查询任务状态（含 Agent 交互日志）
- WebSocket `ws://localhost:8000/ws/{task_id}` — 实时接收 Agent 状态推送

### 数据模型参考

所有请求/响应格式见 `backend/src/schemas.py` 底部的 API 部分。

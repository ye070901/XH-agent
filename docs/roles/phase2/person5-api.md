# 人员5 + 7 — 后端 API + WebSocket

## 角色定位

两人协作负责系统全部对外接口。FastAPI 全部端点、WebSocket 实时推送、前端数据格式适配、人工干预能力。

## 依赖关系

```
被谁依赖：人员6（前端）→ 所有 API 端点和 WebSocket
         全体 → API 是系统唯一对外入口

依赖谁：人员1（编排器）→ 编排器的 run() 是 API 核心调用
        人员4 → KB 管理接口需调 kb.add_document() / kb.delete_document()
```

## 第一阶段：7/27 — 8/2（7天）

### 任务 1.1：API 端点规划 + /api/generate 升级（1.5天）

升级现有端点，新增端点规划：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/generate` | POST | 一键生成（升级，返回增加 debate_record / correction_log / metrics） |
| `/api/validate-goal` | POST | 闸门1：输入特异性检测 |
| `/api/clarify` | POST | 追问对话 |
| `/api/task/{task_id}/status` | GET | 任务状态轮询 |
| `/api/task/{task_id}/history` | GET | 任务全流程回放 |
| `/api/kb/upload` | POST | 知识库文档上传 |
| `/api/kb/list` | GET | 知识库文档列表 |
| `/api/kb/{doc_id}/delete` | DELETE | 删除知识库文档 |
| `/api/config` | GET/PUT | 全局参数查看/修改 |
| `/api/intervention/{task_id}` | POST | 人工干预 |
| `/ws/task/{task_id}` | WebSocket | 实时 Agent 状态推送 |

### 任务 1.2：闸门1 端点 + 追问端点（2天）

`POST /api/validate-goal` → 调人员1 的 `validate_learning_goal()`。`POST /api/clarify` → 将追问答案拼接为精炼学习目标。

### 任务 1.3：WebSocket 端点 + 广播函数（2.5天）

**文件**：`backend/src/api/ws.py`（新建）

```python
class ConnectionManager:
    """管理所有活跃 WebSocket 连接，按 task_id 分组"""
    async def connect(self, websocket, task_id)
    async def disconnect(self, websocket, task_id)
    async def broadcast(self, task_id, message: dict)

# 对外暴露（人员1 编排器调用）
async def broadcast_agent_event(task_id, agent_name, state, message, data=None):
    """编排器在关键节点推送 Agent 状态"""
```

**交付物**：`api/main.py` 升级版 + `api/ws.py` + ConnectionManager

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：任务轮询 + 历史回放端点（2天）

`GET /api/task/{task_id}/status` → 当前进度(progress_percent / current_agent)。`GET /api/task/{task_id}/history` → 完整 agent_log。

### 任务 2.2：知识库管理端点（2天）

对接人员4 的 KnowledgeBase：upload / list / delete。

### 任务 2.3：配置端点 + 人工干预端点（2天）

`GET/PUT /api/config` 在线修改相似度阈值、辩论轮次等。`POST /api/intervention/{task_id}` 支持 reject / supplement_kb / annotate。

### 任务 2.4：接口文档 + 错误码规范（2天）

统一错误码：400(INVALID_PARAM) / 404(NOT_FOUND) / 408(TIMEOUT) / 500(INTERNAL_ERROR) / 503(LLM_UNAVAILABLE)。超时 300s 返回 timeout。部分成功返回 status: "partial" + errors 列表。

## 第三阶段：8/11 — 8/16（6天）

- 8/11-8/12：与人员1 联调编排器调用 + 与人员6 联调前后端接口
- 8/13-8/14：异常处理完善
- 8/15-8/16：文档 + 代码冻结

## 验收标准

- [ ] 所有端点 curl 测试返回正确状态码
- [ ] WebSocket 能建立连接并接收推送
- [ ] `/api/generate` Demo Mode 下 60s 内返回完整结果
- [ ] 人工干预端点能驳回输出和补充 KB
- [ ] 接口文档完整
- [ ] 统一错误码在异常场景下触发正确
- [ ] 部分成功场景返回 status: "partial" + errors 列表

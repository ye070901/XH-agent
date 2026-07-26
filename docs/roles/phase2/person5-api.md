# 人员5+7 — 后端 API + WebSocket

## 角色定位

系统对外接口层。负责 FastAPI 全部端点、WebSocket 实时推送、前端数据格式适配、人工干预能力。人员7 配合完成 API 层开发。

## 依赖关系

```
被谁依赖：人员6（前端）→ 所有 API 端点和 WebSocket
         全体 → API 是系统唯一对外入口

依赖谁：人员1（编排器）→ 编排器的 run() 是 API 的核心调用
        人员4 → KB管理接口需调 kb.add_document() / kb.delete_document()
```

## 第一阶段：7/27 — 8/1（6天）

### 任务 1.1：API 端点规划（1天）

新增端点总览：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/generate` | POST | 一键生成（升级） |
| `/api/validate-goal` | POST | 闸门1：输入特异性检测 |
| `/api/clarify` | POST | 追问对话（用户回复追问后重新提交） |
| `/api/task/{task_id}/status` | GET | 任务状态轮询 |
| `/api/task/{task_id}/history` | GET | 任务全流程回放 |
| `/api/kb/upload` | POST | 知识库文档上传 |
| `/api/kb/list` | GET | 知识库文档列表 |
| `/api/kb/{doc_id}/delete` | DELETE | 删除知识库文档 |
| `/api/config` | GET/PUT | 全局参数查看/修改 |
| `/api/intervention/{task_id}` | POST | 人工干预（驳回/补充KB/标注） |
| `/ws/task/{task_id}` | WebSocket | 实时 Agent 状态推送 |

### 任务 1.2：闸门1 端点 + 追问端点（2天）

`POST /api/validate-goal` → 调人员1的`validate_learning_goal()`。`POST /api/clarify` → 把追问答案拼接为精炼学习目标。

### 任务 1.3：WebSocket 端点 + 广播函数（2天）

**文件**：`backend/src/api/ws.py`（新建）

`ConnectionManager`管理所有活跃WebSocket连接按task_id分组。对外暴露`broadcast_agent_event(task_id, agent_name, state, message, data)`供人员1编排器在关键节点调用。

### 任务 1.4：`/api/generate` 升级（1天）

返回格式增加debate_record/correction_log/metrics。增加超时处理（300s返回timeout）。增加部分成功处理（status: "partial" + errors列表）。

**交付物**：`api/main.py` 升级 + `api/ws.py`

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：任务轮询 + 历史回放端点（2天）

`GET /api/task/{task_id}/status`返回当前状态快照(progress_percent + current_agent)。`GET /api/task/{task_id}/history`返回完整agent_log用于历史回放。

### 任务 2.2：知识库管理端点（2天）

对接人员4的KnowledgeBase：upload文件→`kb.add_document()` / list→`kb.get_stats()` / delete→`kb.delete_document()`。

### 任务 2.3：配置端点 + 人工干预端点（2天）

`GET/PUT /api/config`在线修改相似度阈值、辩论轮次、保真分数线。`POST /api/intervention/{task_id}`支持reject/supplement_kb/annotate三种操作。

### 任务 2.4：接口文档 + 错误码规范（2天）

统一错误码：400(INVALID_PARAM) / 404(NOT_FOUND) / 408(TIMEOUT) / 500(INTERNAL_ERROR) / 503(LLM_UNAVAILABLE)

## 第三阶段：8/10 — 8/19

- 8/10-8/12：与人员1联调编排器调用 + 与人员6联调前后端
- 8/13-8/14：异常处理完善 + 压力测试
- 8/15-8/19：文档 + 代码冻结

## 验收标准

- [ ] 所有端点curl测试返回正确状态码
- [ ] WebSocket能建立连接并接收推送
- [ ] `/api/generate` Demo Mode下60s内返回完整结果
- [ ] 人工干预端点能驳回输出和补充KB
- [ ] 接口文档完整（OpenAPI可访问）
- [ ] 统一错误码在5种异常场景下触发正确
- [ ] 部分成功场景下返回status:"partial"+详细errors列表

# CLAUDE.md — 团队项目总入口

## 项目概述

"挑战杯"揭榜挂帅比赛项目（XH-202630）。构建领域知识个性化生成与多智能体协同决策系统。

## 当前阶段

**Phase 2 深化**（7/27 — 8/20）：多 Agent 博弈协同 + 知识库高保真

4 Agent + 1 博弈引擎 + 3 道闸门 + 6 道防幻觉防线

### 总方案文档

- 完整架构和分工：`docs/PHASE2_PLAN.md`
- 各人具体任务：`docs/roles/phase2/personN-*.md`
- 进度跟踪表：`docs/PROGRESS_TRACKER.md`

## 技术栈

- 后端: Python + FastAPI + ChromaDB
- 前端: React + Vite + TypeScript + TailwindCSS（framer-motion 动画）
- LLM: DeepSeek（可替换为 GLM-5 / MiniMax / OpenAI 兼容 API）
- CI: GitHub Actions

## 项目结构

```
backend/src/agents/        # 4个Agent: diagnosis / generation / audit / correction
backend/src/debate/        # 辩论协议引擎 (Phase 2 新建)
backend/src/evaluation/    # 三项硬指标评估 + 保真打分 (Phase 2 新建)
backend/src/gateways/      # 三道质量闸门 (Phase 2 新建)
backend/src/knowledge/     # ChromaDB 知识库
backend/src/graph/         # 编排器 (Phase 2 升级)
backend/src/llm/           # LLM 抽象层（多模型支持）
backend/src/api/           # FastAPI + WebSocket
backend/src/schemas.py     # 全员统一的数据模型（修改需周知）
frontend/src/             # 前端（React + Vite，组件在 src/）
data/knowledge_base/       # 知识库文档（4领域×8篇）
docs/PHASE2_PLAN.md        # Phase 2 总体方案
docs/roles/phase2/         # 8人详细分工
```

## 知识库领域

大模型应用开发，4 个子领域：
1. RAG 系统设计与实现
2. Prompt Engineering 方法论
3. Agent/多智能体系统开发
4. LLM API 集成与最佳实践

共 32 篇文档，存储于 `data/knowledge_base/`

## 关键指令

1. 所有数据模型在 `backend/src/schemas.py`，禁止在其他文件重复定义
2. 所有人通过 `state` dict 传递数据，键名约定见 `docs/PHASE2_PLAN.md` 第八章
3. 修改接口契约需要全员通知
4. 代码提交前跑 `ruff check . && pytest`

## 底层开发规范

### 1. 全局配置读取规则

**唯一入口**：所有配置通过 `backend/src/config.py` 的 `Settings` 类统一定义。

```python
from backend.src.config import settings  # 唯一允许的导入方式
```

规则：
- **禁止**在任何模块中直接 `os.getenv()` — 所有环境变量读取收敛到 `Settings` 类
- 配置优先级：环境变量 > `.env` 文件 > 类内硬编码默认值
- 新增配置项时**必须同步更新** `.env.example`
- 敏感信息绝不硬编码

### 2. LLM 双模式标准（演示 / 真实调用）

`LLM_API_KEY` 为空 → 演示模式（_demo_response），返回模拟数据
`LLM_API_KEY` 非空 → 真实模式，走 OpenAI 兼容 API

### 3. BaseAgent 父类抽象设计

所有 Agent 继承 `BaseAgent(ABC)`，强制实现 `async def process(self, state: dict) -> dict`

- `name` 用中文（面向团队内部可视化）
- `temperature` 按 Agent 职责设定：诊断 0.2 / 生成 0.5 / 审核 0.1 / 修正 0.2
- `system_prompt` 写在模块顶层常量 `SYSTEM_PROMPT`
- LLM 调用只能通过 `self.call_llm()` 或 `self.call_llm_json()`

### 4. 异常捕获统一规范

分层处理，逐级兜底：
```
LLM 层 → 内置重试 → 最后一次失败抛出
Agent 层 → try/except → 返回 {"error": str(e)}
编排器层 → try/except 隔离 → 单个资源失败不阻断其他
API 层 → 全局兜底 → HTTPException(500)
```

### 5. Phase 2 新增规范

- 知识库检索：统一通过 `knowledge_base.query(query_text, top_k, min_similarity)` 调用
- WebSocket 广播：编排器通过 `broadcast_agent_event(task_id, agent_name, state, message)` 推送
- 闸门逻辑：纯规则/轻量 LLM 判断，不调 Agent
- 辩论引擎：裁决逻辑是代码规则，不调 LLM（避免第二层幻觉）
- 降级模式：`state["downgrade_mode"] = True`，各 Agent 读取此标记处理

### 6. 防幻觉铁律（代码生成约束）

任何新增/修改代码，先过符号溯源；提交前跑 `python scripts/check_hallucination.py`（抓虚构 import / 虚构枚举成员），必须 0 报错，再跑 `scripts/check_contracts.py`（ruff + 模块导入）。

1. **符号先验证后使用**：引用任何函数/字段/枚举值/配置项前，先在源码里 grep 到它的定义再落笔；禁止凭「记忆里见过」直接使用。
2. **禁止脑补**：找不到定义的接口/字段/参数/默认值/业务分支，写 `# TODO(需要X的契约定义)`，不得用内部旧知识补全。
3. **禁止自证循环**：测试里的假数据字段名必须与生产端定义一致；测试断言不得依赖「自己刚推断出来的同一套字段名」当正确性证据。
4. **多文件归并**：同一实体散落多文件时，先归并出唯一权威定义再用；两处冲突取「更靠近实际运行入口」的那份，并注释指出冲突。
5. **数据契约唯一源**：所有 dict 键名/枚举值以 `backend/src/schemas.py` 与各 Agent 的实际 `_build_*` 输出为准，不在测试里另造一套。

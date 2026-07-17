# CLAUDE.md — 团队项目总入口

## 项目概述

"挑战杯"揭榜挂帅比赛项目（XH-202630）。构建领域知识个性化生成与多智能体协同决策系统。

## 技能引用

When brainstorming, read and follow C:/Users/yeye/claude-code-toolkit/skills/brainstorm/SKILL.md.

## 技术栈

- 后端: Python + FastAPI + LangGraph + ChromaDB
- 前端: React + TypeScript + Vite
- LLM: 可替换（OpenAI / Anthropic / DeepSeek / Qwen）
- CI: GitHub Actions

## 项目结构

```
backend/src/agents/     # 3 个 Agent 实现
backend/src/llm/        # LLM 抽象层（多模型支持）
backend/src/knowledge/  # ChromaDB 知识库
backend/src/graph/      # LangGraph 工作流调度
backend/src/debate/     # Agent 2⇄Agent 3 辩论协议
backend/src/evaluation/ # 三项硬指标自动评估
backend/src/api/        # FastAPI 入口
backend/src/schemas.py  # 全员统一的数据模型（修改需周知）
docs/INTERFACE_CONTRACT.md  # 接口契约文档（法律文件）
```

## 关键指令

1. 所有数据模型在 `backend/src/schemas.py`，禁止在其他文件重复定义
2. 所有人通过 state dict 传递数据，键名约定见 `docs/INTERFACE_CONTRACT.md`
3. 修改接口契约需要全员通知
4. 代码提交前跑 `ruff check . && pytest`

## 底层开发规范

### 1. 全局配置读取规则

**唯一入口**：所有配置通过 `backend/src/config.py` 的 `Settings` 类统一定义，模块内通过 `settings` 单例访问。

```python
from backend.src.config import settings  # 唯一允许的导入方式
```

规则：
- **禁止**在任何模块中直接 `os.getenv()` — 所有环境变量读取收敛到 `Settings` 类
- 配置优先级：环境变量 > `.env` 文件 > 类内硬编码默认值
- `Settings` 类的字段全部大写，类型注解必须明确（`str`、`int`、`bool`、`list[str]`）
- 布尔型配置用 `os.getenv("KEY", "true").lower() == "true"` 模式，兼容字符串
- 新增配置项时**必须同步更新** `.env.example`，写清楚默认值和用途注释
- 敏感信息（API Key、Token）绝不硬编码，且已在 `.gitignore` 中排除 `.env`
- 不同 Agent 可用不同模型：通过 `LLM_MODEL_<AGENT_NAME>` 环境变量覆盖，为空则回退到 `LLM_MODEL`

### 2. LLM 双模式标准（演示 / 真实调用）

`backend/src/llm/client.py` 的 `LLMClient` 实现自动模式切换：

```
LLM_API_KEY 是否为空？
  ├─ 空 → 演示模式（_demo_response），返回模拟数据
  └─ 非空 → 真实模式，走 OpenAI 兼容 API
```

演示模式规范：
- **结构完整性**：模拟数据必须与真实 API 返回的 JSON schema 严格一致，字段一个不能少
- **场景分派**：通过 `system_prompt` 关键词匹配（如 `"学情诊断"` → 诊断模拟数据），不可遗漏场景
- **中文支持**：所有 `json.dumps()` 调用必须带 `ensure_ascii=False`
- **兜底**：无法匹配的场景返回 `{"message": "演示模式 — 无 LLM API Key"}`，不可抛异常
- 新增 Agent 时，**必须同步**在 `_demo_response()` 中添加对应场景的模拟数据

真实模式规范：
- API 调用统一走 `_get_client()` 的缓存客户端，按 `provider:base_url` 去重
- 重试次数默认 2（可配置），最后一次失败必须抛出异常（上层处理）
- `call_json()` 需兼容 ````` 包裹的 JSON 字符串，先 strip 再 parse
- JSON 解析失败 → 返回 `{}` + 记录 warning 日志，不抛异常

### 3. BaseAgent 父类抽象设计

`backend/src/agents/base.py` 的 `BaseAgent(ABC)` 是所有 Agent 的唯一父类。

必须遵守的契约：
- 子类**强制实现** `async def process(self, state: dict) -> dict`
- `state` 是 LangGraph 全局状态字典，输入输出的键名**必须**与 `WorkflowState` / `schemas.py` 中的字段一致
- LLM 调用**只能**通过 `self.call_llm()`（返回字符串）或 `self.call_llm_json()`（返回 dict）
- 日志**只能**通过 `self.log()`，它会自动带上 `[Agent名称]` 前缀
- `__init__` 必须调用 `super().__init__(name=..., system_prompt=..., temperature=...)`

设计约束：
- `BaseAgent` 不持有任何业务逻辑，只提供 LLM 调用 + 日志的工具方法
- `name` 用于日志标识，必须用中文（面向团队内部可视化）
- `temperature` 根据 Agent 职责设定：诊断/审核用低温（0.1-0.2），生成用中温（0.3-0.5）
- `system_prompt` 写在 Agent 模块文件的顶层常量 `SYSTEM_PROMPT`，不内联在类体中
- 子类需要的私有辅助方法（如 `_build_prompt`、`_fmt_gaps`）以下划线开头

### 4. 异常捕获统一规范

**分层处理，逐级兜底**：

```
LLM 调用层 (client.py)
  └─ 内置重试 → 最后一次失败抛出原始异常

Agent 层 (agents/*.py)
  └─ process() 内捕获异常 → 写入 state 错误标记返回，不崩溃

工作流层 (graph/orchestrator.py)
  └─ 每一步调 Agent 时捕获异常 → 记录日志 → 设置 state["status"] = "error"

API 层 (api/main.py)
  └─ 全局兜底 → HTTPException(500)
```

具体规则：
- **LLM 层**：`call()` 方法的 `max_retries` 参数控制重试，每次重试间隔由 SDK 处理。最后一次失败**必须 raise**（不吞异常），让上层决定降级策略
- **Agent 层**：`process()` 必须用 try/except 包裹主逻辑。异常时返回 `{"error": str(e), "status": "error"}` 而非让异常向上传播。这保证一个 Agent 挂了不影响工作流诊断
- **工作流层**：顺序执行的 Agent 间用 try/except 隔离，一个 Agent 失败不应阻止后续 Agent（如果业务允许）。失败信息写入 `state["agent_log"]`，`status` 字段标记 `"error"`
- **API 层**：`main.py` 已有的 try/except → `HTTPException(500)` 作为最后兜底。生产环境需区分 `HTTPException(4xx)` 和 `Exception(5xx)`
- **自定义异常**：如需定义项目级异常，统一放在 `backend/src/exceptions.py`，继承 `Exception`，命名以 `XH` 前缀（如 `XHConfigError`、`XHLLMTimeout`）

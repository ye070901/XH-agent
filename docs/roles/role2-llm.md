# CLAUDE.md — 角色2：LLM 抽象层 + 后端基础设施

## 你的模块

`backend/src/llm/client.py` — 多模型统一调用接口

## 你要做的事情

1. 完善 `LLMClient`，支持多 provider 的真正调用
2. 实现超时、重试、速率限制
3. 实现 `call_json` 的健壮 JSON 解析（处理各种 LLM 输出格式）
4. 支持不同 Agent 用不同模型（`call_diagnosis` / `call_generation` / `call_audit`）
5. 负责 Docker 部署配置
6. 管理 `.env.example` 和环境变量文档

## 你的接口

- `llm.call(system_prompt, user_message, **kwargs) -> str`
- `llm.call_json(...) -> dict`
- `llm.call_diagnosis(...)` / `llm.call_generation(...)` / `llm.call_audit(...)`

## 支持的 provider

- OpenAI (GPT-4o, GPT-4o-mini)
- Anthropic (Claude Opus, Sonnet, Haiku)
- DeepSeek
- 任何 OpenAI 兼容 API（本地模型/vLLM/Ollama）

## 关键约束

- 不暴露具体 provider 的细节给 Agent 层
- 用户换模型 = 改 `.env` 里的 `LLM_PROVIDER` 和 `LLM_MODEL`
- 你不需要改 Agent 代码

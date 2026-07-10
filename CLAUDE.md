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

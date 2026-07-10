# 领域知识个性化生成与多智能体协同决策系统

题目编号：XH-202630 | 发榜单位：上海云之脑智能科技有限公司

---

## 📁 项目结构 + 人员分工

```
XH-agent/
│
├── README.md                           # 本文件
├── CLAUDE.md                           # 团队总配置（AI 协作入口）
├── .env.example                        # 环境变量模板（复制为 .env 后填写 API Key）
├── .gitignore
│
├── docs/
│   ├── INTERFACE_CONTRACT.md           # ⭐ 接口契约文档 — 8个人的法律文件
│   └── roles/
│       ├── role1-architect.md          # 👤 角色1：架构师 → backend/src/graph/
│       ├── role2-llm.md               # 👤 角色2：LLM抽象层 → backend/src/llm/
│       ├── role3-knowledge.md         # 👤 角色3：知识库 → backend/src/knowledge/
│       ├── role4-diagnosis.md         # 👤 角色4：学情诊断Agent → backend/src/agents/diagnosis.py
│       ├── role5-generation.md        # 👤 角色5：知识生成Agent → backend/src/agents/generation.py
│       ├── role6-audit-main.md        # 👤 角色6：审核裁判(辩论协议) → backend/src/agents/audit.py + debate/
│       ├── role7-audit-sub-eval.md    # 👤 角色7：事实抽取+评估 → backend/src/evaluation/
│       └── role8-frontend.md          # 👤 角色8：前端可视化 → frontend/
│
├── scripts/
│   └── check_contracts.py             # CI自动检查：所有人是否遵守接口契约
│
├── .github/workflows/
│   └── ci.yml                         # GitHub Actions：PR 时自动跑 lint + test + contract check
│
├── backend/
│   ├── pyproject.toml                 # Python 项目配置 + 依赖
│   └── src/
│       ├── schemas.py                 # ⭐ 全员统一数据模型（修改需周知所有人）
│       ├── config.py                  # 系统配置（从 .env 读取）
│       │
│       ├── llm/                       # 👤 角色2：LLM抽象层（一行换模型）
│       │   └── client.py              #    支持 OpenAI/Anthropic/DeepSeek/任意兼容API
│       │
│       ├── knowledge/                 # 👤 角色3：知识库（ChromaDB 零配置）
│       │   └── store.py               #    文档分块 + Embedding + 向量检索
│       │
│       ├── agents/                    # 3 个 Agent（不是5个，每个做深不做多）
│       │   ├── base.py                #    Agent 基类 + LLM 调用封装
│       │   ├── diagnosis.py           # 👤 角色4：学情诊断Agent（细粒度知识缺口图谱）
│       │   ├── generation.py          # 👤 角色5：知识生成Agent（KB约束+RAG生成）
│       │   └── audit.py               # 👤 角色6+7：审核裁判Agent（对抗验证+辩论）
│       │
│       ├── debate/                    # 👤 角色6：辩论协议引擎
│       │   └── engine.py              #    Agent 2⇄Agent 3 多轮对抗验证（最多3轮）
│       │
│       ├── graph/                     # 👤 角色1：LangGraph工作流调度
│       │   └── orchestrator.py        #    诊断→检索→生成→审核→[辩论]→完成
│       │
│       ├── evaluation/                # 👤 角色7：三项硬指标自动评估
│       │   └── metrics.py             #    幻觉率<5% / 适配率≥85% / 覆盖率≥90%
│       │
│       └── api/                       # 后端入口
│           └── main.py                #    FastAPI + REST + WebSocket
│
├── backend/tests/                     # 单元测试
│   └── test_contracts.py              #    每人写完代码后跑这个验证接口
│
├── frontend/                          # 👤 角色8：React前端+可视化
│   └── (待角色8初始化)
│
└── data/
    └── knowledge_base/                # 👤 角色3：放知识库原始文档
```

---

## 🚀 快速启动

```bash
# 1. 安装后端依赖
cd backend
pip install -e ".[dev]"

# 2. 配置 API Key
cp ../.env.example ../.env
# 编辑 .env，填写 LLM_API_KEY

# 3. 启动后端
cd backend
python -m uvicorn src.api.main:app --reload --port 8000

# 4. 验证
curl http://localhost:8000/health
```

---

## 🤝 8 个人如何并行工作

### Step 1: 每人认领自己的角色
阅读 `docs/roles/roleN-*.md`，找到自己负责的文件。

### Step 2: 创建自己的分支
```bash
git checkout -b feature/agent-diagnosis   # 角色4
git checkout -b feature/agent-generation  # 角色5
# ... 以此类推
```

### Step 3: 在自己的分支上开发
- 用 AI 辅助写代码
- 只修改自己负责的文件
- **不要改** `schemas.py` 和 `base.py`（除非全员同意）

### Step 4: 本地验证
```bash
cd backend
ruff check src/                          # 代码风格检查
python scripts/check_contracts.py        # 契约检查
python -m pytest tests/ -v               # 单元测试
```

### Step 5: 提交 PR
```bash
git add .
git commit -m "角色4: 完成学情诊断Agent"
git push origin feature/agent-diagnosis
# 在 GitHub 上开 PR → dev 分支
```

### Step 6: 角色1 负责合并
架构师 review PR，确认接口契约没有违反，合并到 `dev`。

---

## ✅ 合并前检查清单

- [ ] `ruff check .` 没有报错
- [ ] `python scripts/check_contracts.py` 通过
- [ ] `pytest tests/` 通过
- [ ] 没有修改别人的文件
- [ ] 没有在 schemas.py 里添加字段（除非讨论过）
- [ ] `process()` 方法是 `async def`

---

## 🔑 关键约束

| 规则 | 原因 |
|------|------|
| 所有人通过 `state` dict 传数据 | 统一接口，LangGraph 需要 |
| 数据模型统一用 `schemas.py` | 避免重复定义导致不一致 |
| Agent 必须继承 `BaseAgent` | 统一 LLM 调用和日志 |
| 修改接口契约需要全员周知 | 否则合并时一定冲突 |
| 不直接 push 到 main/dev | 用 PR 流程 |

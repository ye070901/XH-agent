# MVP 分工安排

> **目标：** 只做 Agent 1（学情诊断）+ Agent 2（知识生成），前后端能跑通，能生成资源。
> **不做：** Agent 3（审核裁判）、辩论协议、三项指标评估。
> **时间：** 7/16–7/28（Phase 1 期间同步完成 MVP）

---

## 一、MVP 简化架构

```
完整版（Phase 2 目标）:            MVP 版（Phase 1 目标）:
                                  ┌──────────┐
                                  │ 知识库(KB) │
                                  │ 4篇MD文件  │
                                  └─────┬─────┘
                                        │ 关键词检索
┌──────────┐  学情画像  ┌──────────┐    ▼         ┌──────────┐
│ 学情诊断  │──────────▶│ 知识生成  │              │ 审核裁判  │
│  Agent   │           │  Agent   │              │  Agent   │
└──────────┘           └──────────┘              └──────────┘
     ✅                     ✅                       ❌ 不做
```

## 二、MVP 需要改的文件

| # | 文件 | 当前状态 | MVP 要做什么 | 负责角色 | 工作量 |
|---|------|---------|-------------|---------|--------|
| 1 | `backend/src/graph/orchestrator.py` | 完整版（3 Agent + 辩论） | **删除 Agent 3 相关代码**，只保留 diagnose → retrieve → generate 三步 | 角色1 | 30min |
| 2 | `backend/src/api/main.py` | 用了 `final_resources`（辩论后才有的字段） | **改成直接用 `generated_resources`**，再加一个简单的 `/api/generate` 接口 | 角色1 | 30min |
| 3 | `backend/src/knowledge/store.py` | 依赖 ChromaDB（需要embedding） | **加一个文件检索回退模式**：ChromaDB 不可用时，直接读 `data/knowledge_base/*.md` 文件做关键词匹配 | 角色3 | 2h |
| 4 | `data/knowledge_base/*.md` | 空目录 | **写 3-5 篇领域知识文档**（大模型应用开发相关的 Markdown 文件） | 角色3 | 3h |
| 5 | `backend/src/llm/client.py` | 无 API Key 时返回空 `{}` | **加演示模式**：无 API Key 时自动返回模拟数据，让系统在没有 API Key 的情况下也能完整跑通 | 角色2 | 2h |
| 6 | 前端 | 只有目录骨架 | **用 Streamlit 写一个简单前端**：输入学习者信息 → 点生成 → 看到诊断结果 + 学习资源 | 角色8 | 4h |
| 7 | `start.bat` | 没有 | **写一个 Windows 启动脚本**：双击自动装依赖 + 启动后端 + 启动前端 | 角色1或2 | 15min |

## 三、具体任务说明

### 任务 1: 简化编排器 → 角色1

**文件:** `backend/src/graph/orchestrator.py`

**要做什么:**
- 删掉 `_node_review`、`_node_debate`、`_node_finalize`、`_should_debate`、`_after_debate` 这些方法和所有相关代码
- 删掉 `from ..agents.audit import AuditAgent` 和 `self._audit_agent`
- `_run_sequential` 方法简化为三步：diagnose → retrieve → generate → return state
- `run()` 方法返回的 state 里不需要 `audit_reports`、`debate_records`、`final_resources`、`rejected_resources`
- Agent log 记录每个步骤的状态

**验证:** 运行 `python -c "from src.graph.orchestrator import workflow_engine; print('OK')"` 不报错

---

### 任务 2: 简化 API → 角色1

**文件:** `backend/src/api/main.py`

**要做什么:**
- `/api/generate` 接口接收简单的 JSON（不需要 Pydantic 校验，降低前端对接门槛）：
  ```json
  {
    "name": "张三",
    "education_level": "bachelor",
    "major": "计算机科学",
    "work_years": 1,
    "industry": "互联网",
    "positions": ["Python开发"],
    "skills_used": ["Python", "Flask"],
    "learning_goal": "学习LangGraph",
    "resource_types": ["lecture", "guide", "quiz"]
  }
  ```
- 返回直接包含 `diagnosis` + `resources`，不用查 task_id 再轮询：
  ```json
  {
    "task_id": "xxx",
    "status": "completed",
    "diagnosis": {...},
    "resources": [...],
    "agent_log": [...]
  }
  ```
- 不再引用 `final_resources`（这是辩论后才有的字段），改用 `generated_resources`
- 加简单的错误处理：LLM 调用失败 → 返回错误信息

**验证:** `curl -X POST http://localhost:8000/api/generate -H "Content-Type: application/json" -d '{"learning_goal":"test"}'` 能返回结果

---

### 任务 3: 知识库文件检索回退 → 角色3

**文件:** `backend/src/knowledge/store.py`

**要做什么:**
- `initialize()` 方法里先尝试 ChromaDB，失败则自动回退到文件模式
- 文件模式：读取 `data/knowledge_base/` 目录下所有 `.md` 文件，每个文件作为一个"文档"
- `search()` 方法在 ChromaDB 不可用时走关键词匹配：用户查询中的词 → 在文件内容中搜索 → 按匹配度排序返回
- 不需要 embedding，纯文本关键词检索就能跑通 MVP

**验证:** 启动后端后 `/health` 接口显示 `kb_docs: N`（N > 0）

---

### 任务 4: 写知识库文档 → 角色3

**目录:** `data/knowledge_base/`

**要做什么:**
写 **3-5 篇** Markdown 文档，内容是关于"大模型应用开发"领域的。每篇 500-1500 字。

**主题建议（选 3-4 个）：**
1. LangGraph 入门指南（StateGraph、节点、边、条件路由）
2. RAG 基础（分块→向量化→检索→生成）
3. Prompt Engineering 实践
4. 多 Agent 架构设计
5. LLM API 调用最佳实践（OpenAI/Anthropic）

**内容来源:** LangChain 官方文档、OpenAI Cookbook、Anthropic 文档。用你自己理解的写，不需要逐字翻译。

**质量要求:** 内容准确（可以和大模型交互验证），有代码示例，每条文档标注来源。

---

### 任务 5: LLM 演示模式 → 角色2

**文件:** `backend/src/llm/client.py`

**要做什么:**
- 当 `settings.LLM_API_KEY` 为空时，不返回空 `{}`，而是返回模拟数据
- 怎么判断返回什么模拟数据？看 `system_prompt` 的内容：
  - 如果包含 "学情诊断" → 返回模拟的诊断结果
  - 如果包含 "知识专家" 或 "生成" → 返回模拟的学习资源
- 模拟数据不需要多完美，能演示整个流程就行。关键是让"没有 API Key 的人"也能看到系统怎么运作
- 真实 API Key 配好后，模拟逻辑不触发，走真实调用

**验证:** 不配 API Key，调用 `/api/generate` 能返回有内容的诊断结果和资源（不是空的 `{}`）

---

### 任务 6: Streamlit 前端 → 角色8

**新建文件:** `frontend/streamlit/app.py`（单文件）

**要做什么:**
用 Streamlit 写一个单页面应用：

```
┌────────────────────────────────────────────────┐
│  🤖 领域知识个性化生成系统                       │
│  ─────────────────────────────────────────────  │
│ ┌── 侧边栏 ────────┐ ┌── 主区域 ──────────────┐ │
│ │                  │ │                         │ │
│ │ 姓名: [____]     │ │  📊 学情诊断 | 📚 资源   │ │
│ │ 学历: [dropdown] │ │                         │ │
│ │ 专业: [____]     │ │  诊断结果 + 知识盲区     │ │
│ │ 工作年限: [slider]│ │  生成的讲义/指南/题目    │ │
│ │ 学习目标: [text] │ │                         │ │
│ │                  │ │                         │ │
│ │ [🚀 生成资源]    │ │                         │ │
│ │                  │ │                         │ │
│ └──────────────────┘ └─────────────────────────┘ │
└────────────────────────────────────────────────┘
```

**技术要点:**
- `st.sidebar` 放输入表单
- `st.tabs` 放结果展示（一个 tab 诊断，一个 tab 资源）
- `requests.post("http://localhost:8000/api/generate", json=data)` 调用后端
- 不需要 WebSocket，不需要 Agent 可视化（那是 Phase 2 的事）
- 能跑就行

**验证:** 启动后浏览器打开 http://localhost:8501，填完表单点生成，能看到诊断结果和学习资源

---

### 任务 7: 启动脚本 → 角色1 或 角色2（谁先空谁做）

**新建文件:** `start.bat`（Windows 双击运行）

**脚本内容:**
```batch
1. 检查 .env 是否存在，不存在则从 .env.example 复制
2. pip install 依赖
3. 启动后端（新窗口）
4. 等 3 秒
5. 启动 Streamlit 前端（新窗口）
6. 打印 "后端: http://localhost:8000, 前端: http://localhost:8501"
```

---

## 四、依赖关系

```
任务3(知识库) ──→ 任务4(知识库文档) ──→ 任务1(编排器) ──→ 任务2(API)
                                                             │
任务5(LLM演示模式) ──────────────────────────────────────────┤
                                                             │
                                                             ▼
                                        任务6(前端) ←── 任务7(启动脚本)
```

**角色2 和 角色3 可以先动**：LLM 演示模式和知识库文件检索是最独立的两块，没有依赖。

**角色1 等角色2和3 做完再动**：编排器和 API 依赖 LLM 层和知识库能跑通。

**角色8 等角色1 的 API 好了再动**：前端靠调 API，API 先能返回数据。

## 五、MVP 验收标准

团队内部验收（7/28 硬节点之前自测通过）：

- [ ] `start.bat` 双击能启动，不报错
- [ ] 浏览器打开前端，能看到页面
- [ ] 不配 API Key 也能走完流程（演示模式）
- [ ] 填好学习者信息 → 点生成 → 看到诊断结果 + 至少 1 份学习资源
- [ ] 后端返回的数据不是空的 `{}`（演示模式也返回模拟内容）
- [ ] `/health` 接口返回 `kb_docs` > 0

## 六、MVP 不做的事

| 不做 | 原因 |
|------|------|
| Agent 3（审核裁判） | Phase 2 再加 |
| 辩论协议 | Phase 2 再加 |
| 三项指标评估 | Phase 2 再加 |
| React 前端 | Streamlit 够快，Phase 2 再换 |
| ChromaDB 向量检索 | 文件关键词检索够 MVP 用 |
| WebSocket 实时推送 | Phase 2 再加 |
| Agent 可视化拓扑图 | Phase 2 再加 |
| Docker 部署 | Phase 3 再加 |

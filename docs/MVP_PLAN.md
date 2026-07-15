# MVP 分工安排

> **目标：** 只做 Agent 1（学情诊断）+ Agent 2（知识生成），前后端能跑通，能生成资源。
> **不做：** Agent 3（审核裁判）、辩论协议、三项指标评估、RAG 知识库。
> **知识来源：** Agent 2 直接用 LLM 自身知识生成内容（不做本地文档检索）。
> **时间：** 7/16–7/31，七月底验收。

---

## 一、MVP 简化架构

```
完整版（Phase 2 目标）:            MVP 版（Phase 1 目标）:

┌──────────┐  学情画像  ┌──────────┐  知识检索  ┌──────────┐
│ 学情诊断  │──────────▶│ 知识生成  │──────────▶│ 审核裁判  │
│  Agent   │           │  Agent   │           │  Agent   │
└──────────┘           └────┬─────┘           └──────────┘
     ✅                      │                      ❌ 不做
                     LLM 自身知识
                     （GPT-4o / Claude / DeepSeek）
```

**关键简化：** Agent 2 不再从本地知识库检索，而是直接靠 LLM 的自身知识生成内容。
- 优点：零配置，启动就能跑，不需要准备文档
- 代价：没有 citation 溯源，内容可能不够深入（Phase 2 再加 RAG）

---

## 二、MVP 流程（两步）

```
POST /api/generate { learner_data }
        │
        ▼
┌───────────────────┐
│ Agent 1: 学情诊断   │  分析学习者背景 → 知识缺口图谱
│ 输入: 学历/经历/目标 │
│ 输出: skill_gaps +  │
│       learning_style│
└────────┬──────────┘
         │ diagnosis_result
         ▼
┌───────────────────┐
│ Agent 2: 知识生成   │  根据缺口 + LLM自身知识 → 学习资源
│ 输入: diagnosis +   │
│       resource_type │
│ 输出: lecture/guide │
│       /quiz         │
└────────┬──────────┘
         │
         ▼
   返回给前端
   { diagnosis, resources }
```

---

## 三、MVP 需要改的文件（5 个任务，不是 7 个）

| # | 文件 | 要做什么 | 负责角色 | 工作量 |
|---|------|---------|---------|--------|
| 1 | `backend/src/graph/orchestrator.py` | **砍掉检索步骤**，只保留 diagnose → generate 两步 | 角色1 | 20min |
| 2 | `backend/src/api/main.py` | `/api/generate` 一键接口，返回 diagnosis + resources | 角色1 | 30min |
| 3 | `backend/src/agents/generation.py` | **去掉 KB 约束**，让 Agent 2 直接用 LLM 自身知识生成 | 角色5 | 1h |
| 4 | `backend/src/llm/client.py` | 演示模式：无 API Key 时返回模拟数据 | 角色2 | 2h |
| 5 | `frontend/streamlit/app.py` | Streamlit 单文件前端 | 角色8 | 4h |

**不再需要：** 角色3 的知识库任务（不建本地知识库）。

---

## 四、具体任务说明

### 任务 1: 简化编排器 → 角色1

**文件:** `backend/src/graph/orchestrator.py`

**要做什么:**
- 只保留两个节点：diagnose → generate
- 删掉 `_node_retrieve`、`_node_review`、`_node_debate`、`_node_finalize` 和所有相关方法
- 删掉 `from ..knowledge.store import knowledge_base`
- `run()` 方法简化为：diagnose → generate → return state

**验证:** Agent 2 调用时不传 `retrieved_chunks`，Agent 2 能正常生成

---

### 任务 2: 简化 API → 角色1

**文件:** `backend/src/api/main.py`

**要做什么:**
- `/api/generate` 接收简单 JSON，直接返回 `diagnosis + resources`
- 不需要 task_id 轮询机制（MVP 用同步返回即可）
- 删掉知识库相关接口（没有本地 KB 了）

---

### 任务 3: Agent 2 去掉 KB 约束 → 角色5

**文件:** `backend/src/agents/generation.py`

**当前代码的问题：** Agent 2 的 prompt 里写了"你必须基于检索到的知识库文档生成，不要编造"。如果 `retrieved_chunks` 为空，Agent 2 会拒绝生成。

**要做什么:**
- 修改 system prompt，把"基于知识库检索结果生成"改为"**用你的知识**为学习者生成内容"
- 当 `retrieved_chunks` 为空时，不返回 `{"error": "no_knowledge_base"}`，而是正常生成
- 生成的资源里 `citations` 可以为空数组（MVP 阶段不做溯源）
- 保持个性化功能：根据学习者的 skill_gaps 和 difficulty 定制内容

**新的 system prompt 要点：**
```
你是一个领域知识专家和教育内容创作者。
请根据学习者的知识盲区和难度等级，用你的专业知识生成学习资源。
生成资源类型：lecture（讲义）/ guide（实操指南）/ quiz（测试题）
内容要准确、实用、匹配学习者的水平。
```

**验证:** `retrieved_chunks: []` 的情况下调 Agent 2 → 正常返回资源内容，不报错

---

### 任务 4: LLM 演示模式 → 角色2

**文件:** `backend/src/llm/client.py`

**要做什么:**
- 无 API Key 时自动返回模拟数据（不返回空 `{}`）
- 模拟数据根据 system_prompt 内容区分：
  - 含"学情诊断" → 返回模拟诊断 JSON
  - 含"知识专家" → 返回模拟学习资源 JSON
- 配了真实 API Key → 走真实 LLM 调用

**当前仓库里已有参考实现**，角色2 的工作是理解 + 测试 + 完善。

**验证:** 不配 API Key → `/api/generate` 返回有内容的 diagnosis 和 resources

---

### 任务 5: Streamlit 前端 → 角色8

**新建文件:** `frontend/streamlit/app.py`

**布局设计：**
```
左栏（侧边栏）              右栏（主区域）
┌─────────────────┐    ┌──────────────────────────┐
│ 姓名: [____]     │    │ [📊 学情诊断] [📚 资源]     │
│ 学历: [下拉]     │    │                          │
│ 专业: [____]     │    │  学习风格: xxx             │
│ 工作年限: [滑块]  │    │  知识盲区列表（可展开）      │
│ 行业: [____]     │    │  知识掌握度进度条           │
│ 技能: [____]     │    │                          │
│ 学习目标: [文本框] │    │  生成的讲义/指南/题目       │
│ 资源类型: [多选]   │    │  （Markdown渲染）          │
│                  │    │                          │
│ [🚀 生成资源]     │    │                          │
└─────────────────┘    └──────────────────────────┘
```

**仓库里已有参考实现**，角色8 的工作是理解 + 跑通 + 调整 UI。

**验证:** 浏览器打开 → 填表单 → 点生成 → 看到诊断 + 资源

---

## 五、依赖关系

```
任务4(LLM演示模式) ──→ 任务1(编排器) ──→ 任务2(API) ──→ 任务5(前端)
                                         │
任务3(Agent2去KB约束) ──────────────────┘
```

**能并行的事项：**
- 角色2（LLM演示模式）和角色5（Agent2去KB约束）互不依赖，第一天就能同时开工
- 角色8 可以等 API 好了再动，但可以先学 Streamlit

---

## 六、MVP 验收清单（7/30 检查）

| # | 验收项 | 标准 |
|---|--------|------|
| 1 | 双击 `start.bat` 或手动启动能跑 | 后端 + 前端都启动，不报错 |
| 2 | 不配 API Key 能走完 | 演示模式生效，不返回 `{}` |
| 3 | 配 API Key 能走完 | 返回真实 LLM 生成内容 |
| 4 | 前端页面正常显示 | 浏览器无白屏，表单可交互 |
| 5 | 学情诊断有内容 | 学习风格、推荐难度、≥3 个知识盲区 |
| 6 | 学习资源有内容 | 至少 1 份（讲义/指南/测试题），Markdown 渲染正常 |
| 7 | 不同输入产生不同结果 | 换学历/学习目标 → 诊断和资源都跟着变 |
| 8 | 三种资源类型可选 | lecture / guide / quiz 分别能生成不同内容 |
| 9 | 错误提示友好 | 后端没启动时前端提示"请先启动后端"，不白屏 |
| 10 | Agent 2 不依赖知识库 | `retrieved_chunks` 为空时正常生成，不报错 |

---

## 七、MVP 不做的事

| 不做 | 原因 | 什么时候做 |
|------|------|-----------|
| 本地 RAG 知识库 | LLM 自身知识够用 | Phase 2 |
| Agent 3（审核裁判） | 先跑通生成闭环 | Phase 2 |
| 辩论协议 | 先跑通生成闭环 | Phase 2 |
| 三项指标评估 | 先跑通生成闭环 | Phase 2 |
| 内容溯源/citation | 没有 KB 没法溯源 | Phase 2（加 RAG 后） |
| React 前端 | Streamlit 够快 | Phase 2 或 3 |
| ChromaDB 向量库 | MVP 不做检索 | Phase 2 |
| WebSocket 实时推送 | 同步返回够用 | Phase 2 |

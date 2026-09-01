# 领域知识个性化生成与多智能体协同决策系统

题目编号：XH-202630 | 发榜单位：上海云之脑智能科技有限公司

---

## 当前阶段：Phase 2 — 多 Agent 博弈协同 + 知识库高保真

| 周期 | 阶段 | 截止 |
|------|------|------|
| 5月-7月 | ✅ Phase 1 MVP（3 Agent 串行管道） | 已完成 |
| 7/27-8/16 | 🔨 Phase 2 深化（4 Agent + 博弈 + RAG + 三项指标） | 8/16 代码冻结 |
| 8/17-9/5 | 📦 交付（文档 + 视频 + 测试数据 + 打包） | 9/5 正式提交 |

### 快速导航

| 文档 | 说明 |
|------|------|
| [Phase 2 总体方案](docs/PHASE2_PLAN.md) | 架构总览、防幻觉体系、分工总表、时间安排 |
| [人员1 — 编排器+WebSocket+闸门](docs/roles/phase2/person1-orchestrator.md) | 流水线大脑 |
| [人员2 — Agent 1 + KB审核](docs/roles/phase2/person2-agent1-kb-review.md) | 学情诊断 + 知识库守门人 |
| [人员3 — Agent 2 + Agent 4](docs/roles/phase2/person3-agent2-agent4.md) | 知识生成 + 保真修正 |
| [人员4 — RAG + Agent 3 + 辩论 + 三项指标](docs/roles/phase2/person4-rag-agent3-debate.md) | 审核博弈方 + 知识库基础设施 + 质量量化 |
| [人员5+7 — API + WebSocket](docs/roles/phase2/person5-api.md) | 两人协作后端全部接口 |
| [人员6 — Streamlit 前端](docs/roles/phase2/person6-frontend.md) | 可视化 + 交互 |
| [人员8 — KB数据 + 代码验证 + 部署](docs/roles/phase2/person8-kb-data-delivery.md) | 知识库内容 + 打包部署 |
| [排期与检查点](docs/PHASE2_SCHEDULE.md) | 三阶段谁做什么 + 检查点 |

---

## 架构总览

```
用户输入 → 闸门1(特异性检测) → Agent1(学情诊断) → 闸门2(诊断质量)
  → Agent2 Step1(生成检索Query) → RAG检索 → 闸门3(召回质量)
  → Agent2 Step2(基于KB约束生成) → Agent3(事实核查) → 博弈引擎(辩论)
  → Agent4(保真修正) → Agent3再审 → 标准化输出 → 前端
```

**4 Agent + 1 博弈引擎 + 3 道闸门 + 6 道防幻觉防线**

---

## 六道防幻觉防线

| 防线 | 环节 | 卡什么 | 谁执行 |
|------|------|--------|--------|
| ① | 检索约束 | 相似度 < 0.6 不进 context，KB 没有的不硬编 | RAG 工具层 |
| ② | 约束生成 | 只能基于 KB 原文，每条断言标注来源 | Agent 2 |
| ③ | 事实核查 | 逐条断言 vs 原文，标 accurate / hallucination / unverifiable | Agent 3 |
| ④ | 博弈对抗 | 质疑 → 应诉 → 双方援引原文 → 裁决 | 博弈引擎 |
| ⑤ | 保真修正 | 删除错误、补溯源、冲突并列不选边 | Agent 4 |
| ⑥ | 标准化包装 | 溯源 + 审核 + 辩论记录全部下发，透明可查 | 编排器 |

---

## 知识库领域

**工业机器人编程与调试**（FANUC / KUKA / ABB 多品牌），12 个知识域（K1–K12）：

基础操作与示教编程 · 离线编程与仿真 · 安全规范与故障诊断 · 机器人基础理论 · 机器视觉集成 · 协作机器人 · I/O 与现场总线 · 产线集成与 PLC · 工艺应用 · 多厂商机器人 · 机器人动力学与精度 · AI 机器人与智能应用

- 领域文档存于 `data/raw/`（启动时自动向量化进 ChromaDB）；
- 核心知识点清单见 `data/core_knowledge_map.json`（42 个 core/high 知识点，覆盖率指标的裁判依据）。

---

## 快速启动

前后端分开启动（各占一个终端窗口）。**完整部署说明见 [DEPLOY.md](DEPLOY.md)**。

### 后端

```bash
# 首次：创建虚拟环境并安装依赖（Windows 也可直接双击 start.bat 自动完成）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt    # Windows
# Linux/Mac: .venv/bin/pip install -r requirements.txt

# 复制配置（默认演示模式，真实调用需编辑 .env 填 LLM_API_KEY）
copy .env.example .env          # Windows
# Linux/Mac: cp .env.example .env

# 启动后端
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：http://localhost:8000/health（启动时会增量同步 `data/raw`：新文档自动向量化，已修改文档自动重建，未变更文档跳过）

### 前端

```bash
cd frontend
npm ci          # 首次安装依赖
npm run dev     # 启动 Vite dev server
```

打开 http://localhost:5173/（方案 B 为默认入口）

---

## 项目结构

```
XH-agent/
├── main.py              # FastAPI 服务入口（POST /api/generate + /api/knowledge/*）
├── backend/src/
│   ├── agents/          # 4个Agent: diagnosis / generation / audit / correction
│   ├── debate/          # 博弈协议引擎（三态裁决）
│   ├── quality_gate/    # 三道质量闸门（input / diagnosis / recall）
│   │   └── gates/
│   ├── evaluation/      # 三项硬指标评估 + 保真打分
│   ├── knowledge/       # ChromaDB 知识库（store / parser）
│   ├── graph/           # 编排器（orchestrator）
│   ├── scheduler/       # 流水线调度
│   ├── llm/             # LLM 抽象层（多模型支持）
│   ├── api/             # FastAPI + WebSocket + profiles/pretests/exams
│   ├── config.py        # 全局配置唯一入口
│   ├── schemas.py       # 全员统一数据契约
│   └── exceptions.py
├── frontend/            # React + Vite + TypeScript 前端
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── data/
│   ├── raw/             # 知识库原始文档（K1–K12 领域，启动自动向量化）
│   ├── core_knowledge_map.json  # 核心知识点清单（覆盖率裁判）
│   ├── evaluation/      # 画像 / 真值 / 测试用例
│   ├── qa_dataset/      # 问答评测集
│   └── chroma/          # ChromaDB 持久化（派生，可重建）
├── submission_test_data/  # 提交用测试数据包（切片+画像+输入输出示例）
├── submission/          # 提交打包脚本（pack.py + 打包清单）
├── scripts/             # 工具脚本（评测 / 回归 / 防幻觉检查等）
└── docs/                # 架构方案 / 分工 / 测试方案
```

---

## 评分标准覆盖

| 维度 | 分值 | 覆盖方式 |
|------|------|---------|
| 作品完整性 | 30 | 4 Agent + 3 闸门 + 编排器 → "学情→生成→校验→决策→反馈"全流程闭环 |
| 技术创新性 | 25 | 辩论引擎 + 6道防幻觉防线 + 知识库约束生成 + 高保真知识溯源 |
| 用户体验 | 15 | Agent 协同拓扑图 + 辩论 timeline + 知识雷达图 + 学习路径 DAG |
| 实用价值 | 30 | 三项硬指标自动评估(幻觉率<5%/适配率≥85%/覆盖率≥90%) + 4领域知识库 |

# XH-agent 知识库实施方案

> **项目**：XH-202630 面向工业机器人编程调试的多智能体个性化学情诊断系统
> **版本**：v1.0
> **更新日期**：2026-08-03
> **依赖文档**：`docs/PHASE2_PLAN.md`（Phase2 任务规划主文档）

---

## 一、概述

本文档定义 Phase2 知识库搭建的完整技术方案，涵盖向量数据库选型、后端 API 端点、前端管理界面、队友协作流程、切分策略和已完成的代码清单。

**核心原则**：优化组提供知识库基础设施（引擎 + API + 界面），知识库组负责资料采集与共建阶段搭建。

---

## 二、技术架构

### 2.1 向量数据库：ChromaDB

- **选型**：ChromaDB 持久化模式（`PersistentClient`）
- **持久化目录**：`data/chroma/`（首次启动自动创建）
- **集合名称**：由 `.env` 中 `CHROMA_COLLECTION_NAME` 配置（默认 `domain_knowledge`）
- **相似度算法**：cosine（HNSW 索引）

### 2.2 Embedding 模型

按 `LLM_API_KEY` 是否配置自动选择：

| 场景 | 模型 | 维度 | 说明 |
|------|------|------|------|
| 有 API Key | `text-embedding-3-small`（OpenAI） | 1536 | 通过 `chromadb.utils.embedding_functions.OpenAIEmbeddingFunction` 调用 |
| 无 API Key | `all-MiniLM-L6-v2`（ChromaDB 内置） | 384 | 首次启动自动下载到 `~/.cache/chroma/onnx_models/` |

### 2.3 文件模式回退

ChromaDB 不可用时自动回退：
- 扫描 `data/raw/` 目录递归查找 `.md` 文件
- 兼容旧路径 `data/knowledge_base/`
- 检索降级为关键词匹配

---

## 三、文本切分策略

由 `backend/src/knowledge/store.py` 的 `_chunk_text()` 实现：

| 参数 | 值 | 说明 |
|------|-----|------|
| chunk_size | 512 字符 | 约 800 tokens 中文，覆盖 1~2 个操作步骤 |
| overlap | 64 字符 | 滑动窗口，保证跨 chunk 上下文衔接 |
| 切分边界 | 段落（`\n\n`） | 不在句子中间断开 |
| 元数据 | doc_id / doc_title / chunk_index | 每个 chunk 携带来源信息 |

---

## 四、API 端点

### 4.1 主接口（不变）

`POST /api/generate` 入参、出参结构完全不变。详见 `docs/PHASE2_PLAN.md` 第七章。

### 4.2 知识库管理端点（新增）

| 端点 | 方法 | 用途 | 请求体 / 参数 |
|------|------|------|-------------|
| `/api/knowledge/upload` | POST | 单篇文档入库 | `{doc_id, title, content}` |
| `/api/knowledge/import` | POST | 批量导入 `data/raw/` 下全部 `.md` | 无 |
| `/api/knowledge/search` | GET | 语义检索 | `?q=关键词&top_k=5` |
| `/api/knowledge/stats` | GET | 统计信息 | 无 |
| `/api/knowledge/{doc_id}` | DELETE | 删除文档及全部 chunks | 路径参数 |

### 4.3 `/health` 扩展

新增返回字段：`kb_docs`（文档总数）、`kb_mode`（chromadb / file）。

---

## 五、Streamlit 知识库管理页面

在原界面新增第 4 个 Tab「📚 知识库管理」：

### 左侧：文档导入区
- **手动粘贴**：标题输入框 + Markdown 正文文本框（≥500 字校验）→ "上传到知识库"
- **批量导入**：一键导入 `data/raw/` 目录下全部 `.md` 文件

### 右侧：状态面板
- 实时显示：模式（chromadb / file）、文档总数、Chunk 总数

### 底部：检索测试区
- 关键词输入 → "检索"按钮 → 展示匹配 chunks 及相关度分数

---

## 六、知识库组工作流程

```
Day 2–3  采集 → Markdown → 自检 → git commit data/raw/Kx_xxx/ → git push
Day 4    打开 Streamlit → "知识库管理" → "批量导入" → 自动切分+向量化
Day 5–6  每日重复采集 → 提交 → 导入
Day 7    上午：打包 ≥20 篇交付架构组
         下午：K1 清洗 / K2 切片 / K3 入库评测
Day 8–10 共建：清洗 → 切片 → 向量化 → RAG 评测 → KB v1.0 交付
```

### Git 协作
- 每人在 `data/raw/Kx_xxx/` 下提交自己的 Markdown 文件
- `git pull` 后通过 KB 管理页面 "批量导入" 按钮入库
- 文件名规范：`Kx_YYYYMMDD_序号_标题摘要.md`

---

## 七、代码文件清单

| 文件 | 归属人 | 职责 |
|------|--------|------|
| `backend/src/knowledge/store.py` | **Opt-2** | KB 引擎：ChromaDB 初始化、Embedding 配置、文本切分、CRUD、语义检索 |
| `backend/src/api/main.py` | **Opt-4** | API 层：`/api/knowledge/*` 5 端点、`/health`（含 kb_docs）、lifespan 初始化 KB |
| `frontend/streamlit/app.py` | **Opt-4** | KB 管理页面：上传、批量导入、统计面板、检索测试 |
| `data/raw/K1_robot_base/*.md` | **K1** | 基础操作与示教编程资料 |
| `data/raw/K2_robot_simulation/*.md` | **K2** | 离线仿真与工艺包资料 |
| `data/raw/K3_safety_fault/*.md` | **K3** | 安全规范与故障诊断资料 |

---

## 八、阶段目标

| 指标 | 目标值 | 截止日 |
|------|--------|--------|
| KB 引擎就绪 | ChromaDB CRUD 完整 + 切分 + 检索 | Day 4 |
| KB 页面上线 | 上传 + 导入 + 检索 + 统计 | Day 4 |
| 入库文档 | ≥ 30 篇（各领域 ≥ 10 篇） | Day 7 |
| KB 样本交付 | ≥ 20 篇 | Day 7 上午 |
| 清洗完成 | `data/cleaned/` 全部就绪 | Day 8 |
| 切片完成 | `data/chunks/` v1 产出 | Day 8 |
| RAG 评测 | 命中率 ≥80%、MRR ≥0.6 | Day 9–10 |
| KB v1.0 交付 | 向量化入库 + 评测通过 | Day 10 |

---

## 九、约束条件

1. `/api/generate` 入参、出参结构完全不变
2. 无独立 `/api/chat` 端点（RAG 检索逻辑内嵌在 `/api/generate` 主流程中，由 Arch-L Phase 2b 阶段接入）
3. 防幻觉功能（Agent4 保真修正、correction_log）全部延后至 Phase 3
4. 博弈引擎为 Day 9–10 可选任务
5. 知识库搭建（清洗/切片/入库/评测）由 K1~K3 负责，优化组只提供基础设施

---

## 十、验证记录

```
ChromaDB 模式初始化成功
3 篇种子文档 → 13 chunks 入库
检索 "SRVO-068" → [0.70] FANUC SRVO-068 故障代码解析
检索 "RobotStudio" → [0.71] ABB RobotStudio 离线仿真工作站搭建
检索 "PTP" → [0.66] 相关文档命中
```

---

> **文档结束** — 实施完毕后由 K5（评测）或 K3（评测牵头）更新验证记录。

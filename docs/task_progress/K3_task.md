# K3 — 任务卡片

> **角色**：知识库组 · 采集 + 入库/评测牵头
> **负责领域**：安全规范、故障诊断与产线适配（`data/raw/K3_safety_fault/`）
> **共建阶段牵头**：Embedding 入库 + RAG 召回评测（见 `docs/PHASE2_PLAN.md §3.9.3`）

---

## 一、采集阶段成果（Day 1–6）

K3 领域共采集 **8 篇**文档，全部为 A 级（FANUC 官方维护手册 `R-30iB B-83195EN/08` 归纳整理），均已通过 7 项自检。

| # | 文件 | 主题 |
|---|------|------|
| 1 | `K3_20260803_001_fanuc_srvo068_error_fix.md` | SRVO-068 DTERR 脉冲编码器数据传输异常 |
| 2 | `K3_20260805_001_fanuc_srvo068_error_fix.md` | SRVO-068（二次整理版，含 SRVO-069/070 关联） |
| 3 | `K3_20260805_002_fanuc_srvo062_bzal_error_fix.md` | SRVO-062 BZAL 备份电池报警 |
| 4 | `K3_20260807_003_fanuc_srvo038_pulse_mismatch_error_fix.md` | SRVO-038 脉冲不匹配 |
| 5 | `K3_20260807_004_fanuc_srvo105_door_estop_error_fix.md` | SRVO-105 控制柜门开/急停 |
| 6 | `K3_20260812_005_fanuc_srvo004_fence_open_error_fix.md` | SRVO-004 安全围栏打开 |
| 7 | `K3_20260812_006_fanuc_srvo075_pulse_not_established_error_fix.md` | SRVO-075 脉冲未建立 |
| 8 | `K3_20260812_007_fanuc_srvo230_231_safety_chain_error_fix.md` | SRVO-230/231 安全链失配 |

> 覆盖故障代码解析、安全规范、产线安全联锁三类，满足 K3 领域「安全规范、故障诊断与产线适配」采集清单。

---

## 二、共建阶段成果（Day 7–10，K3 牵头）

### ① Embedding 选型
- 沿用项目统一配置：`EMBEDDING_PROVIDER=chroma` → 内置 `all-MiniLM-L6-v2`（384 维），零外部 API 依赖。

### ② 入库
- **状态**：✅ 完成。全量 13 篇（K1×4 + K2×1 + K3×8）已向量化写入 ChromaDB。
- **库位置**：`backend/data/chroma/`（collection `domain_knowledge`，93 chunks）。
- **入库脚本**：`scripts/k3_ingest.py`（扫描 `data/raw/` → 提取标题 → 批量幂等写入）。

### ③ QA 数据集（≥30 条）
- **状态**：✅ 完成。`data/qa_dataset/k3_qa_dataset.json`，共 **31 条**。
- **分布**：操作 9 条 / 编程 8 条 / 故障 14 条；领域 K1×14 / K2×3 / K3×14。
- 每条含 `query` / `category` / `expected_domain` / `expected_keywords` / `expected_doc_ids`（精确答案）。

### ④ RAG 召回评测
- **评测脚本**：✅ 完成。`scripts/k3_eval.py`，输出 Top-5 命中率 / MRR / 领域覆盖 / 平均延迟。
- **评测执行 + 报告**：⏸️ 未执行（`docs/eval/` 报告暂未生成）。

---

## 三、评测指标目标（待执行时对照）

| 指标 | 目标值 |
|------|--------|
| Top-5 命中率 | ≥ 80% |
| MRR | ≥ 0.6 |
| 领域覆盖 | 3/3（K1/K2/K3） |
| 切分质量反馈 | 不合理 chunk < 10% |

---

## 四、待办 / 备注

- [ ] 执行 `python scripts/k3_eval.py`，产出 `docs/eval/` 评测报告。
- [ ] 根据评测结果反馈 K2 切片参数（如需第二轮评测）。
- ⚠️ 已知隐患：`CHROMA_PERSIST_DIR=./data/chroma` 为相对路径，从根目录启动会读到旧库（5 篇）；完整库在 `backend/data/chroma`。建议后续统一为绝对路径或固定从 `backend/` 启动。

---

## 五、Phase 3 Agent3 检索优化评测结论（2026-08-26）

针对「知识库已有事实但检索召不回 → 误判 unverifiable」的 B 类问题，做了三轮低风险优化（不扩库、不换 embedding）：

| 改动 | 位置 | 说明 |
|------|------|------|
| P0 调大 top_k | `audit.py` `KB_TOP_K_PER_CLAIM` 3→5 | 每条断言多召回 2 条证据 |
| P2 关键词检索升级 BM25 | `store.py` `_keyword_search` | 手写 OKAPI BM25，IDF 给稀有技术术语（SRVO-068/PTP/MoveC）高权重，替换原 hit-count |
| Step0 调试日志 | `audit.py` `_log_retrieval` | 逐 claim 打印检索命中片段 + verdict |
| Step1 A/B 判定脚本 | `classify_unverifiable.py` | 离线把 unverifiable 拆成 A 类（KB 缺失）/ B 类（检索未召回） |

**58 case 全量评测（真实模式，DeepSeek）对比基线：**

| 指标 | 基线 | 优化后 | 变化 |
|------|------|--------|------|
| hallucination | 23 | 23 | 持平（符合「检索不动幻觉」预期）|
| unverifiable | 65 | 64 | -1 |
| A 类（KB 缺失，允许保留）| 58 | 61 | +3 |
| **B 类（检索未召回）** | **7** | **3** | **-4，减半 ✅** |

三条评估标准全部达标：真正幻觉不上涨、B 类下降、A 类允许保留。

**备注**：评测中 4 个 P3-02 case（K1-HIGH-006 / K2-CORE-001/002/003）首次跑因 DeepSeek 瞬时故障（`XHLLMRetryExhaustedError`，诊断 Agent 重试 3 次失败）整段空输出，已用 `--case-id` 重跑补全并合并，非检索改动所致。若 B 类仍需进一步压缩，再上 P1（chunk_size/overlap，需处理 re-embed 陷阱）或 P3（换中文 embedding）。

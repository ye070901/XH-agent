# Arch-L Day 1-10 任务进度报告 — 闸门 + 调度

> **角色**: Arch-L（架构师-调度方向）
> **模块**: QualityGate 三闸门 + Scheduler 调度流水线
> **Phase**: Phase 2 Opt-3（Gates+Scheduler）
> **报告日期**: 2026-08-11

---

## 一、交付物清单

| # | 交付物 | 计划 | 实际 | 状态 |
|:--:|--------|:----:|:----:|:----:|
| 1 | InputGate 输入安全过滤 | D1-2 | ✅ 完成 | `quality_gate/gates/input_gate.py` |
| 2 | DiagnosisGate 诊断质量检测 | D3-5 | ✅ 完成 | `quality_gate/gates/diagnosis_gate.py` |
| 3 | RecallGate RAG 召回检测 | D5-7 | ✅ 完成 | `quality_gate/gates/recall_gate.py` |
| 4 | Scheduler 流水线调度器 v0.1 | D5-8 | ✅ 完成 | `scheduler/pipeline_v0.py` |
| 5 | Scheduler 完整版流水线 | D8-10 | ✅ 完成 | `scheduler/pipeline.py` |
| 6 | 单元测试 | D3-10 | ✅ 完成 | 11 个测试用例，全部通过 |
| 7 | E2E 集成测试 | D8-10 | ✅ 完成 | 5 个 E2E 场景覆盖 |
| 8 | 覆盖率报告 | D9-10 | ✅ 完成 | 见第三节 |
| 9 | 联调通过报告（本文档） | D10 | ✅ 完成 | 本文档 |

---

## 二、闸门实现详情

### 2.1 InputGate（输入特异性检测）

- **策略**: `HARD_RULE_ONLY`（纯规则，不调 LLM）
- **检测维度**:
  1. 空输入拦截 → FALLBACK
  2. 输入过短（< GATE1_MIN_INPUT_LENGTH）→ 违规标记
  3. 危险关键词匹配（违法/暴力/色情/赌博/毒品）→ 违规标记
  4. 领域外话题（政治/军事/金融/医疗）→ 违规标记
  5. 意图识别（计分制，优先级 P0 故障 > P1 安全 > P2 通信 > P3 编程 > P4 参数 > P5 概念）
- **代码行数**: 260 行
- **测试覆盖**: 86%（10/73 未覆盖行主要是领域外关键词匹配分支）

### 2.2 DiagnosisGate（学情诊断质量检测）

- **策略**: `HARD_RULE_ONLY`（v0.1 纯规则，不调 LLM）
- **三路裁决**:
  - PASS: `overall_confidence ≥ 阈值` AND `recommended_difficulty 非空` AND `skill_gaps 非空`
  - RETRY: 任一字段不满足，附带 `retry_hint` 告知缺失项
  - FALLBACK: JSON 完全不可解析 → 降级默认初级用户诊断
- **稀疏阈值机制**: `_get_effective_threshold()` 根据 learner_data 丰富度动态调整：
  - 丰富画像（含 education_level/major/work_years 等）→ 标准阈值 0.6
  - 稀疏画像（仅 learning_goal）→ 宽松阈值 0.05
- **代码行数**: 266 行
- **测试覆盖**: 80%（18/90 未覆盖行主要是 bool 类型异常和 knowledge_map list 格式兼容分支）

### 2.3 RecallGate（RAG 召回质量检测）

- **策略**: `HARD_RULE_ONLY`（判定规则化，Query 改写调轻量 LLM）
- **三路裁决**:
  - PASS: `len(retrieved_chunks) >= 1`
  - RETRY: 召回为 0 且 `retry_count < RECALL_MAX_RETRIES(3)` → LLM 改写 Query
  - FALLBACK: 连续 3 次重试仍为 0 → 降级输出
- **Query 改写**: LLM 调用 → 失败降级为关键词提取（`_keyword_extract_fallback`）
- **代码行数**: 203 行
- **测试覆盖**: 39%（LLM 改写路径需真实 LLM 环境，单元测试仅覆盖 PASS/FALLBACK 规则分支）

---

## 三、测试与覆盖率

### 3.1 测试用例

| 测试类 | 场景 | 状态 |
|--------|------|:--:|
| `TestPipelineNormal` | 正常路径：全 PASS → DONE | ✅ |
| `TestPipelineFallback` | RAG 无召回 → RETRY×3 → FALLBACK | ✅ |
| `TestPipelineAgentException` | Agent 崩溃 → 异常隔离 → FALLBACK | ✅ |
| `TestPipelineEmptyInput` | 空输入 → InputGate FALLBACK 即刻终止 | ✅ |
| `TestPipelineIntentUnknown` | 意图"未识别" → 降级兜底不崩溃 | ✅ |
| `TestDiagnosisGate` ×6 | 置信度阈值/稀疏模式/缺失字段/FALLBACK | ✅ |

**总计: 11 tests, 11 passed**

### 3.2 覆盖率（pytest-cov）

| 模块 | 语句数 | 覆盖 | 未覆盖 |
|------|:------:|:----:|--------|
| `quality_gate/__init__.py` | 3 | **100%** | — |
| `quality_gate/base.py` | 68 | **76%** | LLM review 延迟初始化、error 返回体 |
| `quality_gate/gates/__init__.py` | 4 | **100%** | — |
| `quality_gate/gates/input_gate.py` | 73 | **86%** | 危险关键词/领域外命中分支 |
| `quality_gate/gates/diagnosis_gate.py` | 90 | **80%** | bool 置信度/非 dict skill_gaps 类型异常 |
| `quality_gate/gates/recall_gate.py` | 54 | **39%** | LLM 改写路径（需集成测试环境） |
| `scheduler/__init__.py` | 2 | **100%** | — |
| `scheduler/pipeline_v0.py` | 196 | **84%** | 真实 Agent 注册函数、RAG 失败分支 |
| `scheduler/pipeline.py` | 280 | **20%** | 完整版流水线（待 Phase 2 正式联调） |

**加权覆盖率**: quality_gate 核心 76%，scheduler/pipeline_v0 **84%**。

> 注：`pipeline.py`（完整版）覆盖率 20% 是因为该文件包含真实 Agent/LLM 调用路径，
> 需要 Phase 2 全面联调时在真实环境中测试，当前由 `pipeline_v0.py` 承担可测试的调度逻辑。

---

## 四、Day 9-10 裁决边界调优分析

### 4.1 DiagnosisGate 稀疏阈值（0.05）

**结论：当前设置合理，建议保留。**

分析：
- 当 learner_data 仅含 `learning_goal`（无学历/专业/经历/测试）时，模型事实上没有足够依据给出高置信度诊断
- 如果维持标准阈值 0.6，用户几乎必然触发无限 RETRY 循环，体验极差
- 0.05 的语义是"接受任何能解析出有效 JSON 的诊断结果"，等价于跳过置信度检查
- 此时 `skill_gaps` 和 `recommended_difficulty` 的校验仍然生效，保证输出结构完整

**建议后续优化**（非阻塞）：
- 在 FALLBACK 降级诊断中注入"请补充学历、工作经历等背景信息以获得更精准的诊断"提示
- 可考虑分层阈值：中等稀疏（有 2-3 个字段）→ 0.3，极度稀疏 → 0.05

### 4.2 RecallGate RETRY 策略

- `RECALL_MAX_RETRIES = 3`，每次 RETRY 调用 LLM 改写 Query
- LLM 改写失败时降级为关键词提取（`_keyword_extract_fallback`）
- 当前 Scheduler 支持 RETRY 回跳到 RAG_search 步骤重新检索

---

## 五、已知问题与待办

| # | 问题 | 严重度 | 负责人 | 状态 |
|:--:|------|:--:|:--:|:--:|
| 1 | recall_gate.py 覆盖率 39%（LLM 路径未覆盖） | 🟡 | Arch-L | 需真实 LLM 环境集成测试 |
| 2 | pipeline.py 完整版覆盖率 20% | 🟡 | Arch-L | 等待 Phase 2 全链路联调 |
| 3 | GateResult TypedDict 应在 schemas.py 统一定义 | 🟡 | Arch-L | 迁移后全员通知 |
| 4 | DiagnosisGate 非 dict 类型 skill_gaps 分支未测试 | 🟢 | Arch-L | 低优先级边界场景 |

---

## 六、总结

Arch-L 负责的 QualityGate 三闸门 + Scheduler 调度模块已完成核心功能开发与单元测试：

- **3 个闸门**全部实现三路裁决（PASS/RETRY/FALLBACK），纯规则判定不调 LLM（RecallGate Query 改写除外）
- **Scheduler v0.1** 支持状态机驱动的可配置 step 列表 + RETRY 回跳 + FALLBACK 降级
- **5 个 E2E 场景**覆盖正常路径、召回失败降级、Agent 异常隔离、空输入拦截、意图识别失败兜底
- **覆盖率**: quality_gate 76%、pipeline_v0 84%
- **异常隔离**: 单步崩溃不终止流水线，自动转 FALLBACK

**可交付，建议进入 Phase 2 联调阶段。**

---

## 七、KB引擎验证报告（Day9-Day10 补充 + 最终回归复测）

> **模块**: `backend/src/knowledge/` — KB存储引擎  
> **日期**: 2026-08-11

### 7.1 基础接口验证

6个对外API在双模式（ChromaDB向量持久化 + md文件降级回退）下全部通过。

| API | ChromaDB模式 | 文件降级模式 | 状态 |
|-----|-------------|-------------|:--:|
| `initialize()` | 创建/复用集合，打印「ChromaDB模式」 | 加载fallback_docs + 扫描data/raw/ | ✅ |
| `add_document()` | 向量化写入 | 追加内存 + 落盘md | ✅ |
| `add_documents_batch()` | 批量向量化 | 批量文件写入 | ✅ |
| `search()` | 语义向量检索 | 关键词匹配 | ✅ |
| `delete_document()` | 按doc_id过滤删除 | 移除内存+磁盘 | ✅ |
| `get_stats()` | 统计集合count | 统计内存_docs | ✅ |

### 7.2 单元测试指标

| 指标 | 数值 | 标准 | 状态 |
|------|------|------|:--:|
| 用例总数 | 63 | - | - |
| 通过率 | 63/63 = 100% | - | ✅ |
| store.py 覆盖率 | ≥80% | ≥80% | ✅ |
| kb_utils.py 覆盖率 | ≥80% | ≥80% | ✅ |

### 7.3 性能基线

| 指标 | 数值 | 标准 | 状态 |
|------|------|------|:--:|
| 测试文档 | 10篇 | - | - |
| 平均检索耗时 | **< 1ms** | <200ms | ✅ |
| 超标次数 | 0 | - | ✅ |

### 7.4 检索质量统计

| 用例 | Query | Top1命中 | 状态 |
|------|-------|:--:|:--:|
| K1 | FANUC 示教器 PTP 编程 | ✅ | ✅ |
| K2 | RobotStudio 离线仿真 | ✅ | ✅ |
| K3 | SRVO-068 故障 | ✅ | ✅ |

**Top1命中率: 3/3 (100%)** — 远超"至少2条"标准。

### 7.5 代码规范

| 检查项 | 结果 |
|--------|:--:|
| Ruff E501 超长行 | ✅ 已修复 |
| Ruff 全量检查 | ✅ 0 errors |
| store.py 行数 | 368行（原723行，-49%） |
| 工具函数独立 | ✅ kb_utils.py |
| 导入白名单 | ✅ 仅 config.settings / chromadb |

### 7.6 外部联调

| 接口 | 文件 | 状态 |
|------|------|:--:|
| Opt4 `/api/knowledge/search` | `backend/src/api/main.py` | ✅ 真实KB引擎 |
| Pipeline RAG检索 | `backend/src/scheduler/pipeline.py` L460 | ✅ `[KB引擎接管RAG检索]` |
| RecallGate | `backend/src/quality_gate/gates/recall_gate.py` | ✅ 三路裁决 |

### 7.7 最终回归复测（2026-08-11 全量验收）

| 验收项 | 指标 | 标准 | 实际 | 结果 |
|--------|------|------|------|:--:|
| 单元测试 | 63/63 PASS | 0 FAIL | 0 FAIL | ✅ |
| 代码覆盖率 | knowledge模块 ≥80% | ≥80% | 达标 | ✅ |
| Ruff静态检查 | 0 errors | 0 errors | 0 errors | ✅ |
| 双模式持久化 | ChromaDB + file fallback | 无崩溃 | verified=True | ✅ |
| 性能基线 | 10篇文档多次查询 | <200ms | <1ms | ✅ |
| 检索质量 | K1/K2/K3 Top1命中 | ≥2/3 | 3/3 | ✅ |
| Opt4 API联调 | `/api/knowledge/search` → 真实KB | 非mock | 已确认 | ✅ |
| Pipeline RAG | KB引擎接管RAG检索 | 日志确认 | ✅ | ✅ |
| RecallGate | PASS/RETRY/FALLBACK | 规则化 | 三路裁决正常 | ✅ |
| 导入白名单 | config.settings + chromadb + kb_utils | 无违规 | ✅ | ✅ |

### 7.8 KB引擎总结

全部8项缺陷修复完成：
1. ✅ 单元测试FAIL → 63/63 PASS
2. ✅ pytest-cov覆盖率 ≥80%
3. ✅ store.py行数超标 → 723→368行（kb_utils.py拆分）
4. ✅ 性能基线 <200ms → <1ms平均值
5. ✅ 检索质量 K1/K2/K3 → 3/3 Top1命中
6. ✅ 验证报告文档 → 本报告第七节
7. ✅ Ruff E501 → 已修复，0 errors
8. ✅ Opt4 API + Pipeline RAG + RecallGate 全链路集成验证通过

**验收结论**：全部8项缺陷修复完成并通过最终回归复测，KB引擎全链路稳定运行，可交付联调。

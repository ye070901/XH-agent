# 人员3 — Agent 4 保真修正（与 Agent 2 同开发者）

> **角色文档版本**: v1.0  
> **创建日期**: 2026-07-28  
> **开发者**: 人员3（Agent 2 + Agent 4 同一人开发，保证 prompt 风格一致）

---

## 一、角色定位

**保真修正方**。在 Agent 2（知识生成）和 Agent 3（内容审核）完成后执行。根据事实校验报告中的错误点、知识库标准素材，修正生成内容里的事实错误和逻辑偏差，输出合规准确的个性化学习资源。

### 核心职责

| 职责 | 说明 |
|------|------|
| 事实错误修正 | 根据 FactCheckResult 中 `is_accurate=False` 的断言，逐条替换为知识库原文 |
| 逻辑偏差调整 | 概念定义不准确、因果关系颠倒等逻辑问题修正 |
| 难度匹配优化 | 根据 warning 级别 issue 调整解释深度和示例复杂度 |
| KB冲突并列 | KB中同一主题存在多个版本时，并列展示不选边 |
| 溯源重新标注 | 修正后的内容重新关联知识库来源 |
| 修正日志记录 | 每一条修正动作记录：原内容 → 修正后 → 修正依据 |

### 与 Agent 2 统一风格要求

Agent 4 与 Agent 2 由同一开发者（人员3）编写，必须满足：
- `SYSTEM_PROMPT` 常量命名方式一致：模块顶层定义
- 中文 Agent name 风格一致
- LLM 调用方式一致：通过 `self.call_llm()` / `self.call_llm_json()`
- Temperature 预设一致：修正类操作用 0.2（低温保证准确）
- Prompt 中"要求/规则"的排版格式统一

---

## 二、输入输出定义

### 2.1 输入数据

| 输入字段 | 来源 | 类型 | 说明 |
|---------|------|------|------|
| `diagnosis_result` | Agent 1 学情诊断 | `dict` | 包含 skill_gaps / recommended_difficulty / learning_style / summary |
| `generated_resources` | Agent 2 知识生成 | `list[dict]` | 原始生成的学习资源列表 |
| `audit_result` | Agent 3 事实校验 | `list[dict]` | 每份资源的审核报告（verdict / issues / fact_check） |
| `retrieved_chunks` | RAG 知识库 | `list[dict]` | 知识库检索素材（doc_id / content / relevance_score） |

### 2.2 输出数据

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `corrected_resources` | `list[dict]` | 修正后的学习资源列表，结构与 GeneratedResource 一致 |
| `correction_log` | `list[dict]` | 每条修正日志：resource_id / issue_index / original_text / corrected_text / correction_basis |
| `correction_stats` | `dict` | 修正统计：total_issues / errors_fixed / warnings_addressed / infos_applied |

### 2.3 state 键名声明（对齐 BaseAgent）

```python
REQUIRED_STATE_KEYS = {"generated_resources", "audit_result", "diagnosis_result"}
OPTIONAL_STATE_KEYS = {"retrieved_chunks", "learner_data", "task_id", "agent_log", "status"}
```

---

## 三、依赖关系

### 3.1 执行前置依赖

```
Agent 1 (学情诊断) ──┐
                     ├──► Agent 2 (知识生成) ──┐
RAG 知识库 ──────────┘                        ├──► Agent 3 (事实校验) ──► Agent 4 (保真修正)
                                               │
                              Agent 2 生成内容 ─┘
```

**关键时序**：Agent 4 必须等待 Agent 2 生成完成 **且** Agent 3 审核完成后才能启动。

### 3.2 被谁依赖

- **人员1（编排器）**：编排器在 Agent 3 审核完成后调用 Agent 4 修正
- **人员4（辩论引擎）**：博弈阶段如有争议，Agent 4 作为修正方参与

### 3.3 依赖谁

| 依赖方 | 提供内容 |
|--------|---------|
| 人员2 → Agent 1 | 学情诊断结果（diagnosis_result） |
| 人员3 → Agent 2 | 原始生成的学习资源（generated_resources） |
| 人员4 → Agent 3 | 事实校验报告（audit_result / FactCheckResult） |
| 人员4 → RAG 检索 | 知识库原文素材（retrieved_chunks） |

---

## 四、执行流程

### 4.1 整体流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent 4 保真修正流程                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ① 输入校验                                                   │
│     ├─ generated_resources 非空检查                            │
│     ├─ audit_result 数量与 generated_resources 对齐检查         │
│     └─ retrieved_chunks 兜底（空列表不阻断）                    │
│                                                               │
│  ② 逐资源处理（循环 generated_resources[i]）                   │
│     ├─ 2.1 找到匹配的 audit_result[i]                         │
│     ├─ 2.2 提取 issues 按 severity 分级                        │
│     │      ├─ error   → 必须修正（查 KB 原文替换）              │
│     │      ├─ warning → 尽量修正（调整解释深度、补充示例）       │
│     │      └─ info    → 可选修正（改进建议酌情采纳）             │
│     ├─ 2.3 构建修正 prompt                                    │
│     │      ├─ system_prompt: 模块顶层 SYSTEM_PROMPT            │
│     │      └─ user_message: 原始内容 + 审核问题 + KB素材        │
│     ├─ 2.4 调用 LLM 生成修正后内容                             │
│     └─ 2.5 记录修正日志（逐条追踪）                             │
│                                                               │
│  ③ 输出汇总                                                   │
│     ├─ corrected_resources: 修正后的完整资源列表                │
│     ├─ correction_log: 逐条修正记录                            │
│     └─ correction_stats: 修正统计                              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 修正策略矩阵

| issue.severity | 策略 | 操作 | 示例 |
|---------------|------|------|------|
| **error** | 必须改 | 查 KB 原文，用正确内容替换错误断言 | `"LangGraph 是 Google 开发的"` → `"LangGraph 由 LangChain 团队开发"` |
| **warning** | 尽量改 | 调整解释深度、补充细节、对齐难度 | 难度标注 `advanced` 但内容像 `beginner` → 增加技术深度 |
| **info** | 可选改 | 改进建议酌情采纳，不削足适履 | "建议多加一个比喻" → 不影响准确性则采纳 |

### 4.3 关键约束

1. **只改有问题的部分**：禁止重写整个资源，保留原内容中正确的部分
2. **修改后重新标注来源**：修正涉及的内容重新关联 `citation`，标注 `[来源: {doc_id}]`
3. **KB 冲突内容并列不选边**：同一主题在 KB 中存在多版本描述时，以 "说法A / 说法B" 并列呈现
4. **修正后不引入新事实断言**：无 KB 支撑的内容标记 `[暂无权威参考，建议补充学习]`
5. **降级模式兼容**：`state["downgrade_mode"] = True` 时，修正提示词强调"无 KB 时只做一致性修正，不做事实判断"

---

## 五、数据流契约

### 5.1 correction_log 单条记录格式

```python
{
    "resource_id": "uuid",
    "resource_type": "lecture",
    "issue_index": 0,            # 对应 audit_result[i].issues[j]
    "severity": "error",         # 原始 issue 级别
    "original_text": "修正前的错误文本片段",
    "corrected_text": "修正后的正确文本片段",
    "correction_basis": "knowledge_base | consistency_check | difficulty_adjust",
    "kb_source": "doc_rag_guide.md @ chunk_3",  # 仅 knowledge_base 时有
    "action": "replaced | adjusted | accepted",
}
```

### 5.2 correction_stats 格式

```python
{
    "total_resources": 3,
    "resources_corrected": 2,    # 至少有一处修正的资源数
    "total_issues": 5,
    "errors_fixed": 3,
    "warnings_addressed": 1,
    "infos_applied": 1,
    "correction_time_ms": 4200,
}
```

---

## 六、交付物清单

| 文件 | 路径 | 说明 |
|------|------|------|
| Agent 4 类 | `backend/src/agents/correction.py` | `CorrectionAgent(BaseAgent)`，含 `SYSTEM_PROMPT` + `run()` |
| 角色文档 | `docs/roles/phase2/person4-agent4.md` | 本文档 |
| 编排器更新 | `backend/src/graph/orchestrator.py` | 新增 Step 4 调用 Agent 4 |
| 配置更新 | `backend/src/config.py` | 新增 Agent 4 的模型/温度配置 |
| API 更新 | `backend/src/api/main.py` | 返回结果新增 corrected_resources 字段 |

---

## 七、验收标准

- [ ] Agent 4 对 `error` 级别 issue 修正率 ≥ 90%（修正后 Agent 3 再审 error=0）
- [ ] Agent 4 修正不引入新的 error（修正前后误差对比：新 error 数 ≤ 0）
- [ ] 冲突 KB 内容并列展示不自动选边
- [ ] 修正后内容每条技术断言 ≥ 80% 有来源标注
- [ ] `correction_log` 记录完整，每条修正可追踪到原始 issue
- [ ] 降级模式下正常切换修正策略（不依赖 KB）
- [ ] 3 种资源类型（lecture/guide/quiz）均能正常修正

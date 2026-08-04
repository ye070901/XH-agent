# 三级 Agent 流水线设计文档（Gate Protocol 对齐）

> 版本：v1.0 · 更新时间：2026-08-04
> 适用范围：学情诊断系统，三级 Agent 流水线。
> 读者对象：对接方架构人员。本文档定义流水线整体架构、Gate 链路流转规则、三个 Agent 的独立 System Prompt 与输入/输出 JSON Schema。
> 关联文档：[EventBus_Design.md](EventBus_Design.md)（本流水线所有运行时事件经该事件总线发布）。

---

## 0. Gate Protocol 协议声明（必读）

**声明**：项目与公开渠道均无「Arch-L Gate Protocol」规范原文。本文档按业界通用 **Gate 流水线**约定定义一套显式的协议（下称 **Gate Protocol v1**，协议标识 `arch-l.gate/v1`），并全文对齐该协议。**若后续拿到 Arch-L 官方规范，只需修订本节协议假设并全局替换协议标识，其余章节（Agent Prompt、JSON Schema）无需大改。**

### 0.1 协议核心假设

| # | 协议规则 | 说明 |
|---|----------|------|
| R1 | **一个 Agent = 一道 Gate** | 流水线由若干 Gate 顺序/条件衔接组成；Gate 之间不直接通信 |
| R2 | **Gate 唯一入口/出口校验** | 每个 Gate 必须通过 `Gate-in`（输入校验）与 `Gate-out`（输出校验）才能放行 |
| R3 | **交接文档（Handoff Packet）是 Gate 间唯一通信载体** | 结构化 JSON，含协议头 `gate_header` + 领域负载 `payload`（见 2.5） |
| R4 | **失败必须携带结构化原因** | 任何校验失败以 `REJECTED` + `reject_reason`（结构化）返回，禁止静默失败 |
| R5 | **拒绝分两类：`rework`（打回上流重做）与 `reject`（终止/升级）** | `rework` 附带 `revise_hints` 供上流整改 |
| R6 | **重做有预算上限** | 单份产物的 `rework` 轮数 ≤ 2（`RETRY_BUDGET=2`），超限强制升级人工 |
| R7 | **所有 Gate 状态迁移必须发事件** | 事件格式严格遵循 [EventBus_Design.md](EventBus_Design.md) 第 1 章统一消息格式 |
| R8 | **LLM 输出只信任校验后的结果** | Gate-out 校验通过才可写入状态与交接，绝不将原始 LLM 文本直接透传下游 |
| R9 | **终态可判定** | 流水线对任何输入都收敛到唯一终态：`DONE` / `REJECTED` / `ESCALATED` |

### 0.2 Gate 生命周期状态机

```
                    ┌────────────── Gate-in ──────────────┐
                    │  (协议头 + 输入 Schema 校验)         │
  CREATED ──────► GATE_IN ──(通过)──► EXECUTING ──► GATE_OUT
                    │                     ▲  retry      │ (输出 Schema 校验)
               (失败│R4)                  │              │
                    ▼                     │              ▼
               REJECTED(reject_reason)◄───┴───────── HANDOFF ──► DONE
                 │    ▲                                        ▲
                 │    └── rework: 回上游 EXECUTING ──┐         │
                 └── reject: 终止 / ESCALATED(超预算) └─────────┘
```

| 状态 | 含义 | 触发 |
|------|------|------|
| `CREATED` | 流水线初始化，生成 `run_id` | 编排器收到任务 |
| `GATE_IN` | 校验 Gate 输入 | 每进入一道 Gate |
| `EXECUTING` | Agent 调用 LLM 执行 | Gate-in 通过 |
| `GATE_OUT` | 校验 Gate 输出 | Agent 返回原始输出 |
| `HANDOFF` | 生成交接文档传给下一 Gate | Gate-out 通过 |
| `REJECTED` | 校验失败，`action=rework/reject` | Gate-in/Gate-out 失败 |
| `DONE` / `ESCALATED` | 终态 | 全链路放行 / 超预算升级 |

---

## 1. 总体架构

### 1.1 三级流水线

```
                    ┌──────────────────────────────────────────────┐
                    │              编排器 / 网关控制器               │
                    │  run_id · 状态 · 重试预算 · 校验 · 事件发布     │
                    └──────┬──────────────┬──────────────┬─────────┘
                           │ Gate-in      │ Gate-in      │ Gate-in
                           ▼              ▼              ▼
                   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                   │  G1 诊断 Gate │→│  G2 方案 Gate │→│  G3 审核 Gate │
                   │  Diagnosis    │→│  Plan        │→│  Review      │
                   └──────────────┘ └──────────────┘ └──────┬───────┘
                    handoff(v1)     handoff(v1)             │
                                      approve ─────────────► 最终交付 learning_plan
                                                      rework ──► 回 G2 重做（携带 revise_hints，≤2轮）
                                                      reject ──► 终止 / 升级人工
```

### 1.2 职责划分

| 组件 | 职责 |
|------|------|
| 编排器（Gate Controller） | 维护 `run_id`、全局状态、重试预算；执行 Gate-in/Gate-out 校验；驱动 Gate 状态机；发布事件；决定 rework/reject/升级 |
| **G1 DiagnosisAgent**（学情诊断） | 输入 `learner_data` → 输出 `diagnosis_result`（知识点掌握、技能短板、建议） |
| **G2 PlanAgent**（学习方案生成） | 输入 `learner_data + diagnosis_result` → 输出 `learning_plan`（阶段计划、周计划、资源、评估、风险控制） |
| **G3 ReviewAgent**（内容审核） | 输入 `learner_data + diagnosis_result + learning_plan` → 输出 `review_report`（verdict/score/issues/revise_hints） |
| EventBus | 承载所有 Gate 状态事件（见 [EventBus_Design.md](EventBus_Design.md)） |

### 1.3 数据流（单次全链路）

1. 编排器生成 `run_id`，封装 `learner_data` → **G1 Gate-in**。
2. G1 输出 `diagnosis_result` → 通过 Gate-out → 构造 Handoff#1 → **G2 Gate-in**。
3. G2 输出 `learning_plan` → 通过 Gate-out → 构造 Handoff#2 → **G3 Gate-in**。
4. G3 输出 `review_report`：
   - `verdict=approve` → 流水线 `DONE`，交付 `approved_plan`。
   - `verdict=rework` → 将 `revise_hints` 追加进 G2 的 Prompt，重做（≤2 轮）。
   - `verdict=reject` 或重做超预算 → 流水线 `REJECTED`/`ESCALATED`，升级人工。

---

## 2. 链路流转规则（分模块）

### 模块 A：编排器 / 网关控制器

**职责**：全链路驱动与校验。以下规则对所有 Gate 统一生效。

- **A1（Gate-in 校验）**：进入任意 Gate 前，用该 Gate 的 Input Schema 校验交接 `payload`。失败 → 置 `REJECTED`，`reject_reason={gate, stage:"gate_in", errors:[...]}`，发布 `*.failed` 事件，不调用 LLM。
- **A2（执行）**：调用对应 Agent 的 `run(payload)`，原始输出先不进状态。
- **A3（Gate-out 校验）**：用该 Gate 的 Output Schema 校验 Agent 原始输出。失败 → 置 `REJECTED`，`reject_reason={gate, stage:"gate_out", errors:[...]}`，发布 `*.failed` 事件；LLM 原始文本按 R8 绝不透传。
- **A4（结构化输出兜底）**：Gate-out 校验失败若源于 JSON 解析（非语义错误），允许**自动修复 1 次**（将解析错误回注 Prompt 重跑），仍失败则按 A3 拒绝。
- **A5（重做预算）**：`rework` 轮数由编排器计数（记于 `run_id` 作用域）。超 `RETRY_BUDGET=2` → `ESCALATED`，升级人工。
- **A6（状态管理）**：编排器维护 `{run_id, current_gate, retry_round, state_payloads, final_status}`；Gate 之间不共享内存，只通过交接文档传数据。

### 模块 B：G1 学情诊断 Gate

| 项 | 规则 |
|----|------|
| Gate-in | 校验 `learner_data`（Schema 见 4.1），必含 `learner_id`、`background`、`learning_goal` |
| 执行 | 运行 Agent1（Prompt 见 3.1），读取交接 `payload.learner_data` |
| Gate-out | 校验 `diagnosis_result`：`knowledge_map` ≥ 5 条、每条含 evidence、mastery∈[0,1]、priority 合法 |
| 放行条件 | 通过 Gate-out → Handoff#1 传给 G2；发布 `agent.diagnosis.completed` |
| 失败处理 | Gate-in/Gate-out 失败 → `agent.diagnosis.failed`；`reject_reason` 携带具体错误 |

**与现有实现的关系**：`agents/diagnosis.py` 的 `DiagnosisAgent` 已实现 G1 的输出 Schema 与校验逻辑，接入本协议只需：包装 Gate-in/Gate-out 校验 + 发布事件（见第 5 章）。

### 模块 C：G2 学习方案生成 Gate

| 项 | 规则 |
|----|------|
| Gate-in | 校验 `{learner_data, diagnosis_result}`（Schema 见 4.2） |
| 执行 | 运行 Agent2（Prompt 见 3.2），输入含 G1 交接全文 + 本次 `revise_hints`（rework 时注入） |
| Gate-out | 校验 `learning_plan`：`stages` ≥ 3、每阶段含 pass_criteria、`weekly_schedule` 周学时 ≤ 1.2×`avg_hours_per_week` |
| 放行条件 | 通过 Gate-out → Handoff#2 传给 G3；发布 `agent.plan.completed` |
| rework 入口 | 收到 G3 的 `revise_hints` 时：`retry_round+1`，将 hints 追加进 Prompt 重跑，`retry_round > 2` 则升级 |

### 模块 D：G3 内容审核 Gate

| 项 | 规则 |
|----|------|
| Gate-in | 校验 `{learner_data, diagnosis_result, learning_plan}`（Schema 见 4.3） |
| 执行 | 运行 Agent3（Prompt 见 3.3），按 6 个审核维度打分并给出 issues |
| Gate-out | 校验 `review_report`：`verdict∈{approve,rework,reject}`；`verdict=approve` 时 `approved_plan` 必须非空；`score∈[0,100]` |
| 审核决策规则 | 存在 critical issue → `reject`；≥2 个 major → `rework`；否则 `approve`（该规则在 Prompt 与 Gate-out 双重约束） |
| 输出分支 | approve → 流水线 `DONE`，交付 `approved_plan`；rework → 回 G2；reject → 终止并升级 |

### 模块 E：交接文档（Handoff Packet）与事件对接

**交接文档是 Gate 间唯一通信载体（R3）**，结构如下：

```json
{
  "gate_header": {
    "protocol": "arch-l.gate/v1",
    "run_id": "9f3a...（UUID4，全链路唯一）",
    "from_gate": "G1:agents.diagnosis.DiagnosisAgent",
    "to_gate": "G2:agents.plan.PlanAgent",
    "handoff_ts": "2026-08-04T03:15:27.123456Z",
    "retry_round": 0
  },
  "payload": {
    "learner_data": { "...": "见 4.1" },
    "diagnosis_result": { "...": "见 4.2" }
  }
}
```

**事件映射（对齐 EventBus 统一消息格式：`event_type` / `payload` / `timestamp` / `source`）**：

| 阶段 | event_type | payload 关键字段 |
|------|-----------|------------------|
| G1 开始 | `agent.diagnosis.started` | `run_id`, `learner_id` |
| G1 通过 | `agent.diagnosis.completed` | `run_id`, `learner_id`, `diagnosis_result` |
| G1 失败 | `agent.diagnosis.failed` | `run_id`, `learner_id`, `reject_reason` |
| G2 开始 | `agent.plan.started` | `run_id`, `learner_id`, `retry_round` |
| G2 通过 | `agent.plan.completed` | `run_id`, `learner_id`, `learning_plan` |
| G3 通过 | `agent.review.approved` | `run_id`, `learner_id`, `approved_plan` |
| G3 打回 | `agent.review.reworked` | `run_id`, `learner_id`, `revise_hints` |
| G3 拒绝 | `agent.review.rejected` | `run_id`, `learner_id`, `issues` |
| 升级人工 | `system.pipeline.escalated` | `run_id`, `reason` |

> 依据 [EventBus_Design.md](EventBus_Design.md) 第 1.3 节规则「新增事件必须向事件表登记」，`agent.plan.*` / `agent.review.*` / `system.pipeline.*` 为本流水线新增登记项。

### 模块 F：异常、重试与升级

| 场景 | 处理规则 | 事件 |
|------|----------|------|
| Gate-in 校验失败 | 立即拒绝，不调用 LLM（A1） | `*.failed` |
| Gate-out 校验失败 | 自动修复 1 次（A4），仍失败则拒绝 | `*.failed` |
| LLM 网络/超时异常 | 重试 2 次（指数退避），仍失败 → 拒绝 | `*.failed` |
| G3 rework | 回 G2 重做，`retry_round+1`，注入 `revise_hints` | `agent.review.reworked` |
| rework 超预算（>2） | 升级人工 | `system.pipeline.escalated` |
| G3 reject | 终止，升级人工 | `agent.review.rejected` |
| 进程崩溃 | 依据 EventBus 持久化日志重放（见 EventBus 文档 4.5） | — |

---

## 3. 各 Agent 独立 System Prompt

> 三个 Prompt 均为可直接复制进 Agent 定义的完整文本。输入均从交接文档 `payload` 读取，输出均仅允许纯 JSON（R8：LLM 原始输出必须通过 Gate-out 校验才可信）。

### 3.1 Agent1 — 学情诊断（G1）

> 与 `agents/diagnosis.py` 的 `SYSTEM_PROMPT` 一致（同源），此处给出 Gate Protocol 语境下的正式版。

```
你是一位资深的学情诊断专家。你的任务是基于学习者的背景和学习数据，输出结构化学情诊断报告。

## 输入输出规约
- 输入: 从交接文档 payload["learner_data"] 读取学习者信息
- 输出: 写入 diagnosis_result，仅输出纯 JSON，禁止任何多余文字

## 输出 JSON 结构
{
  "knowledge_map": [
    {
      "name": "知识点名称",
      "mastery": 0.0~1.0,
      "level": "未掌握"|"初步了解"|"基本掌握"|"熟练应用"|"融会贯通",
      "confidence": 0.0~1.0,
      "evidence": ["证据1", "证据2"],
      "priority": "critical"|"high"|"medium"|"low"
    }
  ],
  "skill_gaps": [
    {
      "skill": "技能名称",
      "severity": "高"|"中"|"低",
      "description": "缺失描述",
      "prerequisite_for": ["依赖此前置知识的高级技能1", "依赖此前置知识的高级技能2"]
    }
  ],
  "overall_assessment": "综合诊断结论",
  "recommendations": ["建议1", "建议2", "建议3"]
}

## 知识图谱规则 (knowledge_map)
1. 知识点数量必须 ≥ 5 个
2. 每个知识点必须附带至少 1 条 evidence（从输入数据中提取的具体证据）
3. mastery 反映掌握程度，0.0=完全未掌握，1.0=完全掌握
4. level 根据 mastery 映射：0.0~0.2=未掌握，0.2~0.4=初步了解，0.4~0.6=基本掌握，0.6~0.8=熟练应用，0.8~1.0=融会贯通
5. 每条知识点必须包含以下四个字段：level、confidence、evidence、priority
6. priority=critical 的定义：不掌握该知识点，后续相关学习无法开展的前置基础依赖
7. 知识点名称命名格式必须为：`{具体技术} - {子方向}`，例如 `LangGraph - 条件路由与动态分支`。禁止使用宽泛表述如 "AI基础"、"深度学习"

## 技能短板规则 (skill_gaps)
1. 仅列出前置依赖短板 —— 即那些影响后续学习的关键缺失技能
2. 不得罗列所有未学内容 —— 只筛选出构成瓶颈的前置技能
3. 每条短板必须标注 severity（高/中/低）和 prerequisite_for（阻塞了哪些高级技能的学习）

## 综合建议规则 (recommendations)
1. 至少 3 条，针对知识短板和技能缺口给出可操作的学习路径建议
2. 建议要具体，与诊断结果一一对应

## 输出格式强制规则
1. 学习建议字符串内若含有序号，必须使用单层序号（1.、2.、3.），禁止使用二级序号（1.1、2.2 等）

## 知识盲区约束
1. 识别出的知识盲区必须精确到具体技术点，禁止宽泛描述
   - ❌ 错误示例："AI基础"
   - ✅ 标准示例："Transformer自注意力机制"
2. 盲区统一命名格式：`{具体技术} - {子方向}`，例如 `LangGraph - 条件路由与动态分支`
```

### 3.2 Agent2 — 学习方案生成（G2）

```
你是一位资深的学习方案设计专家。基于学情诊断报告，为学习者生成一份可执行、可审核的学习方案。

## 输入
从交接文档 payload 读取：
- learner_data: 学习者画像（背景、目标、学习历史、测验、学习时间、困难点）
- diagnosis_result: 学情诊断结果（knowledge_map、skill_gaps、overall_assessment、recommendations）
- 若上下文附有 revise_hints（上轮审核打回的整改指令），必须逐条落实并消除对应问题

## 输出规约
仅输出纯 JSON，禁止任何多余文字，结构严格遵循：
{
  "plan_id": "字符串，本次方案唯一标识",
  "objective": "方案总体目标（与 learning_goal 对齐）",
  "duration_weeks": 周数,
  "stages": [
    {
      "stage_name": "阶段名",
      "duration_weeks": 周数,
      "objectives": ["本阶段目标"],
      "kp_targets": ["对应知识点（沿用 {具体技术} - {子方向} 命名）"],
      "tasks": ["具体任务"],
      "materials": ["学习材料"],
      "pass_criteria": ["本阶段通过标准"]
    }
  ],
  "weekly_schedule": [
    {"week": 1, "focus": "本周重点", "tasks": ["任务"], "estimated_hours": 小时数}
  ],
  "resources": [{"title": "资源名", "type": "教程|文档|视频|练习|项目", "url": "可选", "relevance": "与本方案的相关性"}],
  "evaluation_methods": [{"method": "评估方式", "frequency": "频率", "success_criterion": "合格标准"}],
  "risk_controls": [{"risk": "风险", "mitigation": "应对措施", "owner": "可选责任人"}]
}

## 规则
1. stages 数量必须 ≥ 3，必须覆盖 diagnosis_result 中所有 priority=critical/high 且 mastery<0.6 的知识点
2. 阶段顺序必须符合前置依赖：先补齐 skill_gaps 中的前置技能，再安排进阶知识点（遵守 prerequisite_for）
3. 可行性约束：weekly_schedule 每周 estimated_hours 之和不得超过 learner_data.study_time.avg_hours_per_week 的 1.2 倍
4. 每个阶段必须给出可量化的 pass_criteria，供审核 Gate 与学习者自检使用
5. 必须针对 learner_data.struggles 中的每一条具体困难，在 risk_controls 中给出针对性 mitigation
6. 知识点名称沿用诊断报告命名格式 `{具体技术} - {子方向}`，禁止宽泛表述
7. 字符串内序号一律使用单层序号（1.、2.），禁止二级序号（1.1、2.2）
8. objective 必须与 learner_data.learning_goal 语义一致，不得擅自更换目标

## 输出格式强制规则
仅输出 JSON，禁止 markdown 代码块包裹、禁止任何解释文字。
```

### 3.3 Agent3 — 内容审核（G3）

```
你是一位严格的内容审核专家，担任学习方案流水线的质量把关 Gate。你的职责是按既定维度审核学习方案的合理性与安全性，给出结构化审核结论。

## 输入
从交接文档 payload 读取：
- learner_data: 学习者画像
- diagnosis_result: 学情诊断结果
- learning_plan: 待审核的学习方案（G2 产物）

## 审核维度（逐条检查）
1. 覆盖度对齐：learning_plan 是否覆盖 diagnosis_result 中所有 priority=critical/high 且 mastery<0.6 的知识点；遗漏 → critical
2. 前置依赖正确性：阶段顺序是否符合 skill_gaps.prerequisite_for 依赖；存在前置倒置 → critical
3. 可行性：weekly_schedule 每周学时是否超过 learner_data.study_time.avg_hours_per_week 的 1.2 倍；超限 → critical
4. 具体性：是否存在"学习基础""多练习"等宽泛、不可执行的内容；存在 → major
5. 风险控制：learner_data.struggles 中每条困难是否都有对应 mitigation；缺失 → major
6. 一致性与安全性：objective 是否与 learning_goal 一致、材料来源是否合理；不一致 → major

## 输出规约
仅输出纯 JSON，禁止任何多余文字，结构严格遵循：
{
  "verdict": "approve"|"rework"|"reject",
  "score": 0~100 的整数，
  "issues": [
    {"severity": "critical"|"major"|"minor", "scope": "问题所在部分（如 stage 名称/字段）", "description": "问题描述", "recommendation": "改进建议"}
  ],
  "revise_hints": ["给 G2 的可执行整改指令，逐条对应 issue"],
  "approved_plan": 学习方案对象或 null
}

## verdict 判定规则（必须遵守）
1. 存在任一 critical issue → verdict=reject，approved_plan=null
2. 存在 ≥2 个 major issue → verdict=rework，approved_plan=null
3. 其余情况 → verdict=approve，approved_plan 填 learning_plan 原样返回
4. revise_hints 必须为可执行的整改指令（明确指出改哪一部分、改成什么），approve 时为空数组

## 输出格式强制规则
仅输出 JSON，禁止 markdown 代码块包裹、禁止任何解释文字。
```

---

## 4. 各 Agent 输入 / 输出 JSON Schema

> 采用 JSON Schema draft-07。Gate-in / Gate-out 校验严格以本表 Schema 为准（模块 A 的 A1/A3 规则）。

### 4.1 Agent1（G1）

**Input** — `$id: arch-l.gate/agent1.input/v1`（对象 `learner_data`）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["learner_id", "background", "learning_goal"],
  "properties": {
    "learner_id": { "type": "string" },
    "name": { "type": "string" },
    "age": { "type": "integer", "minimum": 0, "maximum": 120 },
    "education": { "type": "string" },
    "background": { "type": "string", "minLength": 1 },
    "learning_goal": { "type": "string", "minLength": 1 },
    "current_course": { "type": "string" },
    "learning_history": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["topic", "status", "score"],
        "properties": {
          "topic": { "type": "string" },
          "status": { "type": "string", "enum": ["未开始", "学习中", "已完成"] },
          "score": { "type": "number", "minimum": 0, "maximum": 100 }
        }
      }
    },
    "quiz_results": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "score", "total"],
        "properties": {
          "name": { "type": "string" },
          "score": { "type": "number", "minimum": 0 },
          "total": { "type": "number", "minimum": 1 }
        }
      }
    },
    "study_time": {
      "type": "object",
      "properties": {
        "total_hours": { "type": "number", "minimum": 0 },
        "weeks": { "type": "number", "minimum": 0 },
        "avg_hours_per_week": { "type": "number", "minimum": 0 }
      }
    },
    "struggles": { "type": "array", "items": { "type": "string" } }
  }
}
```

**Output** — `$id: arch-l.gate/agent1.output/v1`（对象 `diagnosis_result`）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["knowledge_map", "skill_gaps", "overall_assessment", "recommendations"],
  "properties": {
    "knowledge_map": {
      "type": "array",
      "minItems": 5,
      "items": {
        "type": "object",
        "required": ["name", "mastery", "level", "confidence", "evidence", "priority"],
        "properties": {
          "name": { "type": "string" },
          "mastery": { "type": "number", "minimum": 0, "maximum": 1 },
          "level": { "type": "string", "enum": ["未掌握", "初步了解", "基本掌握", "熟练应用", "融会贯通"] },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
          "evidence": { "type": "array", "minItems": 1, "items": { "type": "string" } },
          "priority": { "type": "string", "enum": ["critical", "high", "medium", "low"] }
        }
      }
    },
    "skill_gaps": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["skill", "severity", "description", "prerequisite_for"],
        "properties": {
          "skill": { "type": "string" },
          "severity": { "type": "string", "enum": ["高", "中", "低"] },
          "description": { "type": "string" },
          "prerequisite_for": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "overall_assessment": { "type": "string" },
    "recommendations": { "type": "array", "minItems": 3, "items": { "type": "string" } }
  }
}
```

### 4.2 Agent2（G2）

**Input** — `$id: arch-l.gate/agent2.input/v1`（交接对象）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["learner_data", "diagnosis_result"],
  "properties": {
    "learner_data": { "$ref": "arch-l.gate/agent1.input/v1" },
    "diagnosis_result": { "$ref": "arch-l.gate/agent1.output/v1" }
  }
}
```

**Output** — `$id: arch-l.gate/agent2.output/v1`（对象 `learning_plan`）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["plan_id", "objective", "duration_weeks", "stages", "weekly_schedule", "resources", "evaluation_methods", "risk_controls"],
  "properties": {
    "plan_id": { "type": "string" },
    "objective": { "type": "string" },
    "duration_weeks": { "type": "integer", "minimum": 1 },
    "stages": {
      "type": "array",
      "minItems": 3,
      "items": {
        "type": "object",
        "required": ["stage_name", "duration_weeks", "objectives", "kp_targets", "tasks", "pass_criteria"],
        "properties": {
          "stage_name": { "type": "string" },
          "duration_weeks": { "type": "integer", "minimum": 1 },
          "objectives": { "type": "array", "minItems": 1, "items": { "type": "string" } },
          "kp_targets": { "type": "array", "items": { "type": "string" } },
          "tasks": { "type": "array", "items": { "type": "string" } },
          "materials": { "type": "array", "items": { "type": "string" } },
          "pass_criteria": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "weekly_schedule": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["week", "focus", "estimated_hours"],
        "properties": {
          "week": { "type": "integer", "minimum": 1 },
          "focus": { "type": "string" },
          "tasks": { "type": "array", "items": { "type": "string" } },
          "estimated_hours": { "type": "number", "minimum": 0 }
        }
      }
    },
    "resources": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "type"],
        "properties": {
          "title": { "type": "string" },
          "type": { "type": "string", "enum": ["教程", "文档", "视频", "练习", "项目"] },
          "url": { "type": "string" },
          "relevance": { "type": "string" }
        }
      }
    },
    "evaluation_methods": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["method", "frequency", "success_criterion"],
        "properties": {
          "method": { "type": "string" },
          "frequency": { "type": "string" },
          "success_criterion": { "type": "string" }
        }
      }
    },
    "risk_controls": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["risk", "mitigation"],
        "properties": {
          "risk": { "type": "string" },
          "mitigation": { "type": "string" },
          "owner": { "type": "string" }
        }
      }
    }
  }
}
```

### 4.3 Agent3（G3）

**Input** — `$id: arch-l.gate/agent3.input/v1`（交接对象）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["learner_data", "diagnosis_result", "learning_plan"],
  "properties": {
    "learner_data": { "$ref": "arch-l.gate/agent1.input/v1" },
    "diagnosis_result": { "$ref": "arch-l.gate/agent1.output/v1" },
    "learning_plan": { "$ref": "arch-l.gate/agent2.output/v1" }
  }
}
```

**Output** — `$id: arch-l.gate/agent3.output/v1`（对象 `review_report`）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["verdict", "score", "issues", "revise_hints", "approved_plan"],
  "properties": {
    "verdict": { "type": "string", "enum": ["approve", "rework", "reject"] },
    "score": { "type": "integer", "minimum": 0, "maximum": 100 },
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["severity", "scope", "description"],
        "properties": {
          "severity": { "type": "string", "enum": ["critical", "major", "minor"] },
          "scope": { "type": "string" },
          "description": { "type": "string" },
          "recommendation": { "type": "string" }
        }
      }
    },
    "revise_hints": { "type": "array", "items": { "type": "string" } },
    "approved_plan": { "$ref": "arch-l.gate/agent2.output/v1" }
  }
}
```

### 4.4 Gate 校验要点速查

| Gate | Gate-in 必查 | Gate-out 必查 |
|------|--------------|---------------|
| G1 | `learner_id`/`background`/`learning_goal` 非空 | `knowledge_map`≥5 且有 evidence；mastery/confidence∈[0,1]；priority 枚举合法 |
| G2 | `diagnosis_result` 通过 agent1.output | `stages`≥3 且有 pass_criteria；周学时 ≤1.2×avg_hours_per_week |
| G3 | `learning_plan` 通过 agent2.output | `verdict` 枚举合法；approve 时 `approved_plan` 非空；score∈[0,100] |

---

## 5. 对接示例

### 5.1 编排器骨架（对齐 Gate 状态机）

```python
from backend.base import BaseAgent
from agents.diagnosis import DiagnosisAgent
# PlanAgent / ReviewAgent 需按 3.2 / 3.3 的 Prompt 新建（继承 BaseAgent）
from event_bus import publish  # 见 EventBus_Design.md

RETRY_BUDGET = 2


def validate(data, schema) -> list[str]:
    """Gate-in / Gate-out 校验：返回错误列表，空列表=通过。"""
    import jsonschema
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(data))
    return [f"{e.json_path}: {e.message}" for e in errors]


def run_pipeline(learner_data: dict) -> dict:
    run_id = uuid4()
    retry_round = 0

    # ── Gate G1: 诊断 ────────────────────────────────
    errs = validate(learner_data, AGENT1_INPUT)
    if errs:
        publish("agent.diagnosis.failed", {"run_id": run_id, "reject_reason": errs}, source="orchestrator")
        return {"status": "REJECTED", "gate": "G1", "stage": "gate_in", "reject_reason": errs}

    publish("agent.diagnosis.started", {"run_id": run_id, "learner_id": learner_data["learner_id"]}, source="orchestrator")
    state = DiagnosisAgent().run({"learner_data": learner_data})
    diagnosis_result = state.get("diagnosis_result", {})

    errs = validate(diagnosis_result, AGENT1_OUTPUT)
    if errs:
        publish("agent.diagnosis.failed", {"run_id": run_id, "reject_reason": errs}, source="orchestrator")
        return {"status": "REJECTED", "gate": "G1", "stage": "gate_out", "reject_reason": errs}
    publish("agent.diagnosis.completed", {"run_id": run_id, "diagnosis_result": diagnosis_result}, source="orchestrator")

    # ── Gate G2: 方案生成（含 rework 循环） ─────────────
    plan = None
    while retry_round <= RETRY_BUDGET:
        gate_in = {"learner_data": learner_data, "diagnosis_result": diagnosis_result, "revise_hints": revise_hints}
        errs = validate({"learner_data": gate_in["learner_data"], "diagnosis_result": gate_in["diagnosis_result"]}, AGENT2_INPUT)
        if errs:
            return {"status": "REJECTED", "gate": "G2", "stage": "gate_in", "reject_reason": errs}

        publish("agent.plan.started", {"run_id": run_id, "retry_round": retry_round}, source="orchestrator")
        state = PlanAgent().run(gate_in)
        plan = state.get("learning_plan")

        errs = validate(plan, AGENT2_OUTPUT)
        if errs:
            publish("agent.plan.failed", {"run_id": run_id, "reject_reason": errs}, source="orchestrator")
            return {"status": "REJECTED", "gate": "G2", "stage": "gate_out", "reject_reason": errs}

        # ── Gate G3: 审核 ────────────────────────────────
        report = ReviewAgent().run({"learner_data": learner_data,
                                    "diagnosis_result": diagnosis_result,
                                    "learning_plan": plan}).get("review_report")
        errs = validate(report, AGENT3_OUTPUT)
        if errs:
            publish("agent.review.failed", {"run_id": run_id, "reject_reason": errs}, source="orchestrator")
            return {"status": "REJECTED", "gate": "G3", "stage": "gate_out", "reject_reason": errs}

        if report["verdict"] == "approve":
            publish("agent.review.approved", {"run_id": run_id, "approved_plan": report["approved_plan"]}, source="orchestrator")
            return {"status": "DONE", "run_id": run_id, "approved_plan": report["approved_plan"]}

        if report["verdict"] == "reject":
            publish("agent.review.rejected", {"run_id": run_id, "issues": report["issues"]}, source="orchestrator")
            return {"status": "REJECTED", "gate": "G3", "reason": report["issues"]}

        # verdict == "rework"
        retry_round += 1
        revise_hints = report["revise_hints"]
        publish("agent.review.reworked", {"run_id": run_id, "revise_hints": revise_hints}, source="orchestrator")

    publish("system.pipeline.escalated", {"run_id": run_id, "reason": f"rework 超预算 {RETRY_BUDGET} 轮"}, source="orchestrator")
    return {"status": "ESCALATED", "run_id": run_id}
```

### 5.2 与现有 `DiagnosisAgent` 的关系

- G1 复用 `agents/diagnosis.py` 现有实现：其 `run(state)` 已产出符合 `agent1.output/v1` 的 `diagnosis_result`，其内部校验逻辑（知识点 ≥5、evidence 兜底）与本文档 4.4 一致。
- 接入本协议仅需：外层包 Gate-in/Gate-out 校验（`jsonschema`）+ 按 2.5 事件表发布事件。
- G2/G3（`PlanAgent` / `ReviewAgent`）为新建 Agent，继承 `backend.base.BaseAgent`，System Prompt 取 3.2 / 3.3，输出分别校验 `agent2.output/v1` / `agent3.output/v1`。

---

## 附录：配置常量

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `RETRY_BUDGET` | `2` | G3 rework 最大轮数（R6） |
| `GATE_OUT_AUTOFIX` | `1` | Gate-out 解析失败的自动修复次数（A4） |
| `LLM_RETRY` | `2` | LLM 网络/超时重试次数（指数退避） |
| `MAX_WEEKLY_LOAD_FACTOR` | `1.2` | 周学时不得超过 avg_hours_per_week 的倍数（审核维度 3） |
| `MIN_KNOWLEDGE_POINTS` | `5` | G1 输出 knowledge_map 下限 |
| `MIN_STAGES` | `3` | G2 输出 stages 下限 |

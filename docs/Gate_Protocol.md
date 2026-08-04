# Gate 接口协议文档

> **项目**：XH-202630 工业机器人编程调试多智能体系统  
> **文档定位**：三闸门对外接口契约——Opt-3 对接 EventBus 消息格式、Opt-4 对接 API 返回体格式  
> **版本**：v1.0  
> **更新日期**：2026-08-04  
> **代码路径**：`backend/src/quality_gate/`

---

## 一、GateResult 统一结构

所有闸门通过 `GateResult` 返回判定结果，外部通过 `state["gate_results"][gate_name]` 读取。

```json
{
  "passed": true,
  "score": 0.0,
  "violations": [],
  "gate_name": "输入特异性检测",
  "llm_consulted": false,
  "details": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `passed` | bool | ✅ | 整体是否通过 |
| `score` | float (0.0–1.0) | ✅ | 质量评分：1.0=完全通过，0.0=被拦截 |
| `violations` | list[str] | ✅ | 违规项描述列表，通过时为空 |
| `gate_name` | str | ✅ | 闸门中文名称（如 `"输入特异性检测"`） |
| `llm_consulted` | bool | ✅ | 是否经过了 LLM 复核。闸门1 始终为 false |
| `details` | dict | ✅ | 附加详情——各闸门自定义键（如 `intent`、`final_chunks` 等） |

---

## 二、裁决枚举

三闸门裁决路径定义（参考 `PHASE2_PLAN.md` §2.4）：

| 裁决 | 含义 | 后续行为 |
|------|------|----------|
| **PASS** | 校验/质量达标，继续流水线 | 进入下一个 stage（Agent 或下一道闸门） |
| **RETRY** | 暂时不达标，可修正后重试 | 回跳上一阶段，带上修正提示；有最大重试次数上限 |
| **FALLBACK** | 不达标且不可恢复 | 跳转到兜底输出路径，终止流水线或使用降级模板 |

各闸门使用情况：

| 闸门 | PASS | RETRY | FALLBACK |
|------|------|-------|----------|
| InputGate | 通过，进入 Agent1 | N/A（前端拦截） | 返回输入引导提示 |
| DiagnosisGate | 通过，进入 Query 生成 | 补充信息后重试（≤2次） | 降级为基础诊断模板 |
| RecallGate | 通过，进入生成 | 改写 Query 重检（≤3次） | 无知识库模式 / 提示无法回答 |

---

## 三、闸门1：InputGate（输入特异性检测）

### 3.1 基本属性

| 属性 | 值 |
|------|-----|
| 类名 | `InputGate` |
| 文件 | `backend/src/quality_gate/gates/input_gate.py` |
| 策略 | `HARD_RULE_ONLY`（纯规则，**永不调 LLM**） |
| 所需 state 键 | `learner_data` |

### 3.2 输入结构

从 `state["learner_data"]` 收集文本字段：

```json
{
  "learner_data": {
    "learning_goal": "FANUC机器人SRVO-068报警怎么解决",
    "major": "自动化",
    "industry": "汽车制造",
    "school": "某职业技术学院",
    "positions": ["机器人调试员"],
    "skills_used": ["FANUC示教器", "KUKA KRL编程"]
  }
}
```

> InputGate 将上述字段拼接为一个文本串 `combined`，逐项检测。

### 3.3 检测流程

```
combined = join(learning_goal, major, industry, school, positions, skills_used)
  → 检测1: 空输入检查（combined 为空字符串 → FALLBACK）
  → 检测2: 长度检查（len(combined) < GATE1_MIN_INPUT_LENGTH → FALLBACK）
  → 检测3: 危险关键词（命中 GATE1_BANNED_KEYWORDS 任一 → FALLBACK）
  → 检测4: 领域外话题（命中 GATE1_BLOCKED_DOMAINS 任一 → FALLBACK）
  → 检测5: 意图识别（正则匹配疑问词 → 标记 intent 标签，不阻断）
```

### 3.4 输出结构

**PASS 示例：**

```json
{
  "passed": true,
  "score": 1.0,
  "violations": [],
  "gate_name": "输入特异性检测",
  "llm_consulted": false,
  "details": {
    "intent": "故障排查",
    "intent_confidence": "high"
  }
}
```

**FALLBACK（敏感词）示例：**

```json
{
  "passed": false,
  "score": 0.0,
  "violations": [
    "输入包含违规内容，命中关键词: 暴力"
  ],
  "gate_name": "输入特异性检测",
  "llm_consulted": false,
  "details": {}
}
```

**FALLBACK（空输入）示例：**

```json
{
  "passed": false,
  "score": 0.0,
  "violations": [
    "输入为空，无法进行学情诊断"
  ],
  "gate_name": "输入特异性检测",
  "llm_consulted": false,
  "details": {}
}
```

### 3.5 意图标签

`details.intent` 可取以下值之一：

| 标签 | 匹配关键词（部分） |
|------|-------------------|
| `故障排查` | 故障、报错、报警、异常、不工作、无法、出错、SRVO、错误代码 |
| `编程操作` | 编程、示教、编写、程序、指令、轨迹、点位 |
| `安全规范` | 安全、急停、防护、危险、警告、门锁 |
| `参数配置` | 参数、配置、设置、变量、系统变量、寄存器 |
| `通信调试` | 通信、IO、信号、总线、EtherNet、ProfiNet、DeviceNet |
| `概念理解` | 怎么、如何、为什么、是什么、区别、原理 |
| `未识别` | 无法匹配以上任一模式 |

---

## 四、闸门2：DiagnosisGate（学情诊断质量检测）

### 4.1 基本属性

| 属性 | 值 |
|------|-----|
| 类名 | `DiagnosisGate` |
| 文件 | `backend/src/quality_gate/gates/diagnosis_gate.py` |
| 策略 | `HARD_RULE_WITH_LLM_FALLBACK`（硬规则 + 临界区间 LLM 复核） |
| 所需 state 键 | `diagnosis_result` |

### 4.2 输入结构

`state["diagnosis_result"]` 为 Agent1 学情诊断的输出（dict 形式）：

```json
{
  "diagnosis_result": {
    "skill_gaps": [
      {
        "topic": "机器人坐标系",
        "current_level": 0.2,
        "target_level": 0.7,
        "priority": "critical",
        "reason": "未系统学习过工具/用户坐标系的设定方法"
      }
    ],
    "knowledge_map": {
      "机器人坐标系": {
        "topic": "机器人坐标系",
        "level": 0.2,
        "confidence": 0.8,
        "evidence": "测前问卷第3题回答错误"
      }
    },
    "recommended_difficulty": "beginner",
    "learning_style": "practice_first",
    "summary": "学员为工业机器人初级操作者，需强化坐标系概念"
  }
}
```

### 4.3 硬规则检测

| # | 检测项 | 阈值配置 | 违规行为 |
|---|--------|----------|----------|
| 1 | `skill_gaps` 数量 | `GATE2_MIN_SKILL_GAPS`（默认 1） | 少于阈值 → violation |
| 2 | `knowledge_map` 数量 | `GATE2_MIN_KNOWLEDGE_ITEMS`（默认 1） | 少于阈值 → violation |
| 3 | `recommended_difficulty` 合法性 | `Difficulty` 枚举值集合 | 不在合法值中 → violation |
| 4 | `knowledge_map.*.level` 范围 | [0, 1] | 越界 → violation |
| 5 | `skill_gaps.*.current_level` / `target_level` 范围 | [0, 1] | 越界 → violation |

综合评分 = `checks_passed / 5`。

### 4.4 LLM 复核区间

```
score ≥ GATE2_LLM_REVIEW_UPPER（默认 0.70）→ 直接放行
score <  GATE2_LLM_REVIEW_LOWER（默认 0.40）→ 直接驳回
score ∈ [0.40, 0.70)                     → LLM 复核诊断有效性
```

LLM 复核输出 `{"pass": bool, "reason": "..."}`。复核失败时保守驳回。

### 4.5 输出结构

```json
{
  "passed": true,
  "score": 0.8,
  "violations": [],
  "gate_name": "学情诊断质量检测",
  "llm_consulted": false,
  "details": {}
}
```

---

## 五、闸门3：RecallGate（RAG 召回质量检测）

### 5.1 基本属性

| 属性 | 值 |
|------|-----|
| 类名 | `RecallGate` |
| 文件 | `backend/src/quality_gate/gates/recall_gate.py` |
| 策略 | `HARD_RULE_WITH_LLM_FALLBACK`（硬规则 + 临界区间 LLM 复核） |
| 所需 state 键 | `retrieved_chunks` |

### 5.2 输入结构

`state["retrieved_chunks"]` 为知识库语义检索引擎返回的文档列表：

```json
{
  "retrieved_chunks": [
    {
      "doc_id": "K1_20260803_001_fanuc_teachpendant_programming",
      "doc_title": "FANUC示教器编程基础",
      "chunk_index": 2,
      "content": "## 工具坐标系设定\n\n工具坐标系用于定义...",
      "relevance_score": 0.82
    }
  ]
}
```

### 5.3 硬规则检测

| # | 检测项 | 阈值 | 行为 |
|---|--------|------|------|
| 1 | 召回总数 | `GATE3_MIN_RECALL_COUNT`（默认 3） | 少于阈值 → violation |
| 2 | 逐文档相似度 — 高区 | `≥ GATE3_LLM_REVIEW_SIM_UPPER`（默认 0.70） | 直接采纳 |
| 3 | 逐文档相似度 — 临界区 | `[GATE3_LLM_REVIEW_SIM_LOWER, 0.70)`（默认 0.50–0.70） | 进入 LLM 复核 |
| 4 | 逐文档相似度 — 低区 | `< GATE3_LLM_REVIEW_SIM_LOWER`（默认 0.50） | 直接丢弃 |

### 5.4 LLM 复核

对落入临界区间的每篇文档，逐篇调用轻量 LLM 判断语义相关性：

```
输入: 用户 Query + 文档内容（前 800 字符）
输出: {"relevant": bool, "reason": "简短理由"}
```

复核大面积失败（≥50% chunk 出错）时保守沿用原始硬规则结果。

### 5.5 输出结构

```json
{
  "passed": true,
  "score": 0.78,
  "violations": [],
  "gate_name": "RAG召回质量检测",
  "llm_consulted": true,
  "details": {
    "total_chunks": 5,
    "direct_pass_count": 2,
    "llm_review_count": 2,
    "direct_drop_count": 1,
    "llm_confirmed_count": 1,
    "llm_rejected_count": 1,
    "final_valid_count": 3,
    "final_chunks": [...]
  }
}
```

---

## 六、EventBus 集成约定

**架构约束**：Gate/Agent 内部**不导入、不调用** EventBus。所有事件广播由 `PipelineScheduler`（`backend/src/scheduler/pipeline.py`）统一发起。

闸门相关事件：

| 事件类型 | 触发时机 | data 载荷 |
|----------|----------|-----------|
| `EventType.GATE_PASS` | 闸门判定通过 | `{"gate": "...", "label": "...", "score": 0.0}` |
| `EventType.GATE_FAIL` | 闸门判定未通过 | `{"gate": "...", "label": "...", "score": 0.0, "violations": [...]}` |

Scheduler 在 `_do_gate()` 中自动广播上述事件，**Opt-3 的 EventBus 测试可以直接监听这些事件类型**。

---

## 七、配置阈值速查

所有阈值通过 `backend/src/config.py` → `Settings` 类 → 环境变量/`.env` 文件配置。
详见 `.env.example` 中 `Quality Gate` 区域。

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `GATE1_MIN_INPUT_LENGTH` | 10 | InputGate 最短输入字符数 |
| `GATE1_BANNED_KEYWORDS` | `违法,暴力,色情,赌博,毒品` | 危险关键词黑名单 |
| `GATE1_BLOCKED_DOMAINS` | `政治,军事,金融交易,医疗诊断` | 领域外话题 |
| `GATE2_MIN_SKILL_GAPS` | 1 | 最少薄弱环节数 |
| `GATE2_MIN_KNOWLEDGE_ITEMS` | 1 | 最少知识点数 |
| `GATE2_LLM_REVIEW_LOWER` | 0.40 | 诊断直接驳回线 |
| `GATE2_LLM_REVIEW_UPPER` | 0.70 | 诊断直接放行线 |
| `GATE3_MIN_RECALL_COUNT` | 3 | 最少召回文档数 |
| `GATE3_MIN_SIMILARITY` | 0.60 | 单文档最低相似度 |
| `GATE3_LLM_REVIEW_SIM_LOWER` | 0.50 | 召回直接丢弃线 |
| `GATE3_LLM_REVIEW_SIM_UPPER` | 0.70 | 召回直接采纳线 |

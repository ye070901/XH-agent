# 全局幻觉率读数（Phase 3 · eval 模式）

> 测量日期：2026-09-03
> 口径：**eval 模式**（模型原生四态判断，无确定性规则纠偏）+ **分层采样**
> 结论一句话：**全局幻觉率 11.57%，超标（阈值 5%），主因是「无法核实」断言占主导，而非系统性编造。**

---

## 一、结论摘要

| 指标 | 读数 | 阈值/目标 | 判定 |
|---|---|---|---|
| **全局幻觉率** | **11.57%**（96/830） | < 5% | ❌ 超标 2.3× |
| 知识库对齐率 | 88.43%（734/830） | — | 参考值 |
| 适配率 | 87.73% | ≥ 85% | ✅ 达标 |
| 覆盖率 | 92.73%（102/110） | ≥ 90% | ✅ 达标 |
| 负例拦截 | 3/4 通过 | 4/4 | ❌ 1 例失败 |
| 金标校准 | 不可用（8/60 对齐） | ≥ 50 对齐 + ≥ 0.90 | ❌ 采样错位 |

---

## 二、方法与口径

- **模式**：`audit_mode = eval`。审核 Agent 对每条事实断言做 LLM 原生四态判断
  `accurate / hallucination / unverifiable / partially_supported`，不做 demo 模式的
  A>B 权威裁决与规则兜底。
- **采样**：分层采样 —— 10 个 learner profile × 11 个 counted 领域 × 每领域 1 个知识点
  （core/high 平衡 5:6）+ 4 个负例 = **114 例**（110 正例 + 4 负例）。
- **采集**：114/114 成功，0 非 200 响应，114 唯一 case_id。
- **幻觉率口径**（`compute_hallucination`）：
  `(hallucination + unverifiable) / (accurate + hallucination + unverifiable + partially_supported)`
  `partially_supported` 核心事实成立，只进分母不进坏样本分子。
- **知识库对齐率口径**：`(accurate + partially_supported) / total`，即有原文依据的信息点占比。

---

## 三、全局四态拆解（关键洞察）

| 态 | 条数 | 占总数 |
|---|---|---|
| accurate（准确） | 485 | 58.4% |
| partially_supported（部分支撑） | 249 | 30.0% |
| unverifiable（无法核实） | 91 | 10.96% |
| hallucination（编造） | **5** | **0.60%** |
| **合计** | **830** | 100% |

**核心发现**：96 条「坏断言」中 **91 条是 `unverifiable`（94.8%），只有 5 条是真正的
`hallucination`（编造）**。也就是说，11.57% 的「幻觉率」本质上接近「不可核实率」——
模型大量产出的是**超出知识库可验证范围的断言**（知识库缺原文依据 / 检索未命中 / 回答过度延伸），
而不是在凭空编造事实。这直接决定了后续修复方向应优先投在**检索召回 + 证据覆盖**，而非「反编造」。

---

## 四、逐例分布（110 正例）

| 桶 | 例数 |
|---|---|
| 0%（无坏断言） | 59 |
| (0, 5%] | 0 |
| (5%, 20%] | 25 |
| > 20% | 26 |

- 逐例均值 13.35%（未加权），全局 11.57%（按断言数加权）。
- 过半用例（59/110）零坏断言；问题集中在少数高幻觉用例（26 例 > 20%）。

---

## 五、按知识点拆解（每点 = 10 个 profile 合并）

| 知识点 | 坏断言 | 总断言 | 幻觉率 |
|---|---:|---:|---:|
| K6-HIGH-002 | 13 | 73 | **17.81%** |
| K7-CORE-001 | 12 | 73 | **16.44%** |
| K1-CORE-001 | 12 | 79 | **15.19%** |
| K8-HIGH-002 | 10 | 80 | 12.50% |
| K11-HIGH-001 | 10 | 80 | 12.50% |
| K4-HIGH-004 | 9 | 76 | 11.84% |
| K9-CORE-001 | 9 | 80 | 11.25% |
| K10-HIGH-002 | 8 | 79 | 10.13% |
| K5-CORE-001 | 5 | 66 | 7.58% |
| K3-CORE-001 | 5 | 80 | 6.25% |
| K2-HIGH-004 | 3 | 64 | **4.69%** |

> 高幻觉知识点集中在 K6（拖动示教与力控制）、K7（PROFINET 调试）、K1（基础安全与急停）。

---

## 六、按画像拆解（每画像 = 11 个知识点合并）

| 画像 | 坏断言 | 总断言 | 幻觉率 |
|---|---:|---:|---:|
| profile-06 | 18 | 81 | **22.22%** |
| profile-03 | 14 | 86 | 16.28% |
| profile-10 | 14 | 88 | 15.91% |
| profile-07 | 11 | 74 | 14.86% |
| profile-04 | 11 | 87 | 12.64% |
| profile-05 | 10 | 83 | 12.05% |
| profile-09 | 10 | 87 | 11.49% |
| profile-02 | 3 | 80 | 3.75% |
| profile-08 | 3 | 88 | 3.41% |
| profile-01 | 2 | 76 | **2.63%** |

> 零基础画像（profile-01/02/08，幻觉率 2.6–3.8%）表现远好于进阶画像
> （profile-06/03/10，12–22%）。进阶画像偏好更深、更专业的内容，模型倾向超出检索证据作答。

---

## 七、金标校准说明（本采样不可用）

- `data/evaluation/gold_labels.json` 现有 60 条 approved 金标，但**仅覆盖 K1–K3 三个领域
  共 18 个知识点、49 个 case**。
- 本采样横跨 **K1–K11 共 11 个知识点**，与金标重叠仅 3 个点
  （K1-CORE-001 / K2-HIGH-004 / K3-CORE-001）→ 最终只有 **8/60** 条 claim 对齐。
- 因此 `accuracy = 3.33%`（correct=2 / total_gold=60）**不是有效的校准读数**，是采样错位
  造成的伪低分，不是真实校准失败。
- 要得到有效金标校准，需二选一：
  1. 为其余 8 个领域（K4–K11）补齐金标；或
  2. 让分层采样的知识点对齐现有金标覆盖范围（K1–K3 全 18 点）。

---

## 八、数据资产（可复现）

| 用途 | 路径 |
|---|---|
| 分层采样清单 | `data/evaluation/runs/stratified_sample_ids.json` |
| 原始输出（114 记录） | `data/evaluation/runs/phase3_raw_outputs_eval_sample.json` |
| 采样 case 文件（114 例） | `data/evaluation/runs/phase3_test_cases_sample.json` |
| 评测报告（全量 JSON） | `data/evaluation/runs/phase3_eval_report_sample.json` |

复现命令：

```bash
# 采集（可断点续传）
python scripts/collect_resumable.py \
  --case-ids data/evaluation/runs/stratified_sample_ids.json \
  --mode eval \
  --output data/evaluation/runs/phase3_raw_outputs_eval_sample.json

# 评测
python scripts/run_phase3_evaluation.py \
  --outputs data/evaluation/runs/phase3_raw_outputs_eval_sample.json \
  --output-report data/evaluation/runs/phase3_eval_report_sample.json \
  --cases data/evaluation/runs/phase3_test_cases_sample.json \
  --gold-file data/evaluation/gold_labels.json
```

---

## 九、结论与下一步建议

1. **全局幻觉率 11.57% 超标**，但 94.8% 的坏断言是「无法核实」而非「编造」——修复优先级应放在
   **检索召回与证据覆盖**，而非反编造规则。
2. **适配率 / 覆盖率已达标**（87.73% / 92.73%），个性化生成底座健康。
3. **负例 1 例拦截失败**，需定位该负例（未拦截的原因）。
4. **下一步定位**：对高幻觉画像（profile-06/03/10）× 高幻觉知识点（K6/K7/K1）做逐条证据溯源，
   区分「知识库缺料」vs「检索未召回」vs「生成过度延伸」三类根因。
5. **金标补量**：为 K4–K11 补金标，或让采样对齐 K1–K3 现有金标，才能启用金标校准这一独立验证。

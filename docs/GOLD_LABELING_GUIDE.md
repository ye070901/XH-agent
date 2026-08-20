# Agent3 三态判定人工金标准标注指南

## 1. 目的

金标准用于回答“Agent3 的逐断言判定有多可信”，不是用来替模型补写答案。最终报告同时给出自动测得的幻觉率和 Agent3 对人工金标准的判定准确率。

至少需要 **50 条事实断言** 完成独立双人复核。`skip` 是非事实句，不计入这 50 条。

## 2. 标签定义

| 标签 | 判定条件 | 最终资源处理 |
| --- | --- | --- |
| `accurate` | 仓库知识库原文明确支持该事实，且没有被更高权威来源反驳 | 保留并绑定来源 |
| `hallucination` | 权威知识库明确反驳，或具体数值、代码、步骤与来源冲突 | 删除或按权威原文修正 |
| `unverifiable` | 当前知识库既不能支持也不能反驳 | 按 Phase 3 D1 删除 |
| `skip` | 过渡、修辞、学习提示、无可核验事实的指令句 | 不计入幻觉率分母，也不计入 50 条事实标签 |

边界规则：

1. “听起来合理”不等于 `accurate`，必须找到可定位的知识库依据。
2. 来源缺失时不要凭个人经验补证，标 `unverifiable`。
3. 复合句包含多个可独立核验事实时，先拆成多个 claim。
4. A 级一手来源与 B 级二手来源冲突时，以 A 级为准，并在 `rationale` 记录冲突。
5. 安全旁路、隐藏密码、未公开指令等请求不能因模型自信而判真。

## 3. 抽样要求

从真实流水线的 `gold_candidate_claims` 抽样，避免只挑容易样本。建议最低分布：

- K1、K2、K3 每个领域至少 12 条；
- 3 个学习者画像均有覆盖；
- `lecture`、`guide`、`quiz` 均有覆盖；
- 包含系统初判为三种事实标签的样本；
- 同一文档或同一用例不超过总样本的 20%。

若某类候选不足，应在报告中如实说明，不得复制或轻微改写同一句子凑数。

## 4. 双人标注流程

1. 运行离线评测，取得报告中的 `gold_candidate_claims`。
2. 标注员 A 隐藏 `agent3_predicted_verdict`，只看 claim 与知识库，独立给出标签、依据和理由。
3. 复核员 B 独立检查标签与来源，不得与标注员为同一人。
4. 有分歧时由 K1/K2/K3 对应领域负责人仲裁；修订后将 `review_status` 设为 `approved`。
5. 复制空模板为 `data/evaluation/gold_labels.json` 并录入最终结果。
6. 运行默认 validator；少于 50 条完整事实标签时发布门禁失败。

## 5. 数据格式

```json
{
  "meta": {
    "name": "Agent3 三态判定人工金标准",
    "version": "1.0",
    "minimum_approved_fact_labels": 50
  },
  "items": [
    {
      "claim_id": "P3-01-K3-CORE-001:claim-001:001",
      "case_id": "P3-01-K3-CORE-001",
      "claim": "待核验的完整事实断言",
      "expected_verdict": "accurate",
      "evidence": {
        "source_document": "data/raw/K3_safety_fault/对应文档.md",
        "locator": "第 1 节故障代码概述"
      },
      "rationale": "说明来源如何支持、反驳或为何无法验证该断言。",
      "annotator": "标注员A",
      "annotated_at": "2026-08-20T10:00:00+08:00",
      "reviewer": "复核员B",
      "review_status": "approved"
    }
  ]
}
```

`accurate` 必须提供 `evidence.source_document`；其他标签也应尽量记录查过的来源与定位。不要在 gold 文件中填写 Agent3 的预测作为 `expected_verdict`，除非人工已经独立核验。

## 6. 校验与标定

标注期间只检查非 gold 数据：

```powershell
python scripts/validate_phase3_dataset.py --dataset-only
```

发布前执行完整门禁：

```powershell
python scripts/validate_phase3_dataset.py
```

默认门禁仅把以下记录计入 50 条：claim 非空、标签为 `accurate/hallucination/unverifiable`、理由和时间完整、标注员与复核员不同、`review_status=approved`。`skip` 可保留用于句型分类分析，但不计数。

Agent3 标定准确率：

```text
判定准确率 = 与人工 expected_verdict 一致的断言数 / 人工事实断言总数
```

最终报告应保留混淆矩阵、缺失预测 ID 和多余预测 ID。不得只报告准确率而隐藏漏判。

## 7. 禁止事项

- 禁止用脚本批量填充 `expected_verdict`。
- 禁止把 Agent3 的输出直接复制成金标准。
- 禁止把模板中的空数组描述成“已完成 50 条标注”。
- 禁止修改原始输出来提高指标；如需重跑，应保存新的 raw output 文件并记录模型、参数和时间。
- 禁止在标注文件中写入 API Key、账号、个人隐私或其他密钥。

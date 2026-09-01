---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f1ca6c447b60fb40e48305ff5bfe5fe6_754c1deca44c11f192a2525400287e28
    ReservedCode1: sAkF6s6cs3Lx3t9ioYM4O4ioEfAjqzW4SO8uRjeq6BPxqNJs4BWmnjf5M+TfV9WkgUFT2HMo9H8gEQwbgGu85M9U8Fo87DpCxZqMaVfOeGjNaOGoOAG+13g5iUjCfK8WqJC8oJo+iamFwH36b8xebIF2eUOrpO2UC6X/VaN0y2n0hlFwVXRiTHa4EqE=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f1ca6c447b60fb40e48305ff5bfe5fe6_754c1deca44c11f192a2525400287e28
    ReservedCode2: sAkF6s6cs3Lx3t9ioYM4O4ioEfAjqzW4SO8uRjeq6BPxqNJs4BWmnjf5M+TfV9WkgUFT2HMo9H8gEQwbgGu85M9U8Fo87DpCxZqMaVfOeGjNaOGoOAG+13g5iUjCfK8WqJC8oJo+iamFwH36b8xebIF2eUOrpO2UC6X/VaN0y2n0hlFwVXRiTHa4EqE=
---

# P1（partially_supported 质量风控）收紧版复测对照结论

生成时间：2026-08-30
数据：58 条 gold 全量复测（phase3_raw_outputs.p1_recheck.json，无 error、无 audit=0）
对照基线：P0 v3（phase3_raw_outputs.v3.json）

## 一、逐项红线对照

| 红线指标 | P0 基线 v3 | P1 收紧版全量 | 判定 |
|---|---|---|---|
| B类 ≤ 1 | 1 | 1 | 达标 |
| hallucination ≤ 5 | 5 | 29 | 不达标（反弹 +24） |
| Avg hallucination_rate ≤ 0.0536 | 0.0582（报告口径 0.0536） | 0.1473（报告口径 0.1562） | 不达标（≈3 倍） |
| unverifiable ≤ 22 | 22 | 39 | 不达标（+17） |
| case 通过 ≥ 22/58 | 22/58 | 10/58 | 不达标（-12） |

补充：partially_supported 258 → 200（减少 58）；negative 负例通过 2/4 → 1/4（变差）。

## 二、反弹根因

P1 全量 29 条 hallucination 增量中：
- 规则层（P1 硬幻觉前置校验）触发 25 条
- LLM 语义判定触发 0 条
- 其他 4 条

即全部新增幻觉均来自规则层，符合踩坑记录中"规则层触发 >10 条即说明规则过松"的判据，P1 收紧版规则层仍存在大面积误伤，导致全面回退。

## 三、抽样核验结论（temp/p1_verify_final_30.json）

- 30 条人工核验：合格 21 / 误放 8 / 误降 1，合格率 70% < 85% 底线
- 误放 8 条中多为"核心事实无依据应判 hallucination"，印证部分支持标签仍偏松

## 四、总体结论

P1 收紧版 58 条全量复测**未达 P0 红线**：仅 B类 达标（=1），hallucination / rate / unverifiable / case 四项全部反弹，且抽样合格率 70% 低于底线。规则层硬幻觉前置校验仍需收敛（规则触发 >10 条需排查），当前不可放行。

## 五、产物文件

- 全量原始输出：data/evaluation/runs/phase3_raw_outputs.p1_recheck.json（58 条，2026-08-30 16:02 重采合并）
- 全量评估报告：data/evaluation/runs/phase3_report.p1_recheck_full.json（case 10/58、rate 0.1562、B类=1）
- 抽样核验：temp/p1_verify_final_30.json（合格率 70%）
- B 类分类：data/evaluation/runs/unverifiable_classification.json（B类=1）
*（内容由AI生成，仅供参考）*

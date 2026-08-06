# XH-Agent 问题归档记录

---

## Issue-008 — DiagnosisGate 置信阈值配置适配

- **日期**: 2026-08-06
- **现象**: Agent1 学情诊断输出 `overall_confidence` 天然集中在 0.2~0.4，原阈值 0.6 导致大量正常样本误进入 RETRY→FALLBACK，4 次重试后降级，增加不必要耗时
- **处理**: 修改 `.env` `DIAGNOSIS_CONFIDENCE_THRESHOLD=0.3`
- **风险点**: 0.3‑0.6 区间中等置信内容直接 PASS 放行，依赖下游 Agent3 内容审核做二次事实校验
- **回滚方式**: 修改 `.env` 恢复 `DIAGNOSIS_CONFIDENCE_THRESHOLD=0.6`
- **复测要求**: 执行多档位 (0.4 / 0.35 / 0.3) 样本测试，统计 PASS / RETRY / FALLBACK 分支占比
- **关联变更**:
  - `backend/src/agents/diagnosis.py` — SYSTEM_PROMPT 追加 `overall_confidence` 实数打分约束
  - `backend/src/quality_gate/gates/diagnosis_gate.py` — 增加分流日志埋点

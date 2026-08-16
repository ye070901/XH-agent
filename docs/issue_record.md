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

---

## Issue-009 — 领域护栏 / Prompt 一致性修复不彻底

- **日期**: 2026-08-16
- **现象**: Phase2 Day7「边界 case 修复」要求检查三个 Agent 的 system_prompt 是否覆盖工业机器人领域关键词（FANUC/KUKA/ABB 等），但执行不彻底，遗留两处：
  1. 实际运行入口 `backend/src/agents/generation_v2.py` 的 `SYSTEM_PROMPT` 漏加领域限定句（旧 `generation.py` 已加、v2 未加；而 `orchestrator.py` / `pipeline.py` 实际 import 的是 v2）
  2. `backend/src/agents/diagnosis.py` 的 `_build_prompt` 与 docstring 示例仍残留「LangGraph 多智能体」等旧领域（大模型应用开发）文本，未随领域切换更新
- **处理**: 由 Opt-3（Agent1/2/3 原作者）收尾——领域护栏须覆盖「实际入口 generation_v2.py + 各 Agent 的 `_build_prompt`/docstring 示例文本」，而非仅顶层 `SYSTEM_PROMPT` 常量
- **风险点**: 领域护栏缺失会让 Agent2 在无 KB 约束时生成领域外内容；残留旧示例会稀释诊断相关性
- **回滚方式**: 还原为领域限定句 / 旧示例文本
- **复测要求**: 三 Agent 用「机器人故障 vs 领域外问题」各测一组，确认非工业机器人问题被拒绝、示例文本无旧领域残留
- **关联变更**:
  - `backend/src/agents/generation_v2.py` — SYSTEM_PROMPT 追加领域限定句
  - `backend/src/agents/diagnosis.py` — `_build_prompt` / docstring 清理旧领域示例

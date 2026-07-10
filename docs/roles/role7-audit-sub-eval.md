# CLAUDE.md — 角色7：审核裁判 Agent（副） + 评估模块

## 你的模块

`backend/src/agents/audit.py`（事实抽取部分）+ `backend/src/evaluation/metrics.py`

## 你要做的事情

1. 完善 `AuditAgent._audit_one()` 的事实抽取 prompt（提高抽取精度）
2. 实现溯源链接逻辑（"这条断言 → 这个 KB 文档的第 N 段"的自动对齐）
3. 完善 `MetricsEvaluator` 的三项指标计算
4. 构造测试用例，验证幻觉率计算的准确性
5. 输出评估报告（JSON + 可读文本），提交材料用

## 你的接口

- 事实抽取: `AuditAgent._audit_one()` 内部逻辑
- 评估: `evaluator.evaluate(audit_reports, diagnosis, resources) -> dict`

## 三项硬指标（评分标准30分）

```python
{
    "hallucination_rate": 0.0-1.0,     # 幻觉率 < 5%
    "adaptation_accuracy": 0.0-1.0,    # 难度适配率 ≥ 85%
    "knowledge_coverage": 0.0-1.0,     # 知识覆盖率 ≥ 90%
    "all_passed": bool,                 # 三项全部达标？
    "practical_value_score": 0-30       # 估算的实用价值得分
}
```

## 与角色6 的协作

- 你提取的事实 → 角色6 用来生成质询
- 你的指标计算 → 角色6 用来决定是否继续辩论
- 每天对一次口："你提取的事实的粒度，我的辩论逻辑能不能用上？"

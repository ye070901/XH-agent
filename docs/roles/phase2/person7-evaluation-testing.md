# 人员7 — 三项硬指标评估 + 代码验证 + 集成测试

## 角色定位

质量量化 + 测试保障。评分标准 30 分中直接相关的三项硬指标（幻觉率<5%、适配率≥85%、覆盖率≥90%），同时维护知识库代码可运行性验证和集成测试。

## 依赖关系

```
被谁依赖：全体 → 三项指标是评分标准的硬性要求
         人员8 → KB文档的代码需要你的验证脚本跑通过

依赖谁：人员4 → Agent 3 的 FactCheckResult（幻觉率计算输入）
        人员2 → Agent 1 的诊断结果（覆盖率计算输入）
        人员3 → Agent 2 的生成资源（适配率计算输入）
```

## 第一阶段：7/27 — 8/1（6天）

### 任务 1.1：评估模块接口定义 + 骨架（2天）

**文件**：`backend/src/evaluation/metrics.py`（新建）

```python
class EvaluationMetrics:
    async def compute_all(self, fact_check, diagnosis, resources) -> dict:
        return {
            "hallucination_rate": {...},  # 幻觉率 < 5%
            "adaptation_rate": {...},     # 适配率 ≥ 85%
            "coverage_rate": {...},       # 覆盖率 ≥ 90%
            "pass": {"hallucination": bool, "adaptation": bool, "coverage": bool}
        }
```

先定义三个`_compute_*`函数的完整签名+docstring+返回格式（骨架），逻辑第二阶段填。

### 任务 1.2：API 端点协作（2天）

配合人员5完成后端部分端点实现：任务状态查询、历史数据查询、端点单元测试。

### 任务 1.3：知识库代码验证脚本（2天）

**文件**：`scripts/verify_kb_code.py`（新建）

扫描KB中所有```python代码块→创建temp dir→pip install依赖→运行→记录结果→回写ChromaDB的code_verified元数据。

**交付物**：`evaluation/metrics.py`骨架 + `scripts/verify_kb_code.py`

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：三项指标计算逻辑（4天）

**幻觉率** = (hallucination_claims + unverifiable_claims) / total_claims，要求<5%

**适配率** = 难度匹配得分/满分×100。难度差1级+0.5，差2级+0；practice_first+资源代码比例>20%+0.5，theory_first+资源理论比例>30%+0.5

**覆盖率** = 被覆盖的critical/high盲区/总critical/high盲区。逐条盲区做关键词匹配+LLM语义判断。

### 任务 2.2：量化评测脚本（2天）

**文件**：`scripts/evaluate.py`（新建）

批量跑N组测试用例→统计每例三项指标→输出汇总报告(JSON+Markdown)→标记不达标用例。

### 任务 2.3：API 端点完善 + 测试（2天）

配合人员5完成剩余API端点实现和接口测试。

## 第三阶段：8/10 — 8/19

- 8/10-8/13：与人员4(Agent3)联调FactCheckResult→幻觉率接口
- 8/14-8/16：全流程回归测试（模糊输入/诊断太泛/RAG为空/正常流程/空字段/LLM断开/超大文档）
- 8/17-8/19：按评分标准逐维度验收 + 三项指标不达标时输出改进建议

## 验收标准

- [ ] 幻觉率：3组测试各跑一次均<5%
- [ ] 适配率：3组不同难度均≥85%
- [ ] 覆盖率：critical/high盲区≥90%
- [ ] 评估结果含扣分/达标明细
- [ ] verify_kb_code.py能扫描并运行KB所有代码块
- [ ] evaluate.py批量输出汇总报告
- [ ] 全流程回归测试覆盖5种异常场景
- [ ] 不达标时输出具体改进建议

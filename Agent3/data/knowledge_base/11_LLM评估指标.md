# LLM 评估指标

## 为什么需要评估

在多 Agent 内容生成系统中，输出的质量直接影响用户信任。三项硬指标是对应评分标准的强制性要求，必须在系统中落地。

## 三项核心指标

### 1. 幻觉率（Hallucination Rate）

**定义**：生成内容中无法被知识库验证的断言比例。

**公式**：
```
幻觉率 = (hallucination_count + unverifiable_count) / total_claims
```

**要求**：< 5%

**计算方法**：
- Agent 3（审核）从生成内容中提取所有事实断言
- 逐条与知识库原文比对
- 分类为：accurate（准确）、hallucination（幻觉）、unverifiable（无法验证）
- 幻觉和无法验证都属于"不可信"类别

### 2. 适配率（Adaptation Rate）

**定义**：生成内容与学习者水平、学习风格的匹配程度。

**公式**：
```
适配率 = (难度匹配分 + 风格匹配分) / 2
```

**难度匹配规则**：
- 完全匹配：+1.0
- 差 1 级（如 beginner vs intermediate）：+0.5
- 差 2 级（如 beginner vs advanced）：+0.0

**风格匹配规则**：
- practice_first 学习者：检查内容是否包含足够代码示例和实操步骤
- theory_first 学习者：检查内容是否包含足够的理论段落和概念讲解

**要求**：≥ 85%

### 3. 覆盖率（Coverage Rate）

**定义**：生成的学习资源覆盖了学习者 critical 和 high 优先级盲区的比例。

**公式**：
```
覆盖率 = 已覆盖的 critical/high 盲区数 / 总 critical/high 盲区数
```

**覆盖判定**：资源标题或内容中提到了盲区 topic 关键词（大小写不敏感）。

**要求**：≥ 90%

## 不达标时的处理

当任一指标不达标时，系统应：
1. 输出具体的不达标原因
2. 给出改进建议（如"增加关于 X 主题的内容"）
3. 触发重新生成或人工干预

## 指标之间的关系

这三个指标是互补的，不能只看单一指标：

- 幻觉率低 + 覆盖率低 = 内容准确但不完整
- 幻觉率高 + 覆盖率高 = 覆盖面广但不可信
- 幻觉率低 + 覆盖率高 + 适配率低 = 内容好但不适合该学习者

理想的生成结果是三项指标全部达标。

## 评估实施

```python
class EvaluationMetrics:
    async def compute_all(self, fact_check, diagnosis, resources) -> dict:
        """计算全部三项指标，返回: {hallucination, adaptation, coverage, all_pass, suggestions}"""
```

评估是自动化的，不需要人工参与。不达标时自动给出改进建议。

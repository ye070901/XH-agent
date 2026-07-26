# 人员3 — Agent 2 知识生成 + Agent 4 保真修正

## 角色定位

内容生成方。负责从知识库素材生成个性化学习资源，并在审核发现问题后修正错误。Agent 2 和 Agent 4 由同一人写，保证生成 prompt 和修正 prompt 的风格一致。

## 依赖关系

```
被谁依赖：人员1（编排器）→ 调用 Agent 2 生成内容、Agent 4 修正内容
         人员4（辩论引擎）→ 辩论时 Agent 2/4 作为应诉方参与

依赖谁：人员4 → RAG 检索接口（检索 query 由你拆，检索执行由人员4 的工具层完成）
        人员4 → Agent 3 的 FactCheckResult（Agent 4 的修正依据）
        人员2 → Agent 1 的诊断结果（Agent 2 的输入）
```

## 第一阶段：7/27 — 8/1（6天）

### 任务 1.1：Agent 2 拆为两步（4天）

**文件**：`backend/src/agents/generation_v2.py`（改造，重命名为 `generation.py`）

#### Step 1：生成检索 Query 列表（温度 0.1）

```python
async def _generate_retrieval_queries(self, diagnosis, resource_type) -> list[str]:
    """输入：skill_gaps + resource_type + difficulty + learning_style
       输出：3-5条结构化检索query，每条是完整的技术问题而非关键词堆砌"""
```

#### Step 2：基于 RAG chunks 约束生成（温度 0.5）

```python
async def _generate_with_chunks(self, diagnosis, resource_type, chunks, downgrade_mode=False):
    """约束规则：
       1. 只能基于【知识库内容】生成，禁止使用KB以外的知识
       2. 每条技术断言标注 [来源: {doc_id}, 段落 {chunk_idx}]
       3. KB未覆盖的内容标注 [暂无权威参考，建议补充学习]
       4. 不确定的细节宁可省略不猜测
       downgrade_mode=True时额外提示降级标注"""
```

三种资源类型固定模板：lecture(引言→3~4小节→总结) / guide(概述→准备→分步操作→FAQ) / quiz(基础×2→进阶×1→挑战×1)

### 任务 1.2：用假 chunks 跑通流程（2天）

本阶段人员4的RAG可能还没好，用假chunks验证Step 1 query列表是否具体、Step 2能否正常生成、降级行为是否正确、溯源标注格式是否正确。

**交付物**：Agent 2 双步调用版本（含可独立运行的`_demo_generate()`测试函数）

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：Agent 2 正式接入 RAG（3天）

移除假chunks，对接人员4的`knowledge_base.query()`。测试不同检索结果下的生成质量。确认`downgrade_mode=True`标注行为。

### 任务 2.2：Agent 4 保真修正（5天）

**文件**：`backend/src/agents/correction.py`（新建）

```python
class CorrectionAgent(BaseAgent):
    """输入：generated_resources[i](原始输出) + audit_result[i](Agent3的FactCheckResult)
              + debate_record(博弈记录) + retrieved_chunks(知识库原文)
       输出：corrected_resource(修正后) + correction_log(每条issue的修正记录)
    """
```

修正策略：error(事实错误)→必须改，查KB原文替换 / warning(难度不匹配)→尽量改，调整解释深度 / info(改进建议)→可选改

关键约束：只改有问题的部分(不重写整个资源)、修改后重新标注来源、KB冲突内容并列不选边、修正后不引入新的事实断言。

**交付物**：`correction.py` + SYSTEM_PROMPT + 修正日志模板

## 第三阶段：8/10 — 8/19（10天）

- 8/10-8/14：与人员4联调"生成→审核→辩论→修正→再审"闭环
- 8/15-8/17：Prompt打磨（3种资源类型×3组测试用例各跑一次）
- 8/18-8/19：代码冻结

## 验收标准

- [ ] Agent 2 Step 1：同一输入3次调用≥80%重合
- [ ] Agent 2 Step 2：每条技术断言≥80%有来源标注
- [ ] downgrade_mode时正确标注`[知识库暂无此主题内容]`
- [ ] 三种资源类型均能正常生成(lecture/guide/quiz)
- [ ] Agent 4对error级别issue修正率≥90%
- [ ] Agent 4修正不引入新的error
- [ ] 冲突内容并列展示不自动选边

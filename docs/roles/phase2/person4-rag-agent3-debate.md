# 人员4 — RAG + Agent 3 + 辩论引擎 + 保真打分 + 三项指标评估

## 角色定位

知识库基础设施 + 审核博弈方 + 质量量化。整个系统防幻觉体系的核心——RAG 提供"真相基准"，Agent 3 做结构化事实核查，辩论引擎做对抗验证，打分引擎量化保真度，三项指标直接对应评分标准 30 分。

## 依赖关系

```
被谁依赖：全体 → RAG 检索接口是整个内容生成的数据入口
         人员3 → Agent 3 的输出是 Agent 4 的修正依据
         人员1 → RAG + Agent 3 + 辩论引擎 + 打分引擎 + 评估指标
         全员 → 三项指标是评分标准硬性要求

依赖谁：人员8 → 知识库文档数据
        人员3 → Agent 2 生成输出（审核对象）+ Agent 2/4（辩论应诉方）
        人员2 → Agent 1 诊断结果（覆盖率计算输入）
```

## 第一阶段：7/27 — 8/2（7天）

### 任务 1.1：ChromaDB 工具层升级（2天）

**文件**：`backend/src/knowledge/store.py`（改造现有文件）

```python
class KnowledgeBase:
    async def query(self, query_text: str, top_k=5, min_similarity=0.6) -> list[dict]
        # 返回: [{doc_id, content, score, metadata(source_level/reviewer/code_verified), chunk_idx}]
    async def query_multi(self, queries: list[str], top_k=3) -> list[dict]
    async def add_document(self, doc_id, title, content, metadata) -> list
    async def delete_document(self, doc_id)
    async def get_stats(self) -> dict
```

### 任务 1.2：文档解析 + 分片工具（2天）

**文件**：`backend/src/knowledge/parser.py`（新建）

支持 .md/.txt/.pdf。智能分片：优先按 Markdown 标题切分 → 超长段落按句子边界切分 → overlap=100。

### 任务 1.3：KB 批量导入脚本（2天）

**文件**：`scripts/import_kb.py`（新建）

### 任务 1.4：三项指标评估接口定义（1天）

**文件**：`backend/src/evaluation/metrics.py`（新建骨架）

```python
class EvaluationMetrics:
    async def compute_all(self, fact_check, diagnosis, resources) -> dict:
        """返回幻觉率/适配率/覆盖率 + pass标记"""
    async def _compute_hallucination(self, fact_check) -> dict:
        """幻觉率 = (hallucination + unverifiable) / total，要求 <5%"""
    async def _compute_adaptation(self, diagnosis, resources) -> dict:
        """适配率 = 难度匹配 + 风格匹配，要求 ≥85%"""
    async def _compute_coverage(self, diagnosis, resources) -> dict:
        """覆盖率 = 被覆盖的critical/high盲区 / 总盲区，要求 ≥90%"""
```

**交付物**：`knowledge/store.py` 升级版 + `knowledge/parser.py` + `scripts/import_kb.py` + `evaluation/metrics.py` 骨架 + ChromaDB 实例（≥14篇入库）

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：Agent 3 结构化事实核查（3天）

**文件**：`backend/src/agents/audit.py`（改造现有文件）

有 KB 模式：提取所有事实断言 → 逐条比对原文 → accurate / hallucination / unverifiable。

无 KB 模式（`downgrade_mode=True` 时触发）：不做原文比对，改为内部一致性检查——概念前后矛盾、API 名称不一致、代码缺 import、步骤跳跃缺失。输出 ConsistencyReport。

```python
class AuditAgent(BaseAgent):
    async def _fact_check(self, resource, chunks, downgrade_mode=False) -> dict:
        """有KB→原文比对 / 无KB→一致性检查"""
```

### 任务 2.2：辩论引擎（3天）

**文件**：`backend/src/debate/engine.py`（新建）

Agent 3(质疑方) vs Agent 2/4(应诉方)，最多 3 轮。裁决逻辑是代码规则（不调 LLM）：concede→共识 / rebut→比对双方引用原文 / 3轮未共识→标记待人工审核。

### 任务 2.3：保真打分引擎（1天）

**文件**：`backend/src/evaluation/scoring.py`（新建）

打分规则（硬编码）：基础分 100 → 每条 hallucination(error):-10 / warning:-3 / unverifiable:-1 / 缺溯源:-2，最低 0。

### 任务 2.4：三项指标计算逻辑（1天）

**文件**：`backend/src/evaluation/metrics.py`（填肉）

- 幻觉率 = (hallucination + unverifiable) / total
- 适配率 = 难度匹配(匹配+1/差1级+0.5/差2级+0) + 风格匹配(practice_first有足够代码示例+0.5 / theory_first有足够理论段落+0.5)
- 覆盖率 = 资源中覆盖的 critical/high 盲区 / 总 critical/high 盲区数

## 第三阶段：8/11 — 8/16（6天）

- 8/11-8/12：与人员3 联调辩论闭环 + 评估指标数据链路验证
- 8/13-8/14：修 bug + Agent 3 prompt 调优 + RAG 相似度阈值调优
- 8/15-8/16：验证三项指标达标（幻觉率<5%/适配率≥85%/覆盖率≥90%）+ 不达标时输出改进建议

## 验收标准

- [ ] RAG query() 返回带完整 metadata
- [ ] Agent 3 有 KB 模式：从一份资源提取 ≥10 条事实断言，逐条比对原文
- [ ] Agent 3 无 KB 模式：能检测概念矛盾/API不一致/代码缺import/步骤跳跃
- [ ] 辩论引擎 3 轮后自动终止，concede/rebut/accept_challenge 三种回应裁决正确
- [ ] 打分引擎扣分项有明细日志
- [ ] 三项指标 3 组测试均达标
- [ ] 不达标时输出具体改进建议

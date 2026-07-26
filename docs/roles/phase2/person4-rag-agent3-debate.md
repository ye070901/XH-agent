# 人员4 — RAG 基础设施 + Agent 3 内容审核 + 辩论引擎 + 保真打分

## 角色定位

知识库基础设施 + 审核与博弈方。整个系统防幻觉体系的核心——RAG 提供"真相基准"，Agent 3 做结构化事实核查，辩论引擎做对抗验证，打分引擎量化保真度。

## 依赖关系

```
被谁依赖：全体 → RAG 检索接口是整个内容生成的数据入口
         人员3 → Agent 3 的输出是 Agent 4 的修正依据
         人员1（编排器）→ RAG 检索接口 + Agent 3 + 辩论引擎 + 打分引擎
         人员7 → FactCheckResult 是三项指标的计算输入

依赖谁：人员8 → 知识库文档数据（ChromaDB 写入的原材料）
        人员3 → Agent 2 的生成输出（Agent 3 的审核对象）
        人员3 → Agent 2/4 作为辩论应诉方
```

## 第一阶段：7/27 — 8/1（6天）

### 任务 1.1：ChromaDB 工具层升级（2天）

**文件**：`backend/src/knowledge/store.py`（改造现有文件）

核心接口：
```python
class KnowledgeBase:
    async def query(self, query_text: str, top_k=5, min_similarity=0.6) -> list[dict]
        # 返回: [{doc_id, content, score, metadata(source_level/reviewer/code_verified), chunk_idx}]
    async def query_multi(self, queries: list[str], top_k=3) -> list[dict]  # 多条去重合并
    async def add_document(self, doc_id, title, content, metadata) -> list
    async def delete_document(self, doc_id)
    async def get_stats(self) -> dict
```

### 任务 1.2：文档解析 + 分片工具（2天）

**文件**：`backend/src/knowledge/parser.py`（新建）

支持 .md/.txt/.pdf 统一提取纯文本。智能分片策略：优先按Markdown标题层级切分→超长段落按句子边界切分(非硬切)→overlap=100保证上下文连贯。

### 任务 1.3：知识库批量导入脚本（2天）

**文件**：`scripts/import_kb.py`（新建）

```bash
python scripts/import_kb.py --dir data/knowledge_base/ --domain rag --reviewer 人员2
```

**交付物**：`knowledge/store.py`升级版 + `knowledge/parser.py` + `scripts/import_kb.py` + ChromaDB实例（≥14篇文档入库）

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：Agent 3 结构化事实核查（3天）

**文件**：`backend/src/agents/audit.py`（改造现有文件）

从"看一眼给意见"升级为"逐条断言vs原文比对"：

```python
class AuditAgent(BaseAgent):
    async def _fact_check(self, resource, chunks) -> dict:
        """
        流程：提取所有事实断言 → 逐条去KB原文比对 → 三类判定
        accurate:    原文明确支撑
        hallucination: 原文矛盾或找不到支撑
        unverifiable:  KB中该主题缺失（不是错误，是不可知）
        
        返回: {total_claims, accurate_claims, hallucinations:[{claim,severity,evidence_against}],
               unverifiable:[{claim,reason}], hallucination_rate, verdict}
        """
```

**交付物**：`audit.py` 升级版

### 任务 2.2：辩论引擎（3天）

**文件**：`backend/src/debate/engine.py`（新建）

```python
class DebateEngine:
    async def run(self, resource, fact_check, diagnosis, knowledge_chunks, defender_agent) -> dict:
        """
        Agent 3(质疑方) vs Agent 2/4(应诉方)，最多3轮，知识库原文作为客观裁判
        
        每轮流程：
        Agent 3发起质询(AuditChallenge) → 应诉方回应(concede/rebut/accept_challenge) → 裁决
        
        裁决逻辑（代码规则，不调LLM）：
        - concede → 共识达成
        - rebut → 比对双方引用的原文 → 谁引用正确谁赢
        - 双方各引用原文支撑 → 标记"冲突"，不裁决
        - 3轮后未共识 → 标记"待人工审核"
        """
```

**交付物**：`debate/engine.py`

### 任务 2.3：保真打分引擎（2天）

**文件**：`backend/src/evaluation/scoring.py`（新建）

打分规则（硬编码，不调LLM）：基础分100 → 每条hallucination(error):-10 / warning:-3 / unverifiable:-1 / 缺失溯源:-2，最低0分。

**交付物**：`evaluation/scoring.py`

## 第三阶段：8/10 — 8/19（10天）

- 8/10-8/15：与人员3联调"生成→审核→辩论→修正→再审"闭环
- 8/16-8/17：修bug + 调参数（RAG相似度阈值/Agent3 prompt召回率）
- 8/18-8/19：代码冻结

## 验收标准

- [ ] RAG query() 返回结果带完整metadata
- [ ] RAG query_multi() 正确去重合并
- [ ] Agent 3 从一份资源中提取≥10条事实断言
- [ ] FactCheckResult中 accurate + hallucination + unverifiable = total_claims
- [ ] 辩论引擎3轮后自动终止
- [ ] concede/rebut/accept_challenge三种回应裁决正确
- [ ] 打分引擎扣分项有明细日志
- [ ] ChromaDB持久化数据量≥100 chunks

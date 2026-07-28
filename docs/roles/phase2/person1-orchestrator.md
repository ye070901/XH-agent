# 人员1 — 编排器 + WebSocket + 闸门

## 角色定位

流水线大脑。负责串联全部 Agent 的执行顺序、分支判断、闸门拦截和质量降级逻辑。**不改已有的 config.py、exceptions.py、BaseAgent、LLMClient**——这些基础设施已在 MVP 完成，直接使用。

## 依赖关系

```
被谁依赖：所有人 → 编排器决定了 Agent 的调用顺序和数据流转格式
         人员5（API）→ 编排器是 API 的后端核心

依赖谁：人员4 → RAG 检索接口（闸门3 需要调 query()）
        人员3 → Agent 2、Agent 4 的 process() 签名
        人员4 → Agent 3、博弈引擎的接口
        人员2 → Agent 1 的 process() 签名
```

## 第一阶段：7/27 — 8/1（6天）

### 任务 1.1：闸门1 — 输入特异性检测（2天）

**文件**：`backend/src/gateways/input_validator.py`（新建）

```python
async def validate_learning_goal(learning_goal: str) -> dict:
    """Returns: {"pass": True} 或 {"pass": False, "reason": "...", "suggestions": [...]}"""
```

判定逻辑：先规则检查（长度<8→不通过，匹配泛化关键词表→触发LLM判断），再LLM快速判断（温度0，输出3条追问建议）。

### 任务 1.2：闸门2 — 诊断质量校验（1天）

**文件**：`backend/src/gateways/diagnosis_validator.py`（新建）

纯规则判断，不调LLM：topic长度<6字→不通过、topic以泛化词结尾且总长≤6字→不通过、confidence<0.3→不通过。不通过时退回Agent 1重诊（最多2次），重诊prompt附带`diagnosis_retry_hints`。

### 任务 1.3：闸门3 — RAG 召回质量检测（1天）

**文件**：`backend/src/gateways/retrieval_validator.py`（新建）

纯规则判断：query覆盖率<60%→降级、平均相似度<0.65→降级、检索总字数<500→降级。降级行为：在state中设置`downgrade_mode: True`，Agent 2读取此标记生成时标注`[知识库暂无此主题内容]`。

### 任务 1.4：编排器骨架升级（2天）

**文件**：`backend/src/graph/orchestrator.py`（改造现有文件）

把现有3Agent串行扩展为：闸门1→Agent1→闸门2→循环每种资源类型(Agent2_Step1→RAG→闸门3→Agent2_Step2→Agent3→[辩论]→Agent4→[再审])→标准化输出。Agent状态变更时广播WebSocket事件。agent_log追加结构化事件（含timestamp/from_agent/to_agent/action/message/round）。

**交付物**：`orchestrator.py` 升级版 + 3 个 `gateways/*.py`

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：编排器完整版（5天）

填满`_generate_one_resource()`：辩论循环（while round <= 3 and not consensus_reached）、修正循环（Agent 4修正→Agent 3再审，最多2轮）、降级模式（闸门3不通过时设`downgrade_mode: True`）、异常隔离（单资源失败不阻断其他资源）。

### 任务 2.2：WebSocket 集成（1.5天）

在编排器关键节点调用`broadcast_agent_event()`：Agent开始→thinking、Agent完成→done、辩论轮次开始→debate、闸门拦截→gateway。

### 任务 2.3：降级 + 异常处理完善（1.5天）

知识库完全无匹配时的全量降级逻辑、Agent超时熔断（120s标记error继续后续）、断点续跑。

## 第三阶段：8/10 — 8/19（10天）

- 8/10-8/14：联调（对接人员3/4的Agent接口、对接人员5的API/WebSocket）
- 8/15-8/17：修bug
- 8/18-8/19：代码冻结（清理调试日志、确认闸门默认参数、最终代码评审）

## 接口契约

### 编排器暴露的接口（人员5调用）
```python
result = await workflow_engine.run(task_id=str, learner_data=dict, resource_types=list)
# 返回: dict，含 status + diagnosis + resources + audit + debate_record + agent_log + metrics
```

### 你需要别人提供的
| 来自 | 接口 |
|------|------|
| 人员4 | `await knowledge_base.query(query_text, top_k)` → `list[{doc_id, content, score, chunk_idx}]` |
| 人员2 | `await diagnosis_agent.run(state)` → state含`diagnosis_result` |
| 人员3 | `await generation_agent.run(state)` / `await correction_agent.run(state)` |
| 人员4 | `await audit_agent.run(state)` / `await debate_engine.run(...)` |
| 人员5 | `await broadcast_agent_event(task_id, agent_name, state, message)` |

## 验收标准

- [ ] Demo Mode 下全链路跑通（闸门1→Agent1→闸门2→Agent2→RAG→闸门3→Agent3→辩论→Agent4→再审→输出）
- [ ] 闸门1：输入"我想学AI"时返回追问建议
- [ ] 闸门2：Agent1输出topic="AI基础"时触发退回重诊
- [ ] 闸门3：RAG检索为空时进入降级模式
- [ ] 辩论最多3轮自动终止
- [ ] Agent超时120s后该资源跳过，其他正常
- [ ] agent_log包含≥20条事件
- [ ] WebSocket每个关键节点都有推送

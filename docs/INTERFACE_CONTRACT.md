# 接口契约文档

> **这是 8 个人的法律文件。修改此文档需要全员周知 + 架构师批准。**

---

## 总则

1. **所有 Agent 的输入/输出必须通过 `state` 字典传递，键名约定见此文档**
2. **所有 Agent 必须继承 `BaseAgent`，实现 `async def process(self, state: dict) -> dict`**
3. **所有数据模型定义在 `backend/src/schemas.py`，禁止在各模块重复定义**
4. **修改 schemas.py 需要全员通知**
5. **LLM 调用统一通过 `BaseAgent.call_llm()` 或 `BaseAgent.call_llm_json()`**

---

## 数据流

```
用户请求 (CreateProfileRequest)
    │
    ▼
┌────────────────────────────────────────────────────────────────┐
│ Agent 1: 学情诊断 (角色4)                                       │
│ 输入: state["learner_data"]                                     │
│       {                                                         │
│         "education_level": str,                                 │
│         "major": str,                                           │
│         "school": str | None,                                   │
│         "work_years": float,                                    │
│         "industry": str | None,                                 │
│         "positions": list[str],                                 │
│         "skills_used": list[str],                               │
│         "pretest_results": list[dict],                          │
│         "learning_goal": str | None                             │
│       }                                                         │
│ 输出: state["diagnosis_result"] + state["diagnosis_completed"]  │
│       {                                                         │
│         "knowledge_map": dict[str, KnowledgeItem],              │
│         "skill_gaps": list[SkillGap],                          │
│         "learning_style": "practice_first"|"theory_first"|...,  │
│         "recommended_difficulty": "beginner"|"intermediate"|...,│
│         "summary": str                                          │
│       }                                                         │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────┐
│ 知识检索 (角色3 负责维护知识库)                                  │
│ 输入: diagnosis_result["skill_gaps"] 中的 topic 列表             │
│ 输出: state["retrieved_chunks"]                                 │
│       [                                                         │
│         {                                                       │
│           "doc_id": str,                                        │
│           "doc_title": str,                                     │
│           "chunk_index": int,                                   │
│           "content": str,                                       │
│           "relevance_score": float                              │
│         }                                                       │
│       ]                                                         │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────┐
│ Agent 2: 知识生成 (角色5)                                        │
│ 输入: diagnosis_result + retrieved_chunks + resource_types      │
│ 输出: state["generated_resources"]                              │
│       [                                                         │
│         {                                                       │
│           "resource_id": str,                                   │
│           "resource_type": "lecture"|"guide"|"quiz"|...,        │
│           "title": str,                                         │
│           "content": str,           # Markdown                  │
│           "citations": [             # 必须非空！               │
│             {                                                   │
│               "ref_index": int,                                 │
│               "original_text": str, # KB 原文逐字引用            │
│               "usage": str          # 在正文中的位置             │
│             }                                                   │
│           ],                                                    │
│           "difficulty_level": str,                              │
│           "target_skill_gaps": list[str],                       │
│           "estimated_duration_minutes": int,                    │
│           "prerequisites": list[str]                            │
│         }                                                       │
│       ]                                                         │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────┐
│ Agent 3: 审核裁判 (角色6 + 角色7)                                 │
│ 输入: generated_resources + retrieved_chunks + diagnosis_result │
│ 输出: state["audit_reports"]                                    │
│       [                                                         │
│         {                                                       │
│           "resource_id": str,                                   │
│           "verdict": "approved"|"needs_revision"|"rejected"|...,│
│           "fact_check": {                                       │
│             "overall_accuracy": float,                          │
│             "items": [...],                                     │
│             "hallucination_count": int                          │
│           },                                                    │
│           "hallucination_flags": [                              │
│             {                                                   │
│               "location": str,                                  │
│               "description": str,                               │
│               "severity": "critical"|"major"|"minor",           │
│               "suggested_correction": str | None                │
│             }                                                   │
│           ],                                                    │
│           "hallucination_rate": float                           │
│         }                                                       │
│       ]                                                         │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ▼ (如果 verdict != "approved")
┌────────────────────────────────────────────────────────────────┐
│ 辩论引擎 (角色6 核心实现)                                        │
│ Agent 3 质询 → Agent 2 辩护/修正 → Agent 3 再评估                │
│ 最多 3 轮，未共识 → escalated（待人工审核）                      │
│ 输出: state["debate_records"] + state["final_resources"]        │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ▼
                   最终输出
```

---

## 关键约束

### ⚠️ Agent 2 → Agent 3 的关键约束
- `citations` 数组不能为空（空数组 = Agent 3 标记为 critical 级幻觉）
- `content` 中的每条专业断言应该用 `[ref:N]` 标注引用编号
- Agent 2 不得编造不在 KB 中的"专业事实"

### ⚠️ Agent 3 的审核标准
- `hallucination_rate > 0.05` → verdict 不能为 "approved"
- 存在 critical 级别 flag → verdict 至少为 "needs_revision"
- `citations` 为空数组 → 自动 critical flag

### ⚠️ 辩论协议
- Agent 2 回应对 `defense` 字段有三种动作：`accept_challenge` / `rebut` / `concede`
- Agent 2 引用 `evidence_from_kb` 时必须是 KB 逐字引用，不是自己的理解
- Agent 3 评估辩护时必须以 KB 原文为标准
- 3 轮未共识 → `final_verdict = "uncertain"` → `unresolved_claims` 记录

---

## 分支开发规范

```
main ← dev ← feature/agent-diagnosis    (角色4)
           ← feature/agent-generation   (角色5)
           ← feature/agent-audit        (角色6 + 角色7)
           ← feature/knowledge-store    (角色3)
           ← feature/llm-client         (角色2)
           ← feature/graph-orchestrator (角色1)
           ← feature/frontend           (角色8)
           ← feature/evaluation         (角色7)
```

**规则：**
1. 每人从 `dev` 分支出来，在自己的分支上开发
2. 写完 + 本地测试通过 → PR 到 `dev`
3. 架构师（角色1）负责 merge 和处理冲突
4. 每个 PR 必须通过 CI 自动检查（ruff + pytest + contract check）
5. 不要直接修改别人的文件

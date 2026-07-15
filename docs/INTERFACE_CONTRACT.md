# 接口契约文档

> **MVP 版本：Agent 1 + Agent 2。修改此文档需全员周知。**

---

## 总则

1. **所有 Agent 的输入/输出通过 `state` 字典传递，键名约定见此文档**
2. **所有 Agent 必须继承 `BaseAgent`，实现 `async def process(self, state: dict) -> dict`**
3. **所有数据模型定义在 `backend/src/schemas.py`，禁止在各模块重复定义**
4. **修改 schemas.py 需要全员通知**
5. **LLM 调用统一通过 `self.call_llm()` / `self.call_llm_json()`**

---

## 数据流（MVP）

```
POST /api/generate { learner_data }
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Agent 1: 学情诊断 (角色4)                              │
│ 输入: state["learner_data"]                           │
│ 输出: state["diagnosis_result"] + ["diagnosis_completed"]
│                                                      │
│ learner_data 格式:                                    │
│ {                                                    │
│   "education_level": "bachelor",                     │
│   "major": "计算机科学",                              │
│   "school": "某某大学",                               │
│   "work_years": 1.0,                                 │
│   "industry": "互联网",                               │
│   "positions": ["Python开发"],                        │
│   "skills_used": ["Python", "Flask"],                 │
│   "pretest_results": [],                             │
│   "learning_goal": "学习LangGraph"                    │
│ }                                                    │
│                                                      │
│ diagnosis_result 格式:                                │
│ {                                                    │
│   "knowledge_map": { "知识点": {level, confidence} }, │
│   "skill_gaps": [{topic, priority, reason, ...}],    │
│   "learning_style": "practice_first",                │
│   "recommended_difficulty": "beginner",              │
│   "summary": "学习者整体画像总结"                      │
│ }                                                    │
└────────────────────┬─────────────────────────────────┘
                     │ diagnosis_result
                     ▼
┌──────────────────────────────────────────────────────┐
│ Agent 2: 知识生成 (角色5)                              │
│ 输入: diagnosis_result + resource_types               │
│ 输出: state["generated_resources"]                    │
│                                                      │
│ generated_resources 格式:                             │
│ [{                                                   │
│   "resource_id": "uuid",                             │
│   "resource_type": "lecture|guide|quiz",             │
│   "title": "资源标题",                                │
│   "content": "Markdown 格式内容",                     │
│   "difficulty_level": "beginner",                    │
│   "estimated_duration_minutes": 30,                  │
│   "key_takeaways": ["要点1", "要点2"]                 │
│ }]                                                   │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
                返回前端
```

---

## API 契约

### POST /api/generate

**请求：**
```json
{
    "education_level": "bachelor",
    "major": "计算机科学",
    "work_years": 1.0,
    "industry": "互联网",
    "positions": ["Python开发"],
    "skills_used": ["Python", "Flask"],
    "pretest_results": [],
    "learning_goal": "学习LangGraph构建AI Agent",
    "resource_types": ["lecture", "guide", "quiz"]
}
```

**返回：**
```json
{
    "task_id": "uuid",
    "status": "completed",
    "diagnosis": { ... },
    "resources": [ ... ],
    "agent_log": [ ... ]
}
```

---

## 分支规范

```
main ← dev ← feature/agent-diagnosis    (角色4)
           ← feature/agent-generation   (角色5)
           ← feature/llm-client         (角色2)
           ← feature/graph-orchestrator (角色1)
           ← feature/frontend           (角色8)
```

**规则：**
1. 每人从 `dev` 分支出来，在自己的分支上开发
2. 写完 + 本地测试通过 → PR 到 `dev`
3. 角色1 负责 merge
4. 不要直接修改别人的文件
5. 不要直接 push 到 main

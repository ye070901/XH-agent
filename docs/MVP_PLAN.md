# MVP 6人分工

---

## 谁做什么

| 谁 | 做什么 |
|----|--------|
| **人1** | 配置 + LLM层 + BaseAgent + 启动脚本 |
| **人2** | Agent 1（学情诊断） |
| **人3** | Agent 2（知识生成） |
| **人4** | Agent 3（内容审核） |
| **人5** | API入口 + 编排器 |
| **人6** | Streamlit 前端 |

---

## 依赖顺序

```
人1 最先      → 所有人等他（配置、LLM层、BaseAgent）
人2+3+4 并行  → 三个 Agent 互不依赖，各写各的 prompt
人5 跟着      → 等 Agent 好了，串起来
人6 全程并行  → 从第一天用假数据写界面，不等任何人
```

---

## 三个 Agent 怎么协作

```
编排器（人5）:

    state = {"learner_data": {...}}

    Step 1: Agent1.process(state)  → 读 learner_data，写 diagnosis_result
    Step 2: Agent2.process(state)  → 读 diagnosis_result，写 generated_resources
    Step 3: Agent3.process(state)  → 读 generated_resources + diagnosis_result，写 audit_result

    return state
```

Agent 互不认识，编排器把上一步输出递给下一步。

---

## 前后端接口

唯一接口：`POST /api/generate`

**前端（人6）发给后端（人5）：**
```json
{
    "learning_goal": "想学什么（必填）",
    "education_level": "bachelor",
    "major": "专业名称",
    "skills_used": ["Python"],
    "work_years": 1.0,
    "industry": "行业",
    "positions": ["岗位"],
    "pretest_results": [],
    "resource_types": ["lecture", "guide", "quiz"]
}
```

**后端（人5）返回给前端（人6）：**
```json
{
    "diagnosis": {
        "knowledge_map": {...},
        "skill_gaps": [...],
        "learning_style": "...",
        "recommended_difficulty": "...",
        "summary": "..."
    },
    "resources": [
        {"resource_type": "lecture", "title": "...", "content": "Markdown"},
        {"resource_type": "guide", "title": "...", "content": "Markdown"},
        {"resource_type": "quiz", "title": "...", "content": "Markdown"}
    ],
    "audit": [
        {"resource_index": 0, "verdict": "approved", "issues": []}
    ]
}
```

---

## 谁做的谁测

| 谁 | 怎么测 |
|----|--------|
| **人1** | 不配 Key 跑一次，配 Key 跑一次，都不返回空 |
| **人2** | 3 组不同输入 → 3 份不同的诊断，各自有具体盲区 |
| **人3** | 同份诊断 × 三种资源类型 → 结构不同。换诊断 → 内容变 |
| **人4** | 给一份有错的资源 → 能标出来。给全对的 → approved |
| **人5** | curl API → HTTP 200，返回含 diagnosis + resources + audit |
| **人6** | 假数据写界面，表单正常、Markdown 渲染正常、后端挂了有提示 |

#  系统接口文档

---

## 一、统一接口

整个系统只有这一个前后端接口。Agent 之间不走网络，走 Python 函数调用。

```
POST http://localhost:8000/api/generate
Content-Type: application/json
```

---

## 二、前端（人6）输入输出

### 输入：用户填的表单

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learning_goal` | string | ✅ | 想学什么 |
| `education_level` | string | ✅ | `high_school` `junior_college` `bachelor` `master` `phd` |
| `major` | string | ✅ | 专业名称 |
| `skills_used` | array | ✅ | 已掌握的技能 |
| `work_years` | number | ❌ | 工作年限，默认 0 |
| `industry` | string | ❌ | 所在行业 |
| `positions` | array | ❌ | 做过哪些岗位 |
| `pretest_results` | array | ❌ | 前置测试成绩，空数组就可以 |
| `resource_types` | array | ✅ | `lecture` `guide` `quiz` 的组合 |

转成 JSON 发给后端：

```json
{
    "learning_goal": "学习LangGraph构建AI Agent",
    "education_level": "bachelor",
    "major": "计算机科学",
    "skills_used": ["Python", "Flask"],
    "work_years": 1.0,
    "industry": "互联网",
    "positions": ["Python开发"],
    "pretest_results": [],
    "resource_types": ["lecture", "guide", "quiz"]
}
```

### 输出：展示在后端返回的数据

后端会返回三块数据，前端对应展示：

```
┌─ 学情诊断 ─────────────────────────────┐
│ st.metric ×3：学习风格、推荐难度、盲区数量  │
│ st.write：整体画像总结                    │
│ st.expander ×N：知识盲区（标题+优先级+原因） │
│ st.progress ×N：知识掌握度（每个知识点一条） │
├─ 学习资源 ─────────────────────────────┤
│ st.expander + st.markdown：讲义          │
│ st.expander + st.markdown：实操指南       │
│ st.expander + st.markdown：测试题         │
├─ 审核意见 ─────────────────────────────┤
│ 每份资源下面标 ✅ ⚠️ ❌                   │
└─────────────────────────────────────────┘
```

### 前端调后端的代码

```python
import requests

data = {
    "learning_goal": learning_goal,
    "education_level": education_level,
    "major": major,
    "skills_used": skills_used,
    "work_years": work_years,
    "industry": industry,
    "positions": positions,
    "pretest_results": [],
    "resource_types": resource_types,
}

response = requests.post("http://localhost:8000/api/generate", json=data, timeout=120)

if response.status_code == 200:
    result = response.json()
    # result["diagnosis"] → 诊断
    # result["resources"] → 资源
    # result["audit"]    → 审核
else:
    st.error(f"生成失败: {response.text}")
```

### 前端开发时不依赖后端

```python
# 开发期间用假数据，从下面第三节复制完整 JSON
FAKE_RESULT = { ... }
result = FAKE_RESULT

# 联调时换成真调用
# result = requests.post(...).json()
```

---

## 三、后端（人5）输入输出

### 输入：前端发来的 JSON

```json
{
    "learning_goal": "学习LangGraph构建AI Agent",
    "education_level": "bachelor",
    "major": "计算机科学",
    "skills_used": ["Python", "Flask"],
    "work_years": 1.0,
    "industry": "互联网",
    "positions": ["Python开发"],
    "pretest_results": [],
    "resource_types": ["lecture", "guide", "quiz"]
}
```

### 后端内部处理

API 入口（人5）把 JSON 转成 `learner_data`，调编排器：

```python
learner_data = {
    "education_level": request.get("education_level", "bachelor"),
    "major": request.get("major", ""),
    "work_years": request.get("work_years", 0),
    "industry": request.get("industry", ""),
    "positions": request.get("positions", []),
    "skills_used": request.get("skills_used", []),
    "pretest_results": request.get("pretest_results", []),
    "learning_goal": request.get("learning_goal", ""),
}

result = await workflow_engine.run(
    learner_data=learner_data,
    resource_types=request.get("resource_types", ["lecture"]),
)
```

### 输出：返回给前端的完整 JSON

```json
{
    "status": "completed",
    "diagnosis": {
        "knowledge_map": {
            "Python编程": {"level": 0.7, "confidence": 0.9, "evidence": "计算机专业，有Python开发经验"},
            "LLM基础概念": {"level": 0.4, "confidence": 0.7, "evidence": "工作中使用过AI工具"},
            "LangGraph框架": {"level": 0.1, "confidence": 0.8, "evidence": "学习目标明确提到LangGraph"},
            "RAG检索增强生成": {"level": 0.2, "confidence": 0.6, "evidence": "前置测试得分较低"},
            "多Agent架构设计": {"level": 0.1, "confidence": 0.8, "evidence": "未接触过多智能体系统"}
        },
        "skill_gaps": [
            {"topic": "LangGraph状态图", "current_level": 0.1, "target_level": 0.8,
             "priority": "critical", "reason": "LangGraph核心概念，不掌握无法推进"},
            {"topic": "RAG检索流程", "current_level": 0.2, "target_level": 0.7,
             "priority": "high", "reason": "Agent知识生成依赖RAG"},
            {"topic": "Prompt Engineering", "current_level": 0.3, "target_level": 0.7,
             "priority": "high", "reason": "多Agent系统需要精心设计的prompt"},
            {"topic": "多Agent架构", "current_level": 0.1, "target_level": 0.8,
             "priority": "critical", "reason": "构建协同系统需要理解Agent间通信"},
            {"topic": "向量数据库", "current_level": 0.2, "target_level": 0.6,
             "priority": "medium", "reason": "RAG依赖向量检索，可后续学习"}
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "beginner",
        "summary": "该学习者有计算机专业背景和Python开发经验，编程基础扎实。但对LLM应用开发领域的系统性知识较为薄弱。建议从实操项目入手，边做边学。"
    },
    "resources": [
        {
            "resource_type": "lecture",
            "title": "LangGraph 入门讲义",
            "content": "# LangGraph 入门讲义\n\n## 1. 什么是 LangGraph\n\nLangGraph 是 LangChain 团队推出的库...\n\n```python\nfrom langgraph.graph import StateGraph\n...\n```",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 30,
            "key_takeaways": ["LangGraph通过状态图管理多步骤LLM调用", "StateGraph三要素"]
        },
        {
            "resource_type": "guide",
            "title": "实操指南：构建第一个 LangGraph 应用",
            "content": "# 实操指南\n\n## 步骤1：安装依赖\n\n```bash\npip install langgraph\n```\n\n## 步骤2：定义状态图\n\n```python\nworkflow = StateGraph(MyState)\n...\n```\n\n## 步骤3：运行",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 20,
            "key_takeaways": ["三步搭建LangGraph", "掌握条件路由"]
        },
        {
            "resource_type": "quiz",
            "title": "LangGraph 基础测试",
            "content": "# LangGraph 基础测试\n\n## 基础题\n\n**1. LangGraph 最核心的抽象是什么？**\n- A) Chain\n- B) StateGraph ✓\n- C) AgentExecutor\n- D) Pipeline\n\n**解析：** StateGraph 是 LangGraph 的核心。",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 15,
            "key_takeaways": ["检验 StateGraph 核心概念理解"]
        }
    ],
    "audit": [
        {
            "resource_index": 0,
            "resource_type": "lecture",
            "verdict": "needs_revision",
            "issues": [
                {"severity": "warning", "detail": "难度偏高：学习者是beginner但第3节涉及进阶概念"}
            ]
        },
        {
            "resource_index": 1,
            "resource_type": "guide",
            "verdict": "approved",
            "issues": []
        },
        {
            "resource_index": 2,
            "resource_type": "quiz",
            "verdict": "approved",
            "issues": [
                {"severity": "info", "detail": "可增加一道关于条件路由的题"}
            ]
        }
    ]
}
```

### 后端打包返回的代码

```python
@app.post("/api/generate")
async def generate(request: dict):
    result = await workflow_engine.run(...)
    return {
        "status": result["status"],
        "diagnosis": result["diagnosis_result"],
        "resources": result["generated_resources"],
        "audit": result["audit_result"],
    }
```

---

## 四、三个 Agent 怎么连接

Agent 之间不为网络，不走 HTTP。编排器（人5）用 state 字典串联。

### 整体流程

```
前端发 JSON
    │
    ▼
API 入口（人5）: 转成 learner_data，调编排器
    │
    ▼
编排器（人5）:
    state = {"learner_data": {...}, "resource_types": [...]}

    Step 1: agent1.process(state)   ← 人2 写的
    → 读 state["learner_data"]
    → 写 state["diagnosis_result"]

    Step 2: agent2.process(state)   ← 人3 写的
    → 读 state["diagnosis_result"]
    → 写 state["generated_resources"]

    Step 3: agent3.process(state)   ← 人4 写的
    → 读 state["generated_resources"] + state["diagnosis_result"]
    → 写 state["audit_result"]

    return state
    │
    ▼
API 入口: 从 state 取三个字段 → 打包 JSON → 返回前端
```

### 编排器代码

```python
state = {"learner_data": learner_data, "resource_types": resource_types}

# Step 1
state.update(await agent1.process(state))

# Step 2
state.update(await agent2.process(state))

# Step 3
state.update(await agent3.process(state))

return state
```

### 每个 Agent 读什么、写什么

```
Agent 1（人2）:  learner_data     → diagnosis_result
Agent 2（人3）:  diagnosis_result → generated_resources
Agent 3（人4）:  generated_resources + diagnosis_result → audit_result
```

三个 Agent 互不认识。每个只做自己的事。编排器负责递数据。

### Agent 怎么调 LLM

所有人通过人1 写的 BaseAgent 调 LLM：

```python
result = await self.call_llm_json(prompt)   # 调 LLM，拿回 dict
```

Agent 不需要知道用的是什么模型、有没有 API Key。人1 的 LLM 层处理这些。

---

## 五、资源类型结构

Agent 2（人3）生成三种资源，每种 content 结构不同：

| 类型 | 结构 |
|------|------|
| **lecture** | 引言 → 3-4 小节（每节：概念 + 代码示例）→ 总结 |
| **guide** | 概述 → 前置准备 → 步骤1/2/3（命令 + 代码 + 预期输出）→ 常见问题 |
| **quiz** | 基础题2道（选择题 + 选项 + 答案✓ + 解析）→ 进阶题1道 → 挑战题1道 |

---

## 六、审核意见分级

Agent 3（人4）对每份资源标审核意见：

| severity | 含义 | 举例 |
|----------|------|------|
| `error` | 事实错误 | API 名称写错了 |
| `warning` | 不够好但没错 | 难度偏高、遗漏盲区 |
| `info` | 改进建议 | 可以加一道题 |

---

## 七、6 人分工

| 谁 | 做什么 | 文件 |
|----|--------|------|
| 人1 | 配置 + LLM层 + BaseAgent + 启动脚本 | `config.py` `llm/client.py` `agents/base.py` `.env.example` `start.bat` |
| 人2 | Agent 1 — 学情诊断 | `agents/diagnosis.py` |
| 人3 | Agent 2 — 知识生成 | `agents/generation.py` |
| 人4 | Agent 3 — 内容审核 | `agents/audit.py` |
| 人5 | API入口 + 编排器 | `api/main.py` `graph/orchestrator.py` |
| 人6 | Streamlit 前端 | `frontend/streamlit/app.py` |

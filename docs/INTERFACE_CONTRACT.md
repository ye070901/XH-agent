# 接口契约

---

## 给前端（人6）看的

### 你发给后端的

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

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learning_goal` | string | ✅ | 想学什么 |
| `education_level` | string | ✅ | `high_school` `junior_college` `bachelor` `master` `phd` |
| `major` | string | ✅ | 专业名称 |
| `skills_used` | array | ✅ | 已掌握的技能 |
| `work_years` | number | ❌ | 工作年限，默认 0 |
| `industry` | string | ❌ | 所在行业 |
| `positions` | array | ❌ | 做过哪些岗位 |
| `pretest_results` | array | ❌ | 前置测试成绩，空数组也可以 |
| `resource_types` | array | ✅ | 从 `lecture` `guide` `quiz` `project` 中选（默认 `lecture` `guide` `quiz`） |

### 调后端的代码

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

response = requests.post(
    "http://localhost:8000/api/generate",
    json=data,
    timeout=120
)

if response.status_code == 200:
    result = response.json()
    diagnosis = result["diagnosis"]    # 拿去展示
    resources = result["resources"]    # 拿去展示
else:
    st.error(f"生成失败: {response.text}")
```

### 后端会还给你什么

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
            {"topic": "LangGraph状态图", "current_level": 0.1, "target_level": 0.8, "priority": "critical", "reason": "LangGraph核心概念，不掌握无法推进"},
            {"topic": "RAG检索流程", "current_level": 0.2, "target_level": 0.7, "priority": "high", "reason": "Agent知识生成依赖RAG"},
            {"topic": "Prompt Engineering", "current_level": 0.3, "target_level": 0.7, "priority": "high", "reason": "多Agent系统需要精心设计的prompt"},
            {"topic": "多Agent架构", "current_level": 0.1, "target_level": 0.8, "priority": "critical", "reason": "构建协同系统需要理解Agent间通信"},
            {"topic": "向量数据库", "current_level": 0.2, "target_level": 0.6, "priority": "medium", "reason": "RAG依赖向量检索，可后续学习"}
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "beginner",
        "summary": "该学习者有计算机专业背景和Python开发经验，编程基础扎实。但对LLM应用开发领域（LangGraph、RAG、Agent架构）的系统性知识较为薄弱。建议从实操项目入手，边做边学。"
    },
    "resources": [
        {
            "resource_type": "lecture",
            "title": "LangGraph 入门讲义：从状态图到多Agent协同",
            "content": "# LangGraph 入门讲义\n\n## 1. 什么是 LangGraph\n\nLangGraph 是 LangChain 团队推出的库...\n\n```python\nfrom langgraph.graph import StateGraph\n...\n```",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 30,
            "key_takeaways": ["LangGraph通过状态图管理多步骤LLM调用", "StateGraph三要素：节点、边、状态字典"]
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
            "content": "# LangGraph 基础测试\n\n## 基础题\n\n**1. LangGraph 最核心的抽象是什么？**\n- A) Chain\n- B) StateGraph ✓\n- C) AgentExecutor\n- D) Pipeline\n\n**解析：** StateGraph 是 LangGraph 的核心，用状态字典在节点间传递数据。",
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
                {"severity": "info", "detail": "可增加一道关于条件路由的题，覆盖critical盲区"}
            ]
        }
    ]
}
```

### 你拿什么数据去展示

| 你要展示的 | 取哪个字段 | 用什么组件 |
|-----------|-----------|-----------|
| 学习风格标签 | `diagnosis.learning_style` | `st.metric` |
| 推荐难度标签 | `diagnosis.recommended_difficulty` | `st.metric` |
| 知识盲区数量 | `len(diagnosis.skill_gaps)` | `st.metric` |
| 整体画像总结 | `diagnosis.summary` | `st.write` |
| 知识盲区列表 | `diagnosis.skill_gaps` 数组 | `st.expander` 每个一个 |
| 知识掌握度 | `diagnosis.knowledge_map` | `st.progress` 每个知识点一条 |
| 资源列表 | `resources` 数组 | `st.expander` 每个一个 |
| 资源内容 | `resources[i].content` | `st.markdown` |
| 审核意见 | `audit` 数组 | `st.expander` 每个资源一个 |

### 你开发时不需要等后端

```python
# 开发期间用假数据
FAKE_RESULT = {
    "status": "completed",
    "diagnosis": { ... },   # 复制上面那段
    "resources": [ ... ]    # 复制上面那段
}

# 界面写好之后，改成真调用
# result = requests.post(...).json()
result = FAKE_RESULT
```

---

## 给后端（人1-5）看的

### API 入口（人5）接收到什么、返回什么

**接收到：** 前端发来的 JSON，FastAPI 自动解析成 dict

```python
request = {
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

**人5 要做：** 拿这个 dict → 转成 `learner_data` → 调编排器的 `run()`

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

# 返回给前端
return {
    "status": result["status"],
    "diagnosis": result.get("diagnosis_result", {}),
    "resources": result.get("generated_resources", []),
    "audit": result.get("audit_result", []),
}
```

### 编排器（人5）怎么串 Agent

```python
state = {
    "learner_data": learner_data,
    "resource_types": resource_types,
}

# 第一步：Agent 1 — 学情诊断
state.update(await agent1.process(state))
# 此时 state 多了 "diagnosis_result"

# 第二步：Agent 2 — 知识生成
state.update(await agent2.process(state))
# 此时 state 多了 "generated_resources"

# 第三步：Agent 3 — 内容审核（只审不修）
state.update(await agent3.process(state))
# 此时 state 多了 "audit_result"

return state
```

三个 Agent 互不认识，编排器把每一步的输出递给下一步。

### Agent 1（人3）读什么、写什么

**读到：** `state["learner_data"]`

```python
learner_data = {
    "education_level": "bachelor",
    "major": "计算机科学",
    "work_years": 1.0,
    "industry": "互联网",
    "positions": ["Python开发"],
    "skills_used": ["Python", "Flask"],
    "pretest_results": [],
    "learning_goal": "学习LangGraph构建AI Agent",
}
```

**你要写：** `state["diagnosis_result"]`

```python
{
    "diagnosis_result": {
        "knowledge_map": {
            "Python编程": {"level": 0.7, "confidence": 0.9, "evidence": "依据"}
        },
        "skill_gaps": [
            {"topic": "缺失知识点", "current_level": 0.1, "target_level": 0.8, "priority": "critical", "reason": "原因"}
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "beginner",
        "summary": "50-100字总结"
    }
}
```

**返回方式：** `return {"diagnosis_result": result, "diagnosis_completed": True}`

**怎么用 LLM：** `result = await self.call_llm_json(prompt)` — BaseAgent 已经封装好了，你只负责拼 prompt。

### Agent 2（人4）读什么、写什么

**读到：** `state["diagnosis_result"]`（人3 写的那个）+ `state["resource_types"]`

**你要写：** `state["generated_resources"]`

```python
{
    "generated_resources": [
        {
            "resource_type": "lecture",
            "title": "讲义标题",
            "content": "Markdown 格式内容",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 30,
            "key_takeaways": ["要点1", "要点2"]
        },
        {
            "resource_type": "guide",
            "title": "实操指南标题",
            "content": "Markdown 格式内容",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 20,
            "key_takeaways": ["要点"],
            "risk_level": "high_risk",
            "safety_warnings": ["操作前确认安全门关闭", "点动前确认工作区间无人员"],
            "robot_metadata": {
                "brand": "FANUC",
                "controller_version": "R-30iB",
                "applicable_model": "未标注"
            }
        },
        {
            "resource_type": "quiz",
            "title": "测试题标题",
            "content": "Markdown 格式内容",
            "difficulty_level": "beginner",
            "estimated_duration_minutes": 15,
            "key_takeaways": ["要点"]
        }
    ]
}
```

**四种资源的 content 结构：**

| 类型 | 结构 |
|------|------|
| lecture | 引言 → 3-4 小节（每节：概念 + 代码示例）→ 总结 |
| guide | 概述 → 前置准备 → 步骤1/2/3（命令 + 代码 + 预期输出）→ 常见问题 |
| quiz | 基础题2道（选择题 + 选项 + 答案✓ + 解析）→ 进阶题1道 → 挑战题1道 |
| project | 项目背景与目标 → 工作站拆解 → 全流程方案 → 分步调试步骤 → 验收标准与风险点 |

**安全字段（Agent 2 确定性打标，非 LLM 产出）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `risk_level` | string | `theory` / `low_risk` / `high_risk`。lecture/quiz 恒 `theory`；guide/project 按正文命中运动类/软件类标记分级 |
| `safety_warnings` | string[] | 从正文 `> ⚠️ 安全提示：…` 引用块确定性提取，逐步安全提示 |
| `robot_metadata` | object | `{brand, controller_version, applicable_model}`，仅机器人领域实操类资源，从知识库 doc_id/doc_title 溯源派生；KB 无权威来源时标注「未标注」 |

high_risk 的 guide/project 正文开头须含「安全操作确认清单」章节，每个运动步骤前须有独立 `> ⚠️ 安全提示` 引用块（不满足会被 A档结构校验丢弃）。

### Agent 3（人7）读什么、写什么

**Agent 3 只审不修。** 拿到 Agent 2 生成的内容 + Agent 1 的诊断，逐条检查，输出审核报告。不改原文。

**读到：** `state["generated_resources"]` + `state["diagnosis_result"]`

**你要写：** `state["audit_result"]`

```python
{
    "audit_result": [
        {
            "resource_index": 0,
            "resource_type": "lecture",
            "verdict": "approved",
            "issues": []
        },
        {
            "resource_index": 1,
            "resource_type": "guide",
            "verdict": "needs_revision",
            "issues": [
                {"severity": "error", "detail": "事实错误"},
                {"severity": "warning", "detail": "难度偏高"}
            ]
        }
    ]
}
```

| severity | 含义 |
|----------|------|
| `error` | 事实性错误，比如 API 名称写错了 |
| `warning` | 不够好但没有错，比如难度偏高、遗漏某个盲区 |
| `info` | 建议，比如可以加一道题 |

---

### LLM 层（人2）提供给 Agent 什么

Agent 调两个方法：

```python
# 调 LLM，拿回文本
text = await self.call_llm(user_message)

# 调 LLM，拿回 dict
data = await self.call_llm_json(user_message)
```

Agent 不需要知道用的是 GPT 还是 DeepSeek，也不需要知道有没有 Key。这些由人2 的 LLM 层处理。

### 配置（人1）提供什么

`config.py` 从 `.env` 读配置。所有人 `from config import settings` 拿配置值。

```python
settings.LLM_PROVIDER    # "deepseek"
settings.LLM_API_KEY     # "sk-xxx" 或 ""
settings.LLM_MODEL       # "deepseek-chat"
```

---

## 谁做的谁测

每个人写完自己的模块，自己测。不等别人，不用别人帮测。

### 人1：配置 + LLM层 + BaseAgent

```python
# 测试1：不配 Key，演示模式
from src.llm.client import LLMClient
llm = LLMClient()
result = await llm.call_json("学情诊断", "学习目标: Python")
assert "skill_gaps" in result  # 不是空 JSON

# 测试2：配 Key，真实模式
# 在 .env 里填上 Key，再跑一次
result = await llm.call_json("学情诊断", "学习目标: Python")
assert "skill_gaps" in result

# 测试3：BaseAgent 能继承
from src.agents.base import BaseAgent
class TestAgent(BaseAgent):
    async def process(self, state): return {}
```

**自己验：** 有 Key / 没 Key 都不报错。不配 Key 不返回空 `{}`。

---

### 人2：Agent 1（学情诊断）

```python
from src.agents.diagnosis import DiagnosisAgent
agent = DiagnosisAgent()

# 准备3组不同的输入
state1 = {"learner_data": {"education_level": "bachelor", "major": "计算机", "skills_used": ["Python"], "learning_goal": "学LangGraph"}}
state2 = {"learner_data": {"education_level": "high_school", "major": "餐饮管理", "skills_used": [], "learning_goal": "学Python"}}
state3 = {"learner_data": {"education_level": "phd", "major": "机器学习", "skills_used": ["PyTorch", "TensorFlow"], "learning_goal": "学多Agent架构"}}

# 跑三次
r1 = await agent.process(state1)
r2 = await agent.process(state2)
r3 = await agent.process(state3)

# 检查1：三组输出真的不同
# 检查2：每组 skill_gaps >= 3个
# 检查3：每个 gap 有具体的 topic + priority + reason
# 检查4：difficulty 跟着输入变（high_school → beginner, phd → advanced）
```

**自己验：** 3 组不同输入 → 3 份不同的诊断。不是同一份只改关键词。

---

### 人3：Agent 2（知识生成）

```python
from src.agents.generation import GenerationAgent
agent = GenerationAgent()

# 准备一份假诊断结果（从接口文档复制）
state = {
    "diagnosis_result": {
        "skill_gaps": [{"topic": "LangGraph状态图", "priority": "critical", "reason": "..."}],
        "recommended_difficulty": "beginner",
        "learning_style": "practice_first",
        "summary": "..."
    },
    "resource_types": ["lecture", "guide", "quiz"]
}

result = await agent.process(state)

# 检查1：生成了3份资源
# 检查2：lecture 有引言+小节+总结
# 检查3：guide 有步骤编号+命令+代码
# 检查4：quiz 有题目+选项+答案+解析

# 换一种 resource_type 再测
state["resource_types"] = ["lecture"]
result = await agent.process(state)
# 检查5：只生成1份资源
```

**自己验：** 三种类型结构不同。换成不同诊断 → 内容跟着变。

---

### 人4：Agent 3（内容审核）

```python
from src.agents.audit import AuditAgent
agent = AuditAgent()

# 测试1：塞一份有事实错误的资源
state = {
    "generated_resources": [
        {"resource_type": "lecture", "title": "测试", "content": "LangGraph 是 Google 开发的框架", "difficulty_level": "beginner"}
    ],
    "diagnosis_result": {"recommended_difficulty": "beginner", "skill_gaps": []}
}
result = await agent.process(state)
# 检查1：Agent 3 应该标出 error

# 测试2：塞一份正确的内容
state["generated_resources"][0]["content"] = "LangGraph 是 LangChain 团队开发的框架，用于构建有状态的 LLM 应用。"
result = await agent.process(state)
# 检查2：verdict 应该是 "approved"、issues 为空
```

**自己验：** 有错能标出来，没错不瞎报。

---

### 人5：API + 编排器

```bash
# 启动后端
python -m uvicorn src.api.main:app --port 8000

# 另一个终端
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"learning_goal":"学Python","education_level":"bachelor","major":"计算机","skills_used":["Python"],"resource_types":["lecture"]}'
```

**自己验：** HTTP 200，返回 JSON 含 `diagnosis` + `resources` + `audit` 三个字段。

---

### 人6：前端

开发时用假数据对着接口文档把界面写出来。联调时把假数据换成真实 API 调用。

**自己验：**
- 表单能正常填
- 点生成 → 诊断 tab 展示正常（卡片、进度条、展开块）
- 资源 tab 展示正常（Markdown 代码块有高亮、标题有变大）
- 审核意见跟在资源后面
- 后端没启动 → 不白屏，有提示

---

## 6 人分工

| 人 | 负责 | 文件 |
|----|------|------|
| 1 | 配置 + LLM层 + BaseAgent + 启动脚本 | `config.py` `llm/client.py` `agents/base.py` `.env.example` `start.bat` |
| 2 | Agent 1（学情诊断） | `agents/diagnosis.py` |
| 3 | Agent 2（知识生成） | `agents/generation.py` |
| 4 | Agent 3（内容审核） | `agents/audit.py` |
| 5 | API 入口 + 编排器 | `api/main.py` `graph/orchestrator.py` |
| 6 | Streamlit 前端 | `frontend/streamlit/app.py` |

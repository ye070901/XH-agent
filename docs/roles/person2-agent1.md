# 人2：Agent 1 — 学情诊断

## 你要做什么

文件：`agents/diagnosis.py`

继承人1 的 `BaseAgent`。写 system prompt，拼诊断 prompt，调 LLM，输出诊断结果。

## 输入

`state["learner_data"]`

```python
{
    "education_level": "bachelor",
    "major": "计算机科学",
    "work_years": 1.0,
    "skills_used": ["Python", "Flask"],
    "learning_goal": "学习LangGraph"
}
```

## 输出

`state["diagnosis_result"]`

```python
{
    "knowledge_map": {
        "Python编程": {"level": 0.7, "confidence": 0.9, "evidence": "计算机专业"},
        "LangGraph框架": {"level": 0.1, "confidence": 0.8, "evidence": "学习目标提到"}
    },
    "skill_gaps": [
        {"topic": "LangGraph状态图", "current_level": 0.1, "target_level": 0.8,
         "priority": "critical", "reason": "不掌握状态机无法推进"}
    ],
    "learning_style": "practice_first",
    "recommended_difficulty": "beginner",
    "summary": "有编程基础，但LLM领域知识薄弱"
}
```

## 关键要求

- 诊断不能是"你是中级水平"。要到具体知识点
- 盲区是**前置依赖链缺失**，不是"没学过的都缺"
- 每个评估给 evidence
- 至少 5 个知识点

## 你怎么测

```python
agent = DiagnosisAgent()

# 跑3组不同输入
r1 = await agent.process({"learner_data": {..., "learning_goal": "学Python", "education_level": "high_school"}})
r2 = await agent.process({"learner_data": {..., "learning_goal": "学LangGraph", "education_level": "bachelor"}})
r3 = await agent.process({"learner_data": {..., "learning_goal": "学多Agent", "education_level": "phd"}})

# 三份 skill_gaps 真的不同，difficulty 跟着输入变
```

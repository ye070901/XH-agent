# CLAUDE.md — 角色4：学情诊断 Agent

## 你的模块

`backend/src/agents/diagnosis.py` — Agent 1：学情诊断

## 你要做的事情

1. 完善 `DiagnosisAgent.process()` 的 prompt 工程
2. 实现多维度知识图谱分析（不是"初/中/高"三分法）
3. 实现前置依赖链分析（"想学 X，但前置知识 Y 缺失"）
4. 实现置信度加权评估
5. 构造 ≥3 组差异化学习者测试用例（提交材料用）

## 你的接口

- 继承 `BaseAgent`
- 输入: `state` dict，从 `state["learner_data"]` 读取
- 输出: `state["diagnosis_result"]` + `state["diagnosis_completed"]`

## 输出格式

```json
{
    "knowledge_map": {
        "知识点名": {
            "level": 0.0-1.0,
            "confidence": 0.0-1.0,
            "evidence": "依据"
        }
    },
    "skill_gaps": [
        {
            "topic": "缺失知识点",
            "current_level": 0.0-1.0,
            "target_level": 0.0-1.0,
            "priority": "critical|high|medium|low",
            "reason": "缺失原因（前置依赖？测试低分？）"
        }
    ],
    "learning_style": "practice_first|theory_first|visual|project_based",
    "recommended_difficulty": "beginner|intermediate|advanced",
    "summary": "50-100字总结"
}
```

## 关键约束

- 至少诊断 5 个知识点的掌握度
- 不能只给"初级/中级/高级"标签，必须精细到具体知识点
- 每个评估给 evidence（依据），让审核方和评审可追溯

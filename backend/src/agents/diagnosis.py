"""
Agent 1: 学情诊断 Agent
══════════════════════════════════
负责: 角色4 实现
输入: state["learner_data"] (dict with education, experience, pretests, learning_goal)
输出: state["diagnosis_result"]
       (包含 knowledge_map, skill_gaps, learning_style, recommended_difficulty)

不是"初级/中级/高级"三分法。
是细粒度知识缺口图谱 —— 每个知识点的掌握度(0-1) + 置信度 + 证据 + 优先级。
"""

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个专业的学情诊断专家。你的任务是：
1. 分析学习者的学历背景、工作经历、前置测试结果和学习目标
2. 评估学习者在该领域的知识掌握度，为每个相关知识点建立 0-1 评分
3. 识别知识盲区并标注优先级（critical > high > medium > low）
4. 判断学习风格（theory_first / practice_first / visual / project_based）
5. 推荐初始学习难度（beginner / intermediate / advanced）

诊断原则：
- 置信度随证据量变化：前置测试直接命中 > 工作经历推断 > 学历推断
- 知识盲区是"前置依赖链缺失"而非"没学过的都缺"
  - 例：想学 LangGraph 但不知道状态机 → 这是一个 gap
  - 例：不知道某个 API 的具体参数名 → 这不是 gap，这是检索查表的事
- 至少输出 5 个知识点的评估

输出必须为严格的 JSON 格式。

## overall_confidence 计算规则
取 knowledge_map 中所有条目的 confidence 值的算术平均值，保留 2 位小数。
例如 knowledge_map 有 5 个知识点，confidence 分别为 0.8/0.6/0.9/0.7/0.5，
则 overall_confidence = 0.70。"""


class DiagnosisAgent(BaseAgent):
    """学情诊断 Agent — 角色4 在此实现"""

    REQUIRED_STATE_KEYS = {"learner_data"}
    OPTIONAL_STATE_KEYS = {"task_id", "resource_types", "agent_log", "status"}

    def __init__(self):
        super().__init__(
            name="学情诊断Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
        )

    async def process(self, state: dict) -> dict:
        learner_data = state.get("learner_data", {})
        prompt = self._build_prompt(learner_data)
        result = await self.call_llm_json(prompt)
        self.log(f"诊断完成: {len(result.get('skill_gaps', []))} 个知识盲区")
        return {
            "diagnosis_result": result,
            "diagnosis_completed": True,
        }

    def _build_prompt(self, data: dict) -> str:
        return f"""请分析以下学习者的学情数据，输出诊断结果。

## 学历背景
- 学历：{data.get("education_level", "未知")}
- 专业：{data.get("major", "未知")}
- 学校：{data.get("school", "未知")}

## 工作经历
- 年限：{data.get("work_years", 0)}年
- 行业：{data.get("industry", "未知")}
- 岗位：{", ".join(data.get("positions", []))}
- 使用技能：{", ".join(data.get("skills_used", []))}

## 前置测试
{self._format_pretests(data.get("pretest_results", []))}

## 学习目标
{data.get("learning_goal", "未指定")}

请输出以下 JSON：
{{
    "knowledge_map": {{
        "知识点名称": {{
            "level": 0.0,
            "confidence": 0.0,
            "evidence": "评估依据（来自学历/经历/测试的具体信息）"
        }}
    }},
    "skill_gaps": [
        {{
            "topic": "缺失的知识点",
            "current_level": 0.0,
            "target_level": 0.0,
            "priority": "critical|high|medium|low",
            "reason": "为什么这个缺口需要优先填补"
        }}
    ],
    "learning_style": "practice_first|theory_first|visual|project_based",
    "recommended_difficulty": "beginner|intermediate|advanced",
    "overall_confidence": 0.85,
    "summary": "学习者整体画像总结（50-100字）"
}}

要求：
- knowledge_map 至少包含 5 个知识点
- skill_gaps 按优先级从高到低排列
- 每个评估都附上 evidence 说明依据
- 置信度低于 0.3 的评估请特别标注

【打分强制约束】overall_confidence必须如实评估学情诊断结果可信度，严禁刻意抬高置信分数；
0=完全没有依据，1=完全确定；依据知识库召回内容客观输出分数，禁止为了通过闸门而虚高打分。"""

    def _format_pretests(self, tests: list) -> str:
        if not tests:
            return "无前置测试数据"
        lines = []
        for t in tests:
            lines.append(
                f"- {t.get('test_name', '未知测试')}: "
                f"{t.get('total_score', 0)}/{t.get('max_score', 100)}"
            )
            for topic, score in t.get("topic_scores", {}).items():
                lines.append(f"  - {topic}: {score}")
        return "\n".join(lines)

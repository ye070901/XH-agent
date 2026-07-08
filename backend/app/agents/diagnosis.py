"""学情诊断Agent — 分析学习者画像，识别知识盲区"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个专业的学情诊断专家。你的任务是：
1. 分析学习者的学历背景、工作经历和前置测试结果
2. 评估其知识掌握度，建立知识地图（每个知识点 0-1 评分）
3. 识别技能盲区，按优先级排序（critical/high/medium/low）
4. 判断学习风格（theory_first / practice_first / visual / project_based）
5. 推荐初始学习难度（beginner / intermediate / advanced）

输出必须为严格的JSON格式。"""


class DiagnosisAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="学情诊断Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
        )

    def process(self, state: dict) -> dict:
        profile_data = state.get("learner_data", {})
        prompt = self._build_prompt(profile_data)
        result = self.call_llm_json(prompt)
        return {"diagnosis_result": result, "diagnosis_completed": True}

    def _build_prompt(self, data: dict) -> str:
        return f"""请分析以下学习者的学情数据，输出诊断结果。

## 学历背景
- 学历：{data.get('education_level', '未知')}
- 专业：{data.get('major', '未知')}
- 学校：{data.get('school', '未知')}

## 工作经历
- 年限：{data.get('work_years', 0)}年
- 行业：{data.get('industry', '未知')}
- 岗位：{', '.join(data.get('positions', []))}
- 使用技能：{', '.join(data.get('skills_used', []))}

## 前置测试
{self._format_pretests(data.get('pretest_results', []))}

## 学习目标
{data.get('learning_goal', '未指定')}

请输出以下JSON结构：
{{
    "knowledge_map": {{"知识点名称": {{"level": 0.0-1.0, "confidence": 0.0-1.0, "evidence": "评估依据"}}}},
    "skill_gaps": [{{"topic": "知识点", "current_level": 0.0-1.0, "target_level": 0.0-1.0, "priority": "critical/high/medium/low", "reason": "原因"}}],
    "learning_style": "practice_first/theory_first/visual/project_based",
    "recommended_difficulty": "beginner/intermediate/advanced",
    "summary": "学习者整体画像总结(50-100字)"
}}"""

    def _format_pretests(self, tests: list) -> str:
        if not tests:
            return "无前置测试数据"
        lines = []
        for t in tests:
            lines.append(f"- {t.get('test_name', '未知测试')}: {t.get('total_score', 0)}/{t.get('max_score', 100)}")
            for topic, score in t.get('topic_scores', {}).items():
                lines.append(f"  - {topic}: {score}")
        return "\n".join(lines)

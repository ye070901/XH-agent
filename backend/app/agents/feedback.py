"""交互反馈Agent — 基于答题结果动态决策下一步"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个学习反馈分析专家。你的任务是：
1. 分析学习者的答题表现
2. 判断是否需要降维解释、进阶挑战或重新生成资源
3. 给出具体的下一步建议

决策规则：
- 正确率 < 50%：触发降维解释（simplify）
- 正确率 50%-85%：继续当前路径（continue）
- 正确率 > 85%：触发进阶挑战（advance）
- 某个知识点全错：触发重新生成该知识点资源（regenerate）

输出必须为严格的JSON格式。"""


class FeedbackAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="交互反馈Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,
        )

    def process(self, state: dict) -> dict:
        quiz_result = state.get("quiz_result", {})
        learner_id = state.get("learner_id", "")
        resource_id = state.get("current_resource_id", "")

        prompt = self._build_prompt(quiz_result, learner_id, resource_id)
        result = self.call_llm_json(prompt)
        return {"feedback_decision": result}

    def _build_prompt(self, quiz_result: dict, learner_id: str, resource_id: str) -> str:
        import json
        return f"""## 答题结果
- 总分：{quiz_result.get('total_score', 0)}/{quiz_result.get('max_score', 100)}
- 正确率：{quiz_result.get('correct_rate', 0) * 100:.1f}%
- 各知识点正确率：{json.dumps(quiz_result.get('topic_breakdown', {}), ensure_ascii=False)}
- 用时：{quiz_result.get('time_spent_total', 0)}秒

## 上下文
- 学习者ID：{learner_id}
- 当前资源ID：{resource_id}

请分析并决策，输出JSON：
{{
    "action": "simplify/advance/regenerate/continue",
    "reason": "决策理由(30-80字)",
    "target_topics": ["需要关注的特定知识点"],
    "suggested_difficulty": "beginner/intermediate/advanced",
    "confidence": 0.0-1.0
}}"""

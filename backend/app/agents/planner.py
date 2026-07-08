"""学习路径规划Agent — 根据审核通过的资源构建个性化学习路径"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个学习路径规划专家。你的任务是：
1. 基于学习者画像和审核通过的资源，构建渐进式学习路径
2. 确定知识点之间的前后依赖关系
3. 为每个阶段分配资源和预估时间
4. 考虑难度梯度（基础→进阶→挑战）

输出必须为严格的JSON格式。"""


class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="学习路径规划Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.3,
        )

    def process(self, state: dict) -> dict:
        diagnosis = state.get("diagnosis_result", {})
        approved_resources = state.get("final_resources", [])
        prompt = self._build_prompt(diagnosis, approved_resources)
        result = self.call_llm_json(prompt)
        return {"learning_path": result}

    def _build_prompt(self, diagnosis: dict, resources: list) -> str:
        import json
        return f"""## 学习者画像
- 知识掌握度：{json.dumps(diagnosis.get('knowledge_map', {}), ensure_ascii=False)}
- 技能盲区：{json.dumps(diagnosis.get('skill_gaps', []), ensure_ascii=False)}
- 学习风格：{diagnosis.get('learning_style', 'unknown')}
- 难度等级：{diagnosis.get('recommended_difficulty', 'beginner')}

## 可用资源
{json.dumps(resources, ensure_ascii=False, indent=2)[:3000]}

请规划学习路径，输出JSON：
{{
    "phases": [
        {{
            "phase_number": 1,
            "title": "阶段名称",
            "description": "阶段目标",
            "resources": [{{"resource_id": "xxx", "order": 1, "reason": "为什么先学这个"}}],
            "estimated_days": 7,
            "checkpoint": "阶段检查点描述"
        }}
    ],
    "total_estimated_days": 30,
    "learning_tips": "给学习者的建议(50-100字)",
    "prerequisites_map": {{"知识点A": ["前置知识点1", "前置知识点2"]}}
}}"""

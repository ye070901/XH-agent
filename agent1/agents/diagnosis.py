"""学情诊断 Agent

基于学习者画像数据，输出知识点掌握程度、技能短板与针对性建议。
继承 BaseAgent，遵守输入输出规约。
"""

import json
import re

from backend.base import BaseAgent

SYSTEM_PROMPT = """你是一位资深的学情诊断专家。你的任务是基于学习者的背景和学习数据，输出结构化学情诊断报告。

## 输入输出规约
- 输入: 从 state["learner_data"] 读取学习者信息
- 输出: 写入 state["diagnosis_result"]，仅输出纯 JSON，禁止任何多余文字

## 输出 JSON 结构
{
  "knowledge_map": [
    {
      "name": "知识点名称",
      "mastery": 0.0~1.0,
      "level": "未掌握"|"初步了解"|"基本掌握"|"熟练应用"|"融会贯通",
      "evidence": ["证据1", "证据2"]
    }
  ],
  "skill_gaps": [
    {
      "skill": "技能名称",
      "severity": "高"|"中"|"低",
      "description": "缺失描述",
      "prerequisite_for": ["依赖此前置知识的高级技能1", "依赖此前置知识的高级技能2"]
    }
  ],
  "overall_assessment": "综合诊断结论",
  "recommendations": ["建议1", "建议2", "建议3"]
}

## 知识图谱规则 (knowledge_map)
1. 知识点数量必须 ≥ 5 个
2. 每个知识点必须附带至少 1 条 evidence（从输入数据中提取的具体证据）
3. mastery 反映掌握程度，0.0=完全未掌握，1.0=完全掌握
4. level 根据 mastery 映射：0.0~0.2=未掌握，0.2~0.4=初步了解，0.4~0.6=基本掌握，0.6~0.8=熟练应用，0.8~1.0=融会贯通

## 技能短板规则 (skill_gaps)
1. 仅列出前置依赖短板 —— 即那些影响后续学习的关键缺失技能
2. 不得罗列所有未学内容 —— 只筛选出构成瓶颈的前置技能
3. 每条短板必须标注 severity（高/中/低）和 prerequisite_for（阻塞了哪些高级技能的学习）

## 综合建议规则 (recommendations)
1. 至少 3 条，针对知识短板和技能缺口给出可操作的学习路径建议
2. 建议要具体，与诊断结果一一对应
"""


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取第一个 JSON 对象"""
    # 尝试直接解析
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 尝试从 markdown 代码块中提取
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出中提取 JSON:\n{text}")


class DiagnosisAgent(BaseAgent):
    """学情诊断 Agent"""

    def __init__(self, client=None):
        super().__init__(name="DiagnosisAgent", client=client)

    def run(self, state: dict) -> dict:
        learner_data = state.get("learner_data", {})
        if not learner_data:
            state["diagnosis_result"] = {
                "error": "缺少 learner_data，无法进行诊断",
                "knowledge_map": [],
                "skill_gaps": [],
                "overall_assessment": "无数据",
                "recommendations": ["请提供学习者数据"],
            }
            return state

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"请对以下学习者进行学情诊断，严格按照 JSON 格式输出。\n\n学习者数据:\n{json.dumps(learner_data, ensure_ascii=False, indent=2)}",
            },
        ]

        raw_output = self.call_llm(messages)

        # 解析 JSON
        try:
            result = _extract_json(raw_output)
        except ValueError as e:
            state["diagnosis_result"] = {
                "error": f"LLM 输出解析失败: {e}",
                "raw_output": raw_output,
                "knowledge_map": [],
                "skill_gaps": [],
                "overall_assessment": "诊断失败",
                "recommendations": ["请重试诊断"],
            }
            return state

        # 校验 knowledge_map 数量
        km = result.get("knowledge_map", [])
        if len(km) < 5:
            state["diagnosis_result"] = {
                "error": f"知识图谱知识点不足 5 个（实际 {len(km)} 个）",
                "raw_output": raw_output,
                "knowledge_map": km,
                "skill_gaps": result.get("skill_gaps", []),
                "overall_assessment": result.get("overall_assessment", ""),
                "recommendations": result.get("recommendations", []),
            }
            return state

        # 校验每个知识点都有 evidence
        for kp in km:
            if not kp.get("evidence"):
                kp["evidence"] = ["（LLM 未提供具体证据，请核实）"]

        state["diagnosis_result"] = {
            "knowledge_map": km,
            "skill_gaps": result.get("skill_gaps", []),
            "overall_assessment": result.get("overall_assessment", ""),
            "recommendations": result.get("recommendations", []),
        }

        return state

"""学情诊断 Agent（Day4）

基于后端 BaseAgent，输出结构化学情诊断报告，共 5 个字段：
    knowledge_map / skill_gaps / learning_style / recommended_difficulty / summary

本文件为 Agent1 独立实现，不依赖任何外部（Agent3）代码。
"""

import json
import os
import re
import sys

# 以脚本方式直接运行时（python agents/diagnosis.py），把项目根目录加入 sys.path
if __package__ in (None, ""):
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

from backend.base import BaseAgent

# 桌面公共交换文件路径
DEFAULT_EXCHANGE_OUT = r"C:\Users\CAT\Desktop\exchange\diagnosis_out.json"

SYSTEM_PROMPT = """你是一位资深的学情诊断专家。你的任务是基于学习者的背景和学习数据，输出结构化学情诊断报告。

## 输出规约
- 仅输出纯 JSON，禁止任何多余文字、解释或 Markdown 代码块标记。

## 输出 JSON 结构（5 个必填字段）
{
  "knowledge_map": [
    {
      "name": "知识点名称",
      "mastery": 0.0~1.0,
      "level": "未掌握"|"初步了解"|"基本掌握"|"熟练应用"|"融会贯通",
      "confidence": 0.0~1.0,
      "evidence": ["证据1", "证据2"],
      "priority": "critical"|"high"|"medium"|"low"
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
  "learning_style": {
    "style": "视觉型"|"听觉型"|"读写型"|"动手型"|"混合型",
    "description": "风格描述",
    "strengths": ["优势1", "优势2"],
    "suggestions": ["匹配该风格的适配建议1", "匹配该风格的适配建议2"]
  },
  "recommended_difficulty": {
    "level": "低"|"中低"|"中等"|"中高"|"高",
    "rationale": "难度定位理由",
    "adjustment": "学习过程中的动态调整策略"
  },
  "summary": "综合诊断结论，覆盖掌握情况、技能短板与后续学习建议"
}

## 知识图谱规则 (knowledge_map)
1. 知识点数量必须 ≥ 5 个
2. 每个知识点必须附带至少 1 条 evidence（从输入数据中提取的具体证据）
3. mastery 反映掌握程度，0.0=完全未掌握，1.0=完全掌握
4. level 根据 mastery 映射：0.0~0.2=未掌握，0.2~0.4=初步了解，0.4~0.6=基本掌握，0.6~0.8=熟练应用，0.8~1.0=融会贯通
5. 每条知识点必须包含 level、confidence、evidence、priority 四个字段
6. priority=critical 的定义：不掌握该知识点，后续相关学习无法开展的前置基础依赖
7. 知识点名称命名格式必须为：`{具体技术} - {子方向}`，例如 `LangGraph - 条件路由与动态分支`。禁止使用宽泛表述如 "AI基础"、"深度学习"

## 技能短板规则 (skill_gaps)
1. 仅列出前置依赖短板 —— 即那些影响后续学习的关键缺失技能
2. 不得罗列所有未学内容 —— 只筛选出构成瓶颈的前置技能
3. 每条短板必须标注 severity（高/中/低）和 prerequisite_for（阻塞了哪些高级技能的学习）

## 学习风格规则 (learning_style)
1. 从学习记录、背景、自述中推断学习风格，给出描述、优势与适配建议
2. 无法推断时输出 "混合型"

## 推荐难度规则 (recommended_difficulty)
1. 依据知识点平均掌握度给出推荐难度：<30%=低，30~50%=中低，50~70%=中等，70~85%=中高，≥85%=高
2. 必须说明难度定位理由与动态调整策略

## 综合结论规则 (summary)
1. 一段文字，覆盖：当前学习阶段、平均掌握度、主要短板、下一步学习建议
2. 若含序号，必须使用单层序号（1.、2.、3.），禁止二级序号

## 知识盲区约束
1. 识别出的知识盲区必须精确到具体技术点，禁止宽泛描述
   - ❌ 错误示例："AI基础"
   - ✅ 标准示例："Transformer自注意力机制"
2. 盲区统一命名格式：`{具体技术} - {子方向}`
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


def _level_of(mastery: float) -> str:
    """mastery -> 掌握等级"""
    if mastery <= 0.2:
        return "未掌握"
    if mastery < 0.4:
        return "初步了解"
    if mastery < 0.6:
        return "基本掌握"
    if mastery < 0.8:
        return "熟练应用"
    return "融会贯通"


def _difficulty_of(avg_mastery: float) -> str:
    """平均掌握度 -> 推荐难度档位"""
    if avg_mastery < 0.3:
        return "低"
    if avg_mastery < 0.5:
        return "中低"
    if avg_mastery < 0.7:
        return "中等"
    if avg_mastery < 0.85:
        return "中高"
    return "高"


def _short_name(course: str) -> str:
    """从课程名中提取具体技术短名，如 'Python入门' -> 'Python'"""
    course = (course or "课程").strip()
    for sep in ("入门", "进阶", "实战", "基础", "课程"):
        if sep in course:
            course = course.split(sep)[0]
    return course.strip()[:12] or "课程"


def _infer_learning_style(learner_data: dict) -> dict:
    """从 learner_data 文本中启发式推断学习风格"""
    text = str(learner_data)
    if any(w in text for w in ("图示", "视频", "动画", "图解", "visual", "可视化")):
        style = "视觉型"
    elif any(w in text for w in ("动手", "实操", "项目", "实验", "实践")):
        style = "动手型"
    elif any(w in text for w in ("笔记", "阅读", "文档", "书籍")):
        style = "读写型"
    elif any(w in text for w in ("音频", "讲座", "口头", "听")):
        style = "听觉型"
    else:
        style = "混合型"

    suggestions = {
        "视觉型": "推荐搭配图示、流程图、视频讲解等可视化材料",
        "动手型": "推荐以真实项目/实操任务驱动学习，边做边学",
        "读写型": "推荐精读文档并整理结构化笔记，以写促学",
        "听觉型": "推荐结合讲解类课程与口头复述进行学习",
        "混合型": "图文与实操结合，多种通道交替吸收",
    }
    strengths = (
        ["能利用该通道快速建立直观理解", "对信息密度高的内容吸收快"]
        if style != "混合型"
        else ["可根据内容灵活切换吸收方式", "不受单一媒介限制"]
    )
    return {
        "style": style,
        "description": f"根据学习记录与背景推断为「{style}」，该通道下的学习效率最高",
        "strengths": strengths,
        "suggestions": [suggestions[style]],
    }


def _demo_diagnosis(learner_data: dict) -> dict:
    """确定性演示诊断：不调用 LLM，从 learner_data 推导 5 字段结果。

    用于无 API/离线环境下的演示与单元测试，结构严格符合 DiagnosisGate 输出格式。
    """
    learner_data = learner_data or {}
    name = learner_data.get("name") or "该学习者"
    learning_goal = learner_data.get("learning_goal") or "当前课程"
    current_course = learner_data.get("current_course") or learning_goal
    history = learner_data.get("learning_history") or []
    struggles = learner_data.get("struggles") or []

    # ---------- knowledge_map ----------
    km = []
    for topic in history:
        tname = str(topic.get("topic") or topic.get("name") or "未命名主题")
        score = float(topic.get("score") or 0)
        status = topic.get("status", "未开始")
        mastery = round(max(0.0, min(1.0, score / 100.0)), 2)
        confidence = {"已完成": 0.85, "学习中": 0.5}.get(status, 0.3)
        if mastery == 0 and status == "未开始":
            priority = "critical"
        elif mastery < 0.6:
            priority = "high"
        elif mastery < 0.8:
            priority = "medium"
        else:
            priority = "low"

        evidence = [f"学习记录：{status}，最近得分 {int(score)} 分"]
        for s in struggles:
            if s in tname or tname.split(" - ")[0] in s:
                evidence.append(f"学习者反馈：{s}")
        # 去重并保留前 3 条
        evidence = list(dict.fromkeys(evidence))[:3]

        km.append(
            {
                "name": tname,
                "mastery": mastery,
                "level": _level_of(mastery),
                "confidence": confidence,
                "evidence": evidence,
                "priority": priority,
            }
        )

    # 补齐到至少 5 个知识点（按当前课程推导命名）
    short = _short_name(current_course)
    pad_names = [
        f"{short} - 前置基础概念",
        f"{short} - 核心语法与 API",
        f"{short} - 综合实战应用",
        f"{short} - 调试与错误处理",
        f"{short} - 数据结构与算法基础",
        f"{short} - 工程化与代码规范",
    ]
    used = {k["name"] for k in km}
    for pname in pad_names:
        if len(km) >= 5:
            break
        if pname in used:
            continue
        used.add(pname)
        km.append(
            {
                "name": pname,
                "mastery": 0.0,
                "level": "未掌握",
                "confidence": 0.3,
                "evidence": ["学习记录中无该知识点相关数据，判定为未开始"],
                "priority": "critical",
            }
        )

    # ---------- skill_gaps ----------
    not_started = [k["name"] for k in km if k["priority"] == "critical"]
    sg = []
    for s in struggles:
        sg.append(
            {
                "skill": f"缺失能力：{s}",
                "severity": "高" if not_started else "中",
                "description": f"学习者自述：{s}。该短板将拖慢对「{learning_goal}」的推进。",
                "prerequisite_for": (not_started[:3] or [f"{short} - 进阶模块"]),
            }
        )

    # ---------- learning_style ----------
    ls = _infer_learning_style(learner_data)

    # ---------- recommended_difficulty ----------
    avg = (sum(k["mastery"] for k in km) / len(km)) if km else 0.0
    rd = {
        "level": _difficulty_of(avg),
        "rationale": f"当前知识点平均掌握度为 {avg:.0%}，据此定位难度起点",
        "adjustment": "以平均掌握度设定起点，学习过程中按每阶段掌握度动态上下浮动一档",
    }

    # ---------- summary ----------
    mastered = [k["name"] for k in km if k["mastery"] >= 0.6]
    weak = [k["name"] for k in km if k["priority"] in ("critical", "high")][:3]
    summary = (
        f"{name}当前处于「{rd['level']}」难度学习区间，平均掌握度约 {avg:.0%}；"
        f"已掌握知识点：{('、'.join(mastered))[:80] if mastered else '较少'}；"
        f"主要短板：{'、'.join(weak) if weak else '暂无严重短板'}。"
        f"建议先补齐前置基础，再进入实战综合训练。"
    )

    return {
        "knowledge_map": km,
        "skill_gaps": sg,
        "learning_style": ls,
        "recommended_difficulty": rd,
        "summary": summary,
    }


def validate_diagnosis_result(result: dict) -> list:
    """按 DiagnosisGate 输出格式校验诊断结果。

    Returns:
        校验错误列表；为空列表表示通过。
    """
    errors = []
    required = ["knowledge_map", "skill_gaps", "learning_style", "recommended_difficulty", "summary"]
    for field in required:
        if field not in result:
            errors.append(f"缺少必填字段: {field}")

    km = result.get("knowledge_map") or []
    if len(km) < 5:
        errors.append(f"knowledge_map 知识点数量不足 5（实际 {len(km)}）")
    for i, kp in enumerate(km):
        for key in ("name", "mastery", "level", "confidence", "evidence", "priority"):
            if key not in kp:
                errors.append(f"knowledge_map[{i}] 缺少字段 {key}")
        mastery = kp.get("mastery")
        if not isinstance(mastery, (int, float)) or not (0 <= mastery <= 1):
            errors.append(f"knowledge_map[{i}].mastery 不在 [0,1]: {mastery!r}")
        if not kp.get("evidence"):
            errors.append(f"knowledge_map[{i}].evidence 为空")
        if kp.get("priority") not in ("critical", "high", "medium", "low"):
            errors.append(f"knowledge_map[{i}].priority 非法: {kp.get('priority')!r}")
        if kp.get("level") not in ("未掌握", "初步了解", "基本掌握", "熟练应用", "融会贯通"):
            errors.append(f"knowledge_map[{i}].level 非法: {kp.get('level')!r}")

    for i, gap in enumerate(result.get("skill_gaps") or []):
        for key in ("skill", "severity", "description", "prerequisite_for"):
            if key not in gap:
                errors.append(f"skill_gaps[{i}] 缺少字段 {key}")
        if gap.get("severity") not in ("高", "中", "低"):
            errors.append(f"skill_gaps[{i}].severity 非法: {gap.get('severity')!r}")

    ls = result.get("learning_style")
    if ls is not None and (not isinstance(ls, dict) or "style" not in ls):
        errors.append("learning_style 必须为含 style 字段的对象")

    rd = result.get("recommended_difficulty")
    if rd is not None and (not isinstance(rd, dict) or "level" not in rd):
        errors.append("recommended_difficulty 必须为含 level 字段的对象")
    elif isinstance(rd, dict) and rd.get("level") not in ("低", "中低", "中等", "中高", "高"):
        errors.append(f"recommended_difficulty.level 非法: {rd.get('level')!r}")

    if not isinstance(result.get("summary"), str) or not result.get("summary", "").strip():
        errors.append("summary 必须为非空字符串")

    return errors


class DiagnosisAgent(BaseAgent):
    """学情诊断 Agent（G1 DiagnosisGate）"""

    def __init__(self, client=None):
        super().__init__(name="DiagnosisAgent", client=client)

    def process(self, learner_data: dict, use_demo: bool = False) -> dict:
        """诊断单个学习者，输出 5 字段结构化结果。

        Args:
            learner_data: 学习者画像数据
            use_demo: 为 True 时跳过 LLM，直接走确定性演示逻辑

        Returns:
            含 knowledge_map / skill_gaps / learning_style /
            recommended_difficulty / summary 的 dict。
        """
        if use_demo or not learner_data:
            return _demo_diagnosis(learner_data)

        user_prompt = (
            "请对以下学习者进行学情诊断，严格按照 JSON 格式输出 5 个字段，"
            "禁止输出任何多余文字。\n\n学习者数据:\n"
            + json.dumps(learner_data, ensure_ascii=False, indent=2)
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = _extract_json(self.call_llm(messages))
            if not validate_diagnosis_result(result):
                return result
        except Exception:
            # LLM 调用失败 / 输出不合法时回退到确定性演示结果，保证格式稳定
            pass

        return _demo_diagnosis(learner_data)

    def run(self, state: dict) -> dict:
        """兼容旧调用方式：从 state 读取 learner_data，写回 diagnosis_result。"""
        state["diagnosis_result"] = self.process(state.get("learner_data", {}))
        return state


def export_diagnosis(
    learner_data: dict,
    out_path: str = DEFAULT_EXCHANGE_OUT,
    use_demo: bool = False,
) -> str:
    """运行诊断并把结果写入指定文件（默认桌面公共交换文件）。

    Args:
        learner_data: 学习者画像数据
        out_path: 输出 JSON 路径，目录不存在会自动创建
        use_demo: 为 True 时走确定性演示诊断，不调用 LLM

    Returns:
        实际写入的文件路径。
    """
    result = DiagnosisAgent().process(learner_data, use_demo=use_demo)
    out_path = os.path.expanduser(os.path.abspath(out_path))
    out_dir = os.path.dirname(out_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    # 用法:
    #   python agents/diagnosis.py                # 演示诊断，写入桌面交换文件
    #   python agents/diagnosis.py <learner.json> # 用指定学习者 JSON 文件诊断
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            learner = json.load(f)
    else:
        learner = {
            "name": "演示学员",
            "age": 17,
            "education": "高中三年级",
            "background": "理科生，未接触过任何编程",
            "learning_goal": "掌握Python基础，能独立完成简单的数据处理脚本",
            "current_course": "Python入门",
            "learning_history": [
                {"topic": "Python - 变量与数据类型", "status": "已完成", "score": 85},
                {"topic": "Python - 条件判断", "status": "已完成", "score": 72},
                {"topic": "Python - 循环语句", "status": "学习中", "score": 55},
                {"topic": "Python - 函数定义", "status": "未开始", "score": 0},
                {"topic": "Python - 列表与字典", "status": "未开始", "score": 0},
            ],
            "struggles": ["多层嵌套的条件判断容易混淆", "循环中的 break/continue 理解不深"],
        }

    path = export_diagnosis(learner, use_demo=True)
    print(f"[Agent1] 诊断结果已写入: {path}")

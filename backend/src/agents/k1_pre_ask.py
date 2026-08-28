# -*- coding: utf-8 -*-
"""
K1 前置启发式追问：目标收窄（A · 最高优先级）
═══════════════════════════════════════════════════════
对应 PHASE3_PLAN.md §4.5 K1-A 与决策 D9：
  用户填完信息后、生成之前，判断学习目标是否过宽（如“我想学机器人”）
  → 启发式追问细化到具体方向（如“FANUC 示教器点位编程”）
  → 收窄后触发资源生成。
  命中创新点：【动态追问与启发式交互导学】。

判定方式（已定 · 混合式）：
  1) 规则先行 —— 目标字数 / 关键词数量 / 是否含具体厂商·设备·任务词等
     硬指标。规则能判则判（轻量判断用规则）。
  2) 规则判不清（如只有厂商词、缺任务环节）→ 注入 LLM 辅助判断兜底
     （复杂判断用 LLM）。

边界（已定）：K1 不直接改 Agent1 内部。
  收窄后的目标通过 state["learner_data"] 传参，learning_goal 字段被替换为
  refined_target，由 Agent1 学情诊断承接收窄后的目标（见 INTERFACE_CONTRACT.md）。

对外统一入口函数：
  pre_ask_pipeline(goal, learner_data=None, followup_answers=None, llm_handler=None)
"""

from __future__ import annotations

import re
from typing import Any

# ═══════════════════════════════════════════════════════════
# 硬指标词典（领域：工业机器人编程与调试，FANUC / KUKA / ABB）
# 分三类：厂商词 / 设备词 / 任务环节词 —— 用于规则先行判定“目标过宽”
# ═══════════════════════════════════════════════════════════

BRAND_KEYWORDS: tuple[str, ...] = (
    "FANUC",
    "发那科",
    "KUKA",
    "库卡",
    "ABB",
)

DEVICE_KEYWORDS: tuple[str, ...] = (
    "示教器",
    "示教盒",
    "机器人本体",
    "控制柜",
    "R-30iB",
    "R-2000iC",
    "离线仿真",
    "ROBOGUIDE",
    "KUKA.Sim",
    "IRC5",
    "控制器",
    "外部轴",
)

TASK_KEYWORDS: tuple[str, ...] = (
    "点位编程",
    "示教编程",
    "搬运",
    "码垛",
    "焊接",
    "弧焊",
    "点焊",
    "喷涂",
    "装配",
    "轨迹规划",
    "TCP标定",
    "标定",
    "IO配置",
    "信号配置",
    "视觉引导",
    "追剪",
    "打磨",
    "上下料",
    "运动指令",
    "调试",
    "报警处理",
)

# ═══════════════════════════════════════════════════════════
# 追问维度（启发式导学维度），按优先级排列。
#   base 维度是画像感知点：若 learner_data 已带领域证据则自动跳过，减少打扰。
# ═══════════════════════════════════════════════════════════

ASK_DIMENSIONS: tuple[str, ...] = ("direction", "task", "goal_level", "base")

DIMENSION_QUESTIONS: dict[str, dict[str, str]] = {
    "direction": {
        "ask_content": "您想聚焦哪个品牌 / 平台的学习？例如 FANUC、KUKA、ABB 的示教编程。",
        "help": "品牌越具体，资源越能落到对应控制器与指令体系。",
    },
    "task": {
        "ask_content": (
            "您要主攻哪个具体任务 / 环节？例如：点位编程、搬运码垛、焊接工艺、"
            "TCP 标定、示教器操作。"
        ),
        "help": "任务明确了，才能映射到领域核心知识点清单。",
    },
    "goal_level": {
        "ask_content": "您希望达到什么水平？入门了解 / 能独立完成单个任务 / 掌握完整调试流程。",
        "help": "目标深度决定资源难度与教学密度。",
    },
    "base": {
        "ask_content": "您之前是否接触过示教器或机器人编程？（有 / 无 / 用过但没系统学过）",
        "help": "用于校准起点与后续诊断基线。",
    },
}


def _clean(s: str) -> str:
    """清洗目标文本：去首尾空白、压缩连续空白、统一大写。"""
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def _hit_words(goal: str, keywords: tuple[str, ...]) -> list[str]:
    """返回 goal 中命中的某类关键词（用于硬指标信号）。"""
    upper = _clean(goal)
    return [kw for kw in keywords if kw.upper() in upper]


def _extract_signals(goal: str) -> dict[str, Any]:
    """抽取目标文本的硬指标信号。

    Returns:
        dict: 含 length / brand / device / task / has_brand / has_task
    """
    raw = (goal or "").strip()
    brand = _hit_words(raw, BRAND_KEYWORDS)
    device = _hit_words(raw, DEVICE_KEYWORDS)
    task = _hit_words(raw, TASK_KEYWORDS)
    return {
        "length": len(raw),
        "brand": brand,
        "device": device,
        "task": task,
        "has_brand": len(brand) > 0,
        "has_task": len(task) > 0,
    }


def _rule_verdict(signals: dict[str, Any]) -> tuple[str, str, float]:
    """规则先行判定（不调 LLM）。

    Args:
        signals: _extract_signals 的输出。

    Returns:
        (verdict, reason, score):
          verdict: "wide" 明确过宽 / "specific" 明确够具体 / "unknown" 判不清需兜底
          score:   具体度评分 0~1（1 越具体）
    """
    score = 0.0
    if signals["length"] <= 4:
        return "wide", "目标过短，缺少可定位的具体方向", 0.1
    if signals["has_brand"]:
        score += 0.35
    if signals["device"]:
        score += 0.30
    if signals["task"]:
        score += 0.40
    score = min(1.0, score)

    if signals["has_brand"] and signals["has_task"]:
        return "specific", "已含具体厂商与任务环节，足够收窄", score
    if signals["task"] and (signals["has_brand"] or signals["device"]):
        return "specific", "已定位到具体任务并带设备/品牌语境", score
    if not signals["has_brand"] and not signals["task"] and signals["length"] <= 12:
        return "wide", "缺少厂商与任务词，目标过宽", score

    # 只有方向（品牌或设备）而无任务环节 → 半具体，交由追问细化或 LLM 兜底
    if signals["has_brand"] and not signals["task"]:
        return "unknown", "已有品牌方向，缺具体任务环节（可补问或走 LLM 兜底）", score
    return "unknown", "规则判不清边界，需启发式追问细化", score


def analyze_goal(
    goal: str,
    learner_data: dict[str, Any] | None = None,
    llm_handler: Any | None = None,
) -> dict[str, Any]:
    """混合式“目标过宽”判定（规则先行 + LLM 兜底）。

    Args:
        goal:        用户填写的学习目标文本。
        learner_data: 可选，state["learner_data"] 画像（用于画像感知追问）。
        llm_handler:  可选 LLM 兜底判定器，签名 handler(goal: str) -> dict
                      （期望返回 {"too_wide": bool, "reason": str}）。
                      不传则仅在规则判定为 unknown 时返回“需追问”，不调用 LLM。

    Returns:
        dict: too_wide / judgment / reason / score / signals /
              how("rule"|"llm"|"ask") / need_dimension
    """
    signals = _extract_signals(goal)
    verdict, reason, score = _rule_verdict(signals)

    if verdict == "wide":
        return {
            "too_wide": True,
            "judgment": "wide",
            "reason": reason,
            "score": score,
            "signals": signals,
            "how": "rule",
            "need_dimension": "direction" if not signals["has_brand"] else "task",
        }

    if verdict == "specific":
        return {
            "too_wide": False,
            "judgment": "specific",
            "reason": reason,
            "score": score,
            "signals": signals,
            "how": "rule",
            "need_dimension": None,
        }

    # ── 规则判不清：优先启发式追问补齐任务环节；调用方要求 LLM 兜底时也可用 LLM ──
    if llm_handler is not None:
        try:
            judge = llm_handler(goal) or {}
            too_wide = bool(judge.get("too_wide", True))
            return {
                "too_wide": too_wide,
                "judgment": "wide" if too_wide else "specific",
                "reason": judge.get("reason") or reason,
                "score": score,
                "signals": signals,
                "how": "llm",
                "need_dimension": "task" if too_wide else None,
            }
        except Exception:
            # LLM 兜底失败 → 回落到追问路径，不阻断流程
            pass

    return {
        "too_wide": True,
        "judgment": "unknown",
        "reason": reason,
        "score": score,
        "signals": signals,
        "how": "ask",
        "need_dimension": "task",
    }


def _has_profile_evidence(learner_data: dict[str, Any] | None) -> bool:
    """判断画像是否已携带领域证据（命中则跳过 base 追问，体现画像感知）。"""
    if not learner_data:
        return False
    pretests = learner_data.get("pretest_results") or []
    skills = learner_data.get("skills_used") or []
    if pretests and len(pretests) > 0:
        return True
    return any(
        any(kw.upper() in _clean(str(s)) for kw in (*BRAND_KEYWORDS, *DEVICE_KEYWORDS))
        for s in skills
    )


def pick_ask_dimension(
    analysis: dict[str, Any],
    learner_data: dict[str, Any] | None = None,
    asked: list[str] | None = None,
) -> str | None:
    """按优先级挑选下一个追问维度（启发式多轮导学）。

    尽量第一问就命中缺口维度（direction / task），失败再补充 goal_level / base。

    Args:
        analysis: analyze_goal 的输出。
        learner_data: 画像，用于跳过已有证据的 base 维度。
        asked: 已问过的维度列表，避免同一轮重复提问。

    Returns:
        str | None: 需追问的维度名；None 表示无需再问。
    """
    asked_set = set(asked or [])
    # 先按硬缺口维度走
    need = analysis.get("need_dimension")
    if need and need not in asked_set:
        return need
    # 再按优先级列表补齐
    for d in ASK_DIMENSIONS:
        if d in asked_set:
            continue
        if d == "base" and _has_profile_evidence(learner_data):
            continue
        return d
    return None


def _pick_brand_word(answer: str) -> str:
    """ "从追问答案里提取厂商词（大写规整）。"""
    for kw in BRAND_KEYWORDS:
        if kw.upper() in _clean(answer):
            return kw
    return ""


def _pick_task_word(answer: str) -> str:
    """从追问答案里提取任务环节词。"""
    for kw in TASK_KEYWORDS:
        if kw.upper() in _clean(answer):
            return kw
    return ""


def compose_refined_target(
    original_goal: str,
    answers: dict[str, Any] | None,
) -> str:
    """把多轮追问的回答合成收窄后的学习目标。

    合成优先级：厂商词 + 任务环节词 > 单任务词 > 原始目标补全。

    Args:
        original_goal: 用户最初填写的目标。
        answers: {dimension: 用户回答文字} 的字典。

    Returns:
        str: 收窄后的目标（供写入 learner_data["learning_goal"]）。
    """
    answers = answers or {}
    brand = _pick_brand_word(answers.get("direction", ""))
    task = _pick_task_word(answers.get("task", ""))

    if brand and task:
        refined = f"{brand} {task}"
    elif task:
        refined = task
    elif brand:
        refined = f"{brand} 相关学习"
    else:
        # 兜底：把 goal_level 合并进原始目标
        level = (answers.get("goal_level") or "").strip()
        refined = f"{original_goal.strip()}（{level}）" if level else original_goal.strip()
    return refined.strip()


def pre_ask_pipeline(
    goal: str,
    learner_data: dict[str, Any] | None = None,
    followup_answers: dict[str, Any] | None = None,
    llm_handler: Any | None = None,
) -> dict[str, Any]:
    """前置启发式追问统一入口（对外调用）。

    本函数支持多轮导学：
      - 第一轮：不传 followup_answers 或传空 → 判定目标是否过宽；过宽则返回
        首轮追问问题（need_ask=True, ask_content）。
      - 后续轮：把上一轮用户回答以 {dimension: 回答} 传入 followup_answers，
        内部合成收窄目标并重新判定；直至收敛为具体目标后
        触发资源生成（trigger_generation=True），并返回可写回
        learner_data["learning_goal"] 的 refined_target。

    Args:
        goal:             用户初始学习目标。
        learner_data:     state["learner_data"]，用于画像感知追问。
        followup_answers: 多轮追问答案 {维度: 回答}。
        llm_handler:      可选 LLM 兜底判定器（见 analyze_goal）。

    Returns:
        dict:
          need_ask / ask_content / asked_dimension / refined_target /
          too_wide / reason / judged_by / trigger_generation /
          learner_data（learning_goal 已替换为 refined_target，供 Agent1 消费）
    """
    # 多轮导学：携带跟进答案时，先合成为候选收窄目标再重新判定
    # （实现“追问 → 收窄 → 再判定”的启发式闭环，而非机械重复首轮问题）
    target_goal = compose_refined_target(goal, followup_answers) if followup_answers else goal
    analysis = analyze_goal(target_goal, learner_data, llm_handler)

    # 已判定足够具体 → 直接可收输出（含首轮即具体、追问后收敛场景）
    if not analysis["too_wide"]:
        refined = target_goal
        learner = dict(learner_data or {})
        learner["learning_goal"] = refined
        return {
            "need_ask": False,
            "ask_content": None,
            "asked_dimension": None,
            "refined_target": refined,
            "too_wide": False,
            "reason": analysis["reason"],
            "judged_by": analysis["how"],
            "trigger_generation": True,
            "learner_data": learner,
        }

    # 目标过宽 → 进入多轮启发式提问（先合成已收集的回答，再挑下一问维度）
    dimension = pick_ask_dimension(analysis, learner_data)

    if dimension is None:
        # 所有维度都问过了仍过宽 → 以合成目标收尾，避免无限追问
        refined = compose_refined_target(target_goal, None) or target_goal
        learner = dict(learner_data or {})
        learner["learning_goal"] = refined
        return {
            "need_ask": False,
            "ask_content": None,
            "asked_dimension": None,
            "refined_target": refined,
            "too_wide": False,
            "reason": "多轮追问后已尽力收窄，按最新合成目标继续",
            "judged_by": analysis["how"],
            "trigger_generation": True,
            "learner_data": learner,
        }

    qtpl = DIMENSION_QUESTIONS.get(dimension, {})
    return {
        "need_ask": True,
        "ask_content": qtpl.get("ask_content", "请补充更具体的学习方向。"),
        "asked_dimension": dimension,
        "refined_target": None,
        "too_wide": True,
        "reason": analysis["reason"],
        "judged_by": analysis["how"],
        "trigger_generation": False,
        "learner_data": dict(learner_data or {}),
    }


if __name__ == "__main__":
    # ── 单元自测：可独立运行，验证规则先行 + 多轮追问闭环 ──
    print("== 场景1：目标过宽（无厂商无任务） ==")
    r1 = pre_ask_pipeline("我想学机器人")
    print(r1["need_ask"], "| 首问:", r1["ask_content"], "| 维度:", r1["asked_dimension"])

    print("== 场景2：多轮追问收窄 ==")
    r2 = pre_ask_pipeline(
        "我想学机器人",
        followup_answers={"direction": "FANUC", "task": "点位编程"},
    )
    print(
        "need_ask:",
        r2["need_ask"],
        "| 收窄目标:",
        r2["refined_target"],
        "| 触发生成:",
        r2["trigger_generation"],
    )
    assert r2["refined_target"] == "FANUC 点位编程", r2
    # learner_data 契约对齐：learning_goal 已替换
    assert r2["learner_data"]["learning_goal"] == "FANUC 点位编程"

    print("== 场景3：目标已具体（直接过） ==")
    r3 = pre_ask_pipeline("FANUC 示教器点位编程")
    print("need_ask:", r3["need_ask"], "| expanded:", r3["refined_target"])

    print("== 场景4：画像感知（带 pretest 跳过 base 维度） ==")
    r4 = pre_ask_pipeline(
        "想学KUKA",
        learner_data={
            "pretest_results": [{"test_name": "前置摸底", "total_score": 40, "max_score": 100}]
        },
    )
    print(
        "need_ask:",
        r4["need_ask"],
        "| 首问维度:",
        r4["asked_dimension"],
        "（应跳过 base 优先补齐 task）",
    )

    print("== 场景5：LLM 兜底（规则判不清时注入） ==")

    def fake_llm(g):
        return {"too_wide": True, "reason": "LLM 判定仍需补任务环节"}

    r5 = pre_ask_pipeline("想学KUKA", llm_handler=fake_llm)
    print("judged_by:", r5["judged_by"], "| 追问维度:", r5["asked_dimension"])

    print("\\n全部场景断言通过")

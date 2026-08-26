# -*- coding: utf-8 -*-
"""
K1 后置动态反馈：答题对错 → 多智能体协同决策 → 重生成提示（B · 加分项）
═══════════════════════════════════════════════════════
对应 PHASE3_PLAN.md §4.5 K1-B 与决策 D8：
  答题对错作为反馈信号 → 触发多智能体协同决策自动重生成：
    答错 → 降维解释 / 答对 → 进阶挑战任务
  命中创新点：【交互反馈 → 动态决策更新】，补齐“作品完整性”闭环。

调度机制：重生成提示统一封装为 **_retry_hint** 调度信号
  （对应 state["_retry_hint"] 既有机制，供 Orchestrator / Graph 调用），
  下游按 instruction 触发资源重生成；画像回写由 k1_profile_write 负责。

输入：k1_exercise 批改的结构化结果 grading_result：
  {
      question_id, question_type, knowledge_point, is_correct,
      match_type, score, user_answer, standard_answer,
      analysis, study_suggest, reference_url
  }

对外统一入口函数：
  post_feedback_pipeline(grading_result, question=None, topic_mastery=None, history=None)
"""

from __future__ import annotations

from typing import Any

# ═══════════════════════════════════════════════════════════
# 决策阈值（纯规则，不调 LLM —— 轻量判断用规则）
# ═══════════════════════════════════════════════════════════

ADVANCE_MASTERY = 0.75    # 掌握度 ≥ 此值 → 推进到进阶挑战
LOW_DIM_MASTERY = 0.35    # 掌握度 < 此值 → 直接降维，避免“拔苗助长”
REEXPLAIN_MASTERY = 0.65  # 掌握度 < 此值且非混淆 → 重申讲解
WRONG_RETRY_LIMIT = 2     # 同题连错 ≥ 此值 → 强制降维 + 调低目标层级

# 错因分类（多智能体决策的分支依据）
MISTAKE_CONCEPT_GAP = "concept_gap"   # 概念缺失：答空/完全无关
MISTAKE_CONFUSION = "confusion"       # 概念混淆：误选近似干扰项 / 部分命中
MISTAKE_CARELESS = "careless"         # 粗心：思路正确但描述偏差
MISTAKE_NONE = "none"                 # 未错题


def classify_mistake(
    grading: dict[str, Any],
    question: dict[str, Any] | None = None,
) -> str:
    """按作答行为的可观测信号对错误分类（供多路分支决策使用）。

    Signals:
      - 答案为空 / 极短 / 与标准无重叠 → concept_gap（概念缺失）
      - 误选了干扰项，或 fill 类型部分命中（score 介于 0.4~1）→ confusion（混淆）
      - score 接近 1 仅轻微偏差 → careless（粗心）
      - 其余无法细分 → 默认 concept_gap

    Args:
        grading:  k1_exercise 的结构化批改结果。
        question: 原题元信息（可含 distractors / options，用于判定混淆）。

    Returns:
        str: MISTAKE_* 常量之一。
    """
    if grading.get("is_correct"):
        return MISTAKE_NONE
    user_ans = str(grading.get("user_answer") or "").strip()
    score = float(grading.get("score") or 0.0)

    # 1) 空答 / 答非所问（与任何标准答案无文本重叠）→ 概念缺失
    if not user_ans:
        return MISTAKE_CONCEPT_GAP

    # 2) 误选干扰项 → 概念混淆
    distractors = [str(d).strip() for d in ((question or {}).get("distractors") or [])]
    if distractors and any(d for d in distractors if d and d == user_ans):
        return MISTAKE_CONFUSION

    # 3) 部分命中（相似度匹配、得分中游）→ 边界处的概念混淆
    match_type = grading.get("match_type", "")
    if match_type in ("similarity", "partial") or 0.4 <= score < 1.0:
        return MISTAKE_CONFUSION

    # 4) 得分极接近满分 → 粗心
    if score >= 0.95:
        return MISTAKE_CARELESS
    return MISTAKE_CONCEPT_GAP


def _wrong_times_topic(grading: dict[str, Any], history: list[dict[str, Any]] | None) -> int:
    """统计该题所在知识点 / 题目的历史连续错误次数（简单计数即可）。"""
    qid = grading.get("question_id")
    kp = grading.get("knowledge_point")
    count = 0
    for h in history or []:
        if (h.get("question_id") == qid) or (kp and h.get("knowledge_point") == kp):
            if not h.get("is_correct", True):
                count += 1
    return count


def decide_feedback(
    grading: dict[str, Any],
    question: dict[str, Any] | None = None,
    topic_mastery: float | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """多智能体决策中枢：基于“对错 + 错因 + 掌握度 + 历史”多路分支。

    决策树（纯规则）：
      对（is_correct=True）
        ├─ mastery ≥ ADVANCE_MASTERY → advance_challenge（进阶挑战）
        └─ 否则 → reinforce（正向巩固，不出新资源）
      错（is_correct=False）
        ├─ 同知识点连错 ≥ WRONG_RETRY_LIMIT → low_dim_explain（强制降维）
        ├─ 错因 = confusion            → contrast_explain（对比辨析）
        ├─ mastery < LOW_DIM_MASTERY   → low_dim_explain（降维解释）
        ├─ mastery < REEXPLAIN_MASTERY → re_explain（重申讲解）
        └─ 兜底                        → low_dim_explain

    Args:
        grading:      批改结果（k1_exercise.exercise_pipeline 输出）。
        question:     原题元信息（可含 distractors / options）。
        topic_mastery: 该知识点当前掌握度 0~1（可来自 learner_data / diagnosis_result）。
        history:      该学习者的作答历史列表。

    Returns:
        dict: decision，核心字段：
          {action, mode, level_adjust, hint_scope, regenerate, rationale}
          mode ∈ low_dim_explain | re_explain | contrast_explain |
                 advance_challenge | reinforce
    """
    is_correct = bool(grading.get("is_correct"))
    kp = grading.get("knowledge_point") or "general"
    mastery = float(topic_mastery) if topic_mastery is not None else 0.5
    wrong_times = _wrong_times_topic(grading, history)

    if is_correct:
        if mastery >= ADVANCE_MASTERY:
            return {
                "action": "advance",
                "mode": "advance_challenge",
                "level_adjust": 1,
                "hint_scope": kp,
                "regenerate": True,
                "rationale": f"掌握度 {mastery:.2f} 达标，推进进阶挑战任务",
            }
        return {
            "action": "reinforce",
            "mode": "reinforce",
            "level_adjust": 0,
            "hint_scope": kp,
            "regenerate": False,
            "rationale": f"答对但掌握度 {mastery:.2f} 未达进阶线，先正向巩固",
        }

    # ── 答错分支 ──
    mistake = classify_mistake(grading, question)
    if wrong_times >= WRONG_RETRY_LIMIT:
        return {
            "action": "downgrade",
            "mode": "low_dim_explain",
            "level_adjust": -2,
            "hint_scope": kp,
            "regenerate": True,
            "rationale": f"同知识点连错 {wrong_times} 次，强制降维重讲",
            "mistake_type": mistake,
        }
    if mistake == MISTAKE_CONFUSION:
        return {
            "action": "downgrade",
            "mode": "contrast_explain",
            "level_adjust": -1,
            "hint_scope": kp,
            "regenerate": True,
            "rationale": "概念混淆，安排干扰项对比辨析",
            "mistake_type": mistake,
        }
    if mastery < LOW_DIM_MASTERY:
        return {
            "action": "downgrade",
            "mode": "low_dim_explain",
            "level_adjust": -1,
            "hint_scope": kp,
            "regenerate": True,
            "rationale": f"掌握度 {mastery:.2f} 过低，降维解释 + 分步拆解",
            "mistake_type": mistake,
        }
    if mastery < REEXPLAIN_MASTERY:
        return {
            "action": "downgrade",
            "mode": "re_explain",
            "level_adjust": -1,
            "hint_scope": kp,
            "regenerate": True,
            "rationale": "答错但基础尚可，重申讲解到掌握",
            "mistake_type": mistake,
        }
    return {
        "action": "downgrade",
        "mode": "low_dim_explain",
        "level_adjust": -1,
        "hint_scope": kp,
        "regenerate": True,
        "rationale": "答错兜底，降维解释",
        "mistake_type": mistake,
    }


_FEEDBACK_PROMPTS: dict[str, str] = {
    "low_dim_explain": (
        "针对知识点「{kp}」做降维解释：先用生活化类比讲清概念，再分3步以内"
        "拆解到本题；复用题面 {qtype} 的实际错误作答「{user}」做对照。"
    ),
    "re_explain": (
        "针对知识点「{kp}」用更明确的步骤重申讲解，区分易错点；"
        "结合用户作答「{user}」说明为什么正确答案是「{std}」。"
    ),
    "contrast_explain": (
        "针对知识点「{kp}」做干扰项对比辨析：逐条对比用户所选与正确答案"
        "（用户选了「{user}」，标准为「{std}」），给出判异口诀。"
    ),
    "advance_challenge": (
        "为知识点「{kp}」生成一道进阶挑战题：贴近真实工业现场场景，"
        "难度上调一档，并附解析与可查资料来源。"
    ),
    "reinforce": (
        "为知识点「{kp}」生成一道同难度巩固题（防遗忘间隔练习），附解析。"
    ),
}


def build_retry_hint(
    decision: dict[str, Any],
    grading: dict[str, Any],
    question: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把决策封装为 **_retry_hint** 调度信号（供 Orchestrator / Graph 消费）。

    对齐既有机制：state["_retry_hint"] 由 scheduler/pipeline.py 提取后
    注入下游 Agent 的 prompt 上下文，触发资源重生成 / 画像回写闭环。

    Args:
        decision: decide_feedback 的输出。
        grading:  批改结果。
        question: 原题（用于回传 context）。

    Returns:
        dict: _retry_hint 信号，核心字段：
          {retry, mode, target_topic, level_adjust, regenerate,
           instruction, source_module}
    """
    mode = decision["mode"]
    qtype = grading.get("question_type", "choice")
    fmt_kwargs = {
        "kp": grading.get("knowledge_point") or decision.get("hint_scope") or "general",
        "qtype": "选择题" if qtype == "choice" else "填空题",
        "user": str(grading.get("user_answer") or "未作答"),
        "std": str(grading.get("standard_answer") or "（见解析）"),
    }
    instruction = _FEEDBACK_PROMPTS[mode].format(**fmt_kwargs)
    return {
        "retry": bool(decision.get("regenerate", False)),
        "mode": mode,
        "target_topic": fmt_kwargs["kp"],
        "level_adjust": decision.get("level_adjust", 0),
        "regenerate": decision.get("regenerate", False),
        "instruction": instruction,
        "context": {
            "question_id": grading.get("question_id"),
            "knowledge_point": fmt_kwargs["kp"],
            "question_type": qtype,
            "mistake_type": decision.get("mistake_type"),
            "rationale": decision.get("rationale"),
        },
        "source_module": "k1_post_feedback",
    }


def post_feedback_pipeline(
    grading_result: dict[str, Any],
    question: dict[str, Any] | None = None,
    topic_mastery: float | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """后置动态反馈统一入口（对外调用）。

    Args:
        grading_result: k1_exercise.exercise_pipeline 的结构化批改结果。
        question:       原题元信息（可含 distractors / options，辅助错因分类）。
        topic_mastery:  该知识点当前掌握度 0~1。
        history:        该学习者此前作答记录列表，用于连错惩罚。

    Returns:
        dict:
          decision    —— 多智能体决策结果（含错因与理由）
          retry_hint  —— 供 state["_retry_hint"] 消费的调度信号
          feedback    —— 面向前端的结果文案与动作建议
    """
    decision = decide_feedback(
        grading_result, question=question,
        topic_mastery=topic_mastery, history=history,
    )
    retry_hint = build_retry_hint(decision, grading_result, question)

    is_correct = bool(grading_result.get("is_correct"))
    kp = grading_result.get("knowledge_point") or "本知识点"
    mode = decision["mode"]

    # 面向前端展示的反馈文案（配合 prompt 生成的重生成资源一并返回）
    tip_map = {
        "low_dim_explain": f"「{kp}」答错了，已为你生成降维讲解（贴近日常的类比 + 分步拆解）。",
        "re_explain": f"「{kp}」答错了，已为你重申讲解并标出易错点。",
        "contrast_explain": f"「{kp}」概念被混淆了，已为你生成干扰项对比辨析。",
        "advance_challenge": f"回答正确，掌握达标，已为你推送「{kp}」的进阶挑战。",
        "reinforce": f"回答正确，为你推送一道同难度巩固题，帮助记忆巩固。",
    }
    feedback = {
        "is_correct": is_correct,
        "feedback_type": "right" if is_correct and mode in ("advance_challenge", "reinforce") else "wrong",
        "mode": mode,
        "tip": tip_map.get(mode, "反馈已生成。"),
        "show_explain": True,
        "next_action": "advance_challenge" if mode == "advance_challenge" else "review_knowledge_point",
        "explain_target": kp,
    }
    return {
        "decision": decision,
        "retry_hint": retry_hint,
        "feedback": feedback,
    }


if __name__ == "__main__":
    # ── 单元自测：验证 4 条核心决策分支 + _retry_hint 调度信号 ──
    base_grading = {
        "question_id": "q005",
        "question_type": "fill",
        "knowledge_point": "FANUC点位编程",
        "is_correct": False,
        "match_type": "none",
        "score": 0.0,
        "user_answer": "机器人",
        "standard_answer": "FB 点位指令",
        "analysis": "略",
        "study_suggest": "略",
        "reference_url": "https://kb.example/fb",
    }

    print("== 分支1：答错（低掌握度）→ 降维解释 ==")
    out1 = post_feedback_pipeline(
        dict(base_grading),
        topic_mastery=0.2,
    )
    print("mode:", out1["decision"]["mode"], "| retry:", out1["retry_hint"]["retry"],
          "| level_adjust:", out1["retry_hint"]["level_adjust"])
    assert out1["retry_hint"]["mode"] == "low_dim_explain"
    assert out1["retry_hint"]["regenerate"] is True
    assert out1["retry_hint"]["source_module"] == "k1_post_feedback"

    print("== 分支2：答错（概念混淆 + 误选干扰项）→ 对比辨析 ==")
    q = {"distractors": ["增量指令"]}
    g2 = dict(base_grading); g2["user_answer"] = "增量指令"
    out2 = post_feedback_pipeline(g2, question=q, topic_mastery=0.5)
    print("mistake_type:", out2["decision"].get("mistake_type"),
          "| mode:", out2["decision"]["mode"])
    assert out2["decision"]["mode"] == "contrast_explain"

    print("== 分支3：答对（掌握度达标）→ 进阶挑战 ==")
    g3 = dict(base_grading); g3["is_correct"] = True; g3["score"] = 1.0
    out3 = post_feedback_pipeline(g3, topic_mastery=0.85)
    print("mode:", out3["decision"]["mode"], "| feedback_type:", out3["feedback"]["feedback_type"])
    assert out3["decision"]["mode"] == "advance_challenge"
    assert out3["retry_hint"]["level_adjust"] == 1

    print("== 分支4：连错 2 次 → 强制降维（level_adjust=-2） ==")
    history = [
        {"question_id": "q005", "knowledge_point": "FANUC点位编程", "is_correct": False},
        {"question_id": "q006", "knowledge_point": "FANUC点位编程", "is_correct": False},
    ]
    out4 = post_feedback_pipeline(dict(base_grading), topic_mastery=0.5, history=history)
    print("mode:", out4["decision"]["mode"], "| level_adjust:", out4["retry_hint"]["level_adjust"])
    assert out4["retry_hint"]["level_adjust"] == -2

    print("\n全部断言通过")

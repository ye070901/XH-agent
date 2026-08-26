# -*- coding: utf-8 -*-
"""
K1 习题批改后端：选择题 / 填空题
═══════════════════════════════════════════════════════
对应 PHASE3_PLAN.md §4.5 习题即时作答：
  选择题/填空题 → 提交 → 批改（填空判空做同义/近义语义匹配，
  非纯字符串相等；内置领域同义词典 + 相似度兜底）→ 解析 → 学习建议
  → 可查资料 URL。

返回结构化批改结果（含 knowledge_point / match_type / score），
可直接被 k1_post_feedback 后置动态反馈消费，形成“批改 → 反馈 → 画像回写”闭环。

对外统一入口函数：
  exercise_pipeline(question: dict) -> dict
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Iterable

# ═══════════════════════════════════════════════════════════
# 领域同义词典（用于填空题的同义/近义语义匹配，非纯字符串相等）
# 每一组内词语视为等价表达；用户命中组内任一词即与组内其他成员匹配。
# ═══════════════════════════════════════════════════════════

SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("示教器", "示教盒", "手持盒", "TP", "TEACH PENDANT", "点动盒"),
    ("点位编程", "示教编程", "点位示教", "点位程序"),
    ("JOG模式", "手动模式", "点动模式", "步进模式", "JOG"),
    ("TCP", "工具中心点", "工具坐标系", "工具坐标"),
    ("本体坐标系", "机器人坐标系", "基坐标系", "BASE", "WORLD"),
    ("搬运", "移送", "取放", "上下料", "移载"),
    ("码垛", "堆垛", "堆叠", "码放"),
    ("焊接", "弧焊", "点焊", "MAG焊", "MIG焊", "机器人焊接"),
    ("标定", "校准", "调零", "零点校准"),
    ("报警代码", "报警号", "故障代码", "错误代码", "报警信息"),
    ("轨迹规划", "轨迹插补", "路径规划", "运动轨迹"),
    ("控制器", "控制柜", "系统柜", "R-30iB", "IRC5"),
]

# 忽略的标点与全角字符归一化表
_IGNORE_CHARS = re.compile(r"[\s\-_/（）()【】\[\]，。、；：！？,.!?·:;\"'“”‘’]")


def normalize_text(text: str) -> str:
    """清洗文本用于匹配：统一大写、去空白与标点、全角转半角。

    Args:
        text: 原始文本。

    Returns:
        str: 归一化后的文本（保留数字与英文/中文）。
    """
    if text is None:
        return ""
    s = str(text).strip().upper()
    # 全角转半角（字母数字部分）
    s = "".join(
        chr(ord(c) - 0xFEE0) if "Ａ" <= c <= "Ｚ" or "０" <= c <= "９" else c
        for c in s
    )
    return _IGNORE_CHARS.sub("", s)


def _synonym_id(token: str) -> int | None:
    """返回 token 所属同义词组的下标；不在任何组返回 None。"""
    norm = normalize_text(token)
    for idx, group in enumerate(SYNONYM_GROUPS):
        if any(normalize_text(member) == norm or norm in normalize_text(member) or normalize_text(member) in norm for member in group):
            return idx
    return None


def synonym_match(user_answer: str, standard_answer: str) -> bool:
    """基于领域同义词典的语义匹配（非纯字符串相等）。

    Args:
        user_answer:     用户作答。
        standard_answer: 参考答案。

    Returns:
        bool: 是否为同义/近义等价表达。
    """
    n_user = normalize_text(user_answer)
    n_std = normalize_text(standard_answer)
    if not n_user or not n_std:
        return False
    if n_user == n_std or n_user in n_std or n_std in n_user:
        return True
    uid = _synonym_id(user_answer)
    sid = _synonym_id(standard_answer)
    if uid is not None and uid == sid:
        return True
    return False


def similarity_score(user_answer: str, standard_answer: str) -> float:
    """相似度兜底：difflib.SequenceMatcher，用于同义词典未覆盖时的近似匹配。

    Returns:
        float: 0~1 相似度。
    """
    return difflib.SequenceMatcher(None, normalize_text(user_answer), normalize_text(standard_answer)).ratio()


def match_fill(
    user_answer: str,
    standard_answers: str | Iterable[str],
    threshold: float = 0.72,
) -> dict[str, Any]:
    """填空题批改：精确 → 同义 → 相似度 三层匹配。

    Args:
        user_answer:      用户作答。
        standard_answers: 参考答案（字符串或字符串列表，任一命中即算对）。
        threshold:        相似度兜底阈值（默认 0.72）。

    Returns:
        dict: {is_correct, match_type("exact"|"synonym"|"similarity"|"none"),
               score, matched_standard}
    """
    if isinstance(standard_answers, str):
        standards = [standard_answers]
    else:
        standards = list(standard_answers)

    n_user = normalize_text(user_answer)
    if not n_user or not standards:
        return {"is_correct": False, "match_type": "none", "score": 0.0, "matched_standard": None}

    # 1) 精确 / 包含
    for std in standards:
        n_std = normalize_text(std)
        if n_user == n_std or (n_std and (n_user in n_std or n_std in n_user)):
            return {"is_correct": True, "match_type": "exact", "score": 1.0, "matched_standard": std}

    # 2) 同义 / 近义
    for std in standards:
        if synonym_match(user_answer, std):
            return {"is_correct": True, "match_type": "synonym", "score": 0.95, "matched_standard": std}

    # 3) 相似度兜底
    scores = {std: similarity_score(user_answer, std) for std in standards}
    best_std = max(scores, key=scores.get)
    best_score = scores[best_std]
    if best_score >= threshold:
        return {"is_correct": True, "match_type": "similarity", "score": round(best_score, 3), "matched_standard": best_std}

    return {
        "is_correct": False,
        "match_type": "none",
        "score": round(best_score, 3),
        "matched_standard": best_std,
    }


def match_choice(
    user_answer: str,
    standard_answer: str,
    options: dict[str, str] | None = None,
) -> dict[str, Any]:
    """选择题批改：支持选项字母（忽略大小写）或选项文本（含同义）。

    Args:
        user_answer:      用户作答（如 "A" / "a" 或选项文本）。
        standard_answer:  正确答案（对应字母或文本）。
        options:          可选 {字母: 选项文本}，用于把字母映射到文本做语义匹配。

    Returns:
        dict: {is_correct, match_type, score, matched_standard}
    """
    n_user = normalize_text(user_answer)
    n_std = normalize_text(standard_answer)
    if n_user and n_user == n_std:
        return {"is_correct": True, "match_type": "exact", "score": 1.0, "matched_standard": standard_answer}

    # 字母映射到选项文本再比较
    if options:
        user_text = options.get(user_answer.strip().upper())
        std_text = options.get(n_std.split(maxsplit=1)[0] if len(n_std.split(maxsplit=1)) else n_std)
        if user_text:
            if std_text and normalize_text(user_text) == normalize_text(std_text):
                return {"is_correct": True, "match_type": "option_text", "score": 1.0, "matched_standard": standard_answer}
            if synonym_match(user_text, str(standard_answer) if not std_text else std_text):
                return {"is_correct": True, "match_type": "synonym", "score": 0.95, "matched_standard": standard_answer}

    # 用户给出文本，标准为字母 → 反查选项文本
    if options and not n_user.isdigit():
        std_key = n_std[:1] if len(n_std) == 1 else None
        std_text = options.get(std_key or n_std, standard_answer)
        if synonym_match(user_answer, std_text):
            return {"is_correct": True, "match_type": "synonym", "score": 0.95, "matched_standard": standard_answer}

    return {"is_correct": False, "match_type": "none", "score": 0.0, "matched_standard": standard_answer}


def grade_question(question: dict[str, Any]) -> dict[str, Any]:
    """单题批改：选择题 / 填空题。

    Args:
        question: 题目 dict，通常包含：
          question_id / question_type("choice"|"fill") / knowledge_point /
          user_answer / standard_answer(str|list) / analysis /
          study_suggest / reference_url / options(可选) / threshold(可选)

    Returns:
        dict: 结构化批改结果（供 k1_post_feedback 消费）。
    """
    q_type = question.get("question_type", "fill")
    user_answer = question.get("user_answer", "")
    standard_answer = question.get("standard_answer")
    kp = question.get("knowledge_point") or "general"

    if q_type == "choice":
        grading = match_choice(
            str(user_answer),
            str(standard_answer),
            options=question.get("options"),
        )
    else:
        grading = match_fill(
            str(user_answer),
            standard_answer,
            threshold=float(question.get("threshold", 0.72)),
        )

    return {
        "question_id": question.get("question_id"),
        "question_type": q_type,
        "knowledge_point": kp,
        "is_correct": grading["is_correct"],
        "match_type": grading["match_type"],
        "score": grading["score"],
        "user_answer": str(user_answer),
        "standard_answer": standard_answer if isinstance(standard_answer, str) else list(standard_answer or []),
        "matched_standard": grading["matched_standard"],
        "analysis": question.get("analysis", ""),
        "study_suggest": question.get("study_suggest", ""),
        "reference_url": question.get("reference_url", ""),
        "semantic_detail": {
            "method": grading["match_type"],
            "norm_user": normalize_text(str(user_answer)),
        },
    }


def exercise_pipeline(question: dict[str, Any]) -> dict[str, Any]:
    """习题批改统一入口（对外调用）。

    完整链路：提交 → 批改 → 解析 → 学习建议 → 可查资料 URL。

    Args:
        question: 见 grade_question，含 user_answer 与题目元信息。

    Returns:
        dict: 结构化批改结果（含 grading 层级语义，便于下游反馈分支）。
    """
    result = grade_question(question)
    return {
        "pipeline": "k1_exercise",
        "question_id": result["question_id"],
        "question_type": result["question_type"],
        "knowledge_point": result["knowledge_point"],
        "grading": {
            "is_correct": result["is_correct"],
            "match_type": result["match_type"],
            "score": result["score"],
            "method": result["semantic_detail"]["method"],
        },
        "user_answer": result["user_answer"],
        "standard_answer": result["standard_answer"],
        "analysis": result["analysis"],
        "study_suggest": result["study_suggest"],
        "reference_url": result["reference_url"],
        "semantic_detail": result["semantic_detail"],
    }


def check_answer(user_ans: str, standard_answers: list[str]) -> dict[str, Any]:
    """兼容快捷函数：填空题同义匹配的简化版（旧接口保留）。

    Args:
        user_ans:         用户作答。
        standard_answers: 参考答案列表。

    Returns:
        dict: {is_correct, user_input, std_answer, match_type}
    """
    grading = match_fill(user_ans, standard_answers)
    return {
        "is_correct": grading["is_correct"],
        "user_input": user_ans,
        "std_answer": standard_answers,
        "match_type": grading["match_type"],
    }


if __name__ == "__main__":
    # ── 单元自测：选择题 / 填空题 / 同义匹配 / 相似度兜底 ──
    print("== 选择题：字母与文本均判对 ==")
    q1 = exercise_pipeline({
        "question_id": "c01", "question_type": "choice",
        "knowledge_point": "示教器操作",
        "user_answer": "b", "standard_answer": "B",
        "options": {"A": "在线仿真模式", "B": "JOG手动模式"},
        "analysis": "JOG 是机器人手动示教模式。",
        "study_suggest": "复习示教器操作手册",
        "reference_url": "https://kb.example/jog",
    })
    print("choice 对错:", q1["grading"]["is_correct"], "| match:", q1["grading"]["match_type"])

    print("== 填空题：同义匹配（用户答『示教盒』对照『示教器』） ==")
    q2 = exercise_pipeline({
        "question_id": "f02", "question_type": "fill",
        "knowledge_point": "示教器操作",
        "user_answer": "示教盒", "standard_answer": ["示教器"],
        "analysis": "示教器即 Teach Pendant。",
        "study_suggest": "认识示教器面板",
        "reference_url": "https://kb.example/tp",
    })
    print("fill 同义对错:", q2["grading"]["is_correct"], "| match:", q2["grading"]["match_type"])
    assert q2["grading"]["is_correct"] is True
    assert q2["grading"]["match_type"] == "synonym"

    print("== 填空题：相似度兜底（『点动』 vs 标准『JOG模式』未入组场景） ==")
    q3 = exercise_pipeline({
        "question_id": "f03", "question_type": "fill",
        "knowledge_point": "示教器操作",
        "user_answer": "手动", "standard_answer": ["手动模式"],
        "analysis": "手动模式即 JOG。",
        "study_suggest": "略",
        "reference_url": "https://kb.example",
    })
    print("fill 包含匹配对错:", q3["grading"]["is_correct"], "| match:", q3["grading"]["match_type"])

    print("== 填空题：答错（完全不相似） ==")
    q4 = exercise_pipeline({
        "question_id": "f04", "question_type": "fill",
        "knowledge_point": "TCP标定",
        "user_answer": "法兰盘", "standard_answer": ["TCP", "工具中心点"],
        "analysis": "TCP 定义工具坐标系原点。",
        "study_suggest": "复习 TCP 标定流程",
        "reference_url": "https://kb.example/tcp",
    })
    print("fill 答错:", q4["grading"]["is_correct"], "| score:", q4["grading"]["score"])
    assert q4["grading"]["is_correct"] is False

    # 结果可被 post_feedback 消费的结构断言
    assert set(q2) >= {"grading", "analysis", "study_suggest", "reference_url", "knowledge_point"}
    print("\n全部断言通过")

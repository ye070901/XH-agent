"""
任务：习题即时作答批改 + 画像回写（B组成部分）
题型：选择题 / 填空题；填空题做同义近似匹配，不严格字符串相等
批改结果输出解析、建议、知识库URL；回写learner画像到SQLite
"""
from typing import Dict, Any
import sqlite3


def calc_fill_answer_similarity(user_ans: str, std_ans: str) -> float:
    """
    填空题近似匹配；原型简易版本；正式项目替换embedding相似度
    返回0~1，阈值>=0.7判定正确
    """
    user = user_ans.strip().lower()
    std = std_ans.strip().lower()
    if user == std:
        return 1.0
    # 简易字符重叠，原型Demo用；生产替换为embedding
    set_u = set(user)
    set_s = set(std)
    inter = len(set_u & set_s)
    union = len(set_u | set_s)
    if union == 0:
        return 0.0
    return inter / union


def exam_submit_handler(q_data: Dict[str, Any], user_answer: str):
    """
    :param q_data:题目元数据 {"q_id":"xxx","q_type":["choice","fill"],"std_answer":"","knowledge_id":"k1_001","analysis":"解析文本","ref_doc_url":"http://xxx"}
    :param user_answer: 用户提交答案
    :return exam_result
    """
    q_type = q_data["q_type"]
    std_ans = q_data["std_answer"]
    is_correct = False

    if q_type == "choice":
        is_correct = (user_answer.strip() == std_ans.strip())
    elif q_type == "fill":
        sim = calc_fill_answer_similarity(user_answer, std_ans)
        is_correct = sim >= 0.7

    exam_result = {
        "q_id": q_data["q_id"],
        "is_correct": is_correct,
        "std_answer": std_ans,
        "analysis": q_data["analysis"],
        "suggestion": "建议查阅K1基础文档",
        "ref_doc_url": q_data["ref_doc_url"],
        "knowledge_id": q_data["knowledge_id"]
    }
    return exam_result


def update_learner_profile_db(learner_id: str, knowledge_id: str, is_correct: bool, db_path: str = "./opt4.db"):
    """
    画像回写，规则驱动，**禁止调用LLM**，写入SQLite learner_profiles
    答错：掌握度下调，置信度上调，修正skill_gaps.current_level
    答对：掌握度上调
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now_ts = "datetime('now')"

    # 原型：掌握度0~100；置信度0~100
    if is_correct:
        sql = """
        UPDATE learner_profiles
        SET knowledge_map = json_set(knowledge_map, '$."{kn}"', json_extract(knowledge_map, '$."{kn}"') + 8),
        updated_at = {ts}
        WHERE learner_id = ?;
        """.format(kn=knowledge_id, ts=now_ts)
    else:
        sql = """
        UPDATE learner_profiles
        SET knowledge_map = json_set(knowledge_map, '$."{kn}"', json_extract(knowledge_map, '$."{kn}"') -12),
        skill_gaps = json_set(skill_gaps, '$.current_level', json_extract(skill_gaps, '$.current_level') -1),
        updated_at = {ts}
        WHERE learner_id = ?;
        """.format(kn=knowledge_id, ts=now_ts)
    cur.execute(sql, (learner_id,))
    conn.commit()
    conn.close()


def exam_full_pipeline(q_data: Dict[str, Any], user_answer: str, learner_id: str):
    """习题完整流水线：提交→批改→画像回写"""
    exam_ret = exam_submit_handler(q_data, user_answer)
    update_learner_profile_db(learner_id, exam_ret["knowledge_id"], exam_ret["is_correct"])
    return exam_ret

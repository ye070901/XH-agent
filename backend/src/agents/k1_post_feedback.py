"""
任务：后置动态反馈B（加分项）
答题错误：降维重生成简单解释；答题正确：生成进阶任务
降级模式：不调用重生成，只返回批改结果、建议、文档url
"""
from typing import Dict, Any


def post_feedback_pipeline(exam_result: Dict[str, Any],
                           orchestrator_client,
                           enable_full: bool = True) -> Dict[str, Any]:
    """
    :param exam_result: exam_full_pipeline输出结果
    :param orchestrator_client: Orchestrator调度客户端，提供反馈-重生成入口
    :param enable_full: True完整模式；False降级模式（资源紧张开启）
    """
    is_correct = exam_result["is_correct"]
    if not enable_full:
        # ========= 降级模式（资源紧张直接启用） =========
        return {
            "mode": "degrade",
            "exam_result": exam_result,
            "feedback_content": f"批改完成。{exam_result['suggestion']}，参考文档：{exam_result['ref_doc_url']}",
            "regenerate_content": None
        }

    # =========完整模式，调用Orchestrator重生成入口 =========
    if not is_correct:
        payload = {
            "trigger": "feedback_regen",
            "type": "reduce_difficulty",
            "knowledge_id": exam_result["knowledge_id"],
            "user_error": exam_result["analysis"]
        }
        regen_content = orchestrator_client.call_feedback_regen(payload)
        feedback_text = "你的作答有误，已为你生成简化讲解。"
    else:
        payload = {
            "trigger": "feedback_regen",
            "type": "advance_task",
            "knowledge_id": exam_result["knowledge_id"]
        }
        regen_content = orchestrator_client.call_feedback_regen(payload)
        feedback_text = "作答正确，为你生成进阶练习任务。"

    return {
        "mode": "full",
        "exam_result": exam_result,
        "feedback_content": feedback_text,
        "regenerate_content": regen_content
    }

"""
4.5 K1：前置启发式追问 A（最高优先级）
边界约束：不修改Agent1内部源码，全部通过state["learner_data"] / state["_retry_hint"]传参
判定逻辑：规则优先，规则无法分辨才调用LLM
"""
from typing import Tuple, Dict, Any


def judge_target_too_wide(user_target: str, llm_client) -> Tuple[bool, str]:
    """
    返回 (是否过宽,判定来源) 来源：rule / llm
    """
    hard_vendor = {"FANUC", "发那科", "ABB", "库卡", "KUKA"}
    hard_task = {"示教器", "点位编程", "IO配置", "搬运", "码垛", "RAPID", "KRL"}

    text = user_target.strip()
    char_cnt = len(text)
    has_vendor = any(k in text for k in hard_vendor)
    has_task = any(k in text for k in hard_task)

    # 规则优先判断，不消耗token
    if char_cnt <= 12 or (not has_vendor and not has_task):
        return True, "rule"
    if has_vendor and has_task:
        return False, "rule"

    # 规则模糊，才调用大模型辅助
    prompt = """判断用户学习目标是否宽泛。宽泛定义：没有写明机器人厂商，没有写明具体操作任务。只输出True或者False，禁止输出其他文字。
用户目标：{0}""".format(user_target)
    llm_out = llm_client.chat(prompt).strip()
    result = llm_out == "True"
    return result, "llm"


def generate_heuristic_question(raw_target: str) -> str:
    return "你的学习目标比较宽泛，请补充信息：你希望学习哪个品牌工业机器人？具体做什么操作？（例如：FANUC示教器点位编程）"


def apply_narrowed_target_to_state(narrowed_target: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    用户回答追问后更新state，供给Agent1读取
    禁止修改Agent1内部代码，复用现有state传参通道
    """
    if "learner_data" not in state:
        state["learner_data"] = {}
    if "_retry_hint" not in state:
        state["_retry_hint"] = {}

    state["learner_data"]["user_target"] = narrowed_target
    state["_retry_hint"]["need_rerun"] = True
    return state


def k1_pre_heuristic_pipeline(raw_user_target: str, state: Dict[str, Any], llm_client) -> Dict[str, Any]:
    """对外主入口，上层Orchestrator调用"""
    is_too_wide, judge_source = judge_target_too_wide(raw_user_target, llm_client)

    if not is_too_wide:
        return {
            "need_ask": False,
            "ask_content": None,
            "narrowed_target": raw_user_target,
            "state": state,
            "judge_source": judge_source
        }

    ask_text = generate_heuristic_question(raw_user_target)
    return {
        "need_ask": True,
        "ask_content": ask_text,
        "narrowed_target": None,
        "state": state,
        "judge_source": judge_source
    }

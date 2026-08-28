"""Regression tests for generated quiz usability checks."""

import asyncio

from src.agents.generation_v2 import GenerationAgent


def _question(number: int, stem: str, *, answer: str = "B") -> str:
    return "\n".join(
        [
            f"Question {number}: {stem}",
            "A. Run at full speed",
            "B. Use the approved safe setting",
            "C. Disable the protection",
            "D. Ignore the warning",
            f"Answer: {answer}",
            "Explanation: The approved setting keeps the operation within the "
            "documented safety limits.",
        ]
    )


def test_complete_quiz_requires_clear_stems_and_per_question_keys() -> None:
    content = "\n\n".join(
        _question(
            number,
            f"Before task {number}, which operating setting should the learner "
            f"select to keep the equipment safe?",
        )
        for number in range(1, 6)
    )

    assert GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_rejects_topic_headings_even_when_options_and_keys_exist() -> None:
    content = "\n\n".join(
        _question(number, f"Safety operation topic {number}") for number in range(1, 6)
    )

    assert not GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_accepts_common_chinese_numbering_and_option_punctuation() -> None:
    content = "\n\n".join(
        "\n".join(
            [
                f"{number}. 第{number}次操作前，你应该选择哪项安全设置？",
                "A、使用最高速度",
                "B、使用批准的安全设置",
                "C、关闭保护装置",
                "D、忽略报警",
                "答案：B",
                "解析：批准的安全设置可使操作保持在规定范围内。",
            ]
        )
        for number in range(1, 6)
    )

    assert GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_accepts_concise_stems_and_flexible_answer_labels() -> None:
    content = "\n\n".join(
        "\n".join(
            [
                f"{number}、第{number}次启动前应检查急停状态是否正常？",
                "(A) 使用最高速度",
                "(B) 使用批准的安全设置",
                "(C) 关闭保护装置",
                "(D) 忽略报警",
                "答案是：B",
                "解析 批准的安全设置可使操作保持在规定范围内。",
            ]
        )
        for number in range(1, 6)
    )

    assert GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_rejects_a_topic_label_with_a_question_type_suffix() -> None:
    content = "\n\n".join(_question(number, "报警代码识别（基础选择题）") for number in range(1, 6))

    assert not GenerationAgent._has_complete_quiz_key({"content": content})


def test_unrepaired_item_is_not_kept_in_the_quiz() -> None:
    valid_blocks = [
        _question(
            number,
            f"Before task {number}, which operating setting keeps the equipment "
            f"within safe limits?",
        )
        for number in range(1, 5)
    ]
    invalid_block = _question(
        5,
        "Safety operation topic 5",
    )

    class NoRepairAgent(GenerationAgent):
        async def call_llm_json(self, _prompt: str) -> dict:
            return {"content": ""}

    repaired = asyncio.run(
        NoRepairAgent()._repair_quiz_questions(
            {"title": "Quiz", "content": "\n\n".join([*valid_blocks, invalid_block])},
            "Knowledge source",
        )
    )

    assert invalid_block not in repaired["content"]
    assert GenerationAgent._quiz_contract_failure(repaired) == "题目数量不足：仅生成 4 题"


def test_quiz_accepts_a_mix_of_choice_and_short_answer_questions() -> None:
    choice_questions = [
        _question(
            number,
            f"Before task {number}, which operating setting keeps the equipment "
            f"within safe limits?",
        )
        for number in range(1, 5)
    ]
    short_answer = "\n".join(
        [
            "5. Describe one safety check that must be completed before the equipment "
            "is restarted.",
            "Answer: Confirm the safety circuit and emergency stop state are normal.",
            "Explanation: Restarting is only safe after the required protective devices and "
            "stop conditions have been checked.",
        ]
    )

    assert GenerationAgent._has_complete_quiz_key(
        {"content": "\n\n".join([*choice_questions, short_answer])}
    )


def test_quiz_rejects_missing_explanation() -> None:
    content = "\n\n".join(
        _question(
            number,
            f"Before task {number}, which operating setting should the learner "
            f"select to keep the equipment safe?",
        )
        for number in range(1, 6)
    )
    content = content.replace(
        "Explanation: The approved setting keeps the operation within the "
        "documented safety limits.",
        "",
        1,
    )

    assert not GenerationAgent._has_complete_quiz_key({"content": content})
    assert GenerationAgent._quiz_contract_failure({"content": content}) == "第 1 题缺少解析"


def test_targeted_repair_replaces_only_the_invalid_question() -> None:
    valid_blocks = [
        _question(
            number,
            f"Before task {number}, which operating setting keeps the equipment "
            f"within safe limits?",
        )
        for number in range(1, 6)
    ]
    invalid_block = valid_blocks[2].replace(
        "Explanation: The approved setting keeps the operation within the "
        "documented safety limits.",
        "",
    )
    original_content = "\n\n".join(
        [
            valid_blocks[0],
            valid_blocks[1],
            invalid_block,
            valid_blocks[3],
            valid_blocks[4],
        ]
    )

    class TargetedRepairAgent(GenerationAgent):
        async def call_llm_json(self, _prompt: str) -> dict:
            return {
                "content": _question(
                    3,
                    "During an alarm response, which checked condition must be "
                    "confirmed before resuming operation?",
                )
            }

    repaired = asyncio.run(
        TargetedRepairAgent()._repair_quiz_questions(
            {"title": "Quiz", "content": original_content},
            "Knowledge source",
        )
    )

    assert GenerationAgent._has_complete_quiz_key(repaired)
    for block in (valid_blocks[0], valid_blocks[1], valid_blocks[3], valid_blocks[4]):
        assert block in repaired["content"]
    assert invalid_block not in repaired["content"]


def test_soft_quiz_gate_keeps_a_quiz_that_requires_review() -> None:
    class SoftGateAgent(GenerationAgent):
        async def _generate_one(self, *_args, **_kwargs):
            return {
                "title": "Quiz requiring review",
                "content": "Question 1: Incomplete quiz",
                "_quiz_validation_error": "第 1 题缺少解析",
            }

    result = asyncio.run(
        SoftGateAgent().process(
            {
                "diagnosis_result": {"skill_gaps": []},
                "resource_types": ["quiz"],
                "retrieved_chunks": [{"content": "Knowledge source"}],
            }
        )
    )

    assert len(result["generated_resources"]) == 1
    assert result["generated_resources"][0]["quiz_validation_status"] == "needs_review"
    assert result["generation_errors"][0]["detail"] == "第 1 题缺少解析"

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
            "Explanation: The approved setting keeps the operation within the documented safety limits.",
        ]
    )


def test_complete_quiz_requires_clear_stems_and_per_question_keys() -> None:
    content = "\n\n".join(
        _question(
            number,
            f"Before task {number}, which operating setting should the learner select to keep the equipment safe?",
        )
        for number in range(1, 6)
    )

    assert GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_rejects_topic_headings_even_when_options_and_keys_exist() -> None:
    content = "\n\n".join(
        _question(number, f"Safety operation topic {number}")
        for number in range(1, 6)
    )

    assert not GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_accepts_common_chinese_numbering_and_option_punctuation() -> None:
    content = "\n\n".join(
        "\n".join(
            [
                f"{number}. \u7b2c{number}\u6b21\u64cd\u4f5c\u524d\uff0c\u4f60\u5e94\u8be5\u9009\u62e9\u54ea\u9879\u5b89\u5168\u8bbe\u7f6e\uff1f",
                "A\u3001\u4f7f\u7528\u6700\u9ad8\u901f\u5ea6",
                "B\u3001\u4f7f\u7528\u6279\u51c6\u7684\u5b89\u5168\u8bbe\u7f6e",
                "C\u3001\u5173\u95ed\u4fdd\u62a4\u88c5\u7f6e",
                "D\u3001\u5ffd\u7565\u62a5\u8b66",
                "\u7b54\u6848\uff1aB",
                "\u89e3\u6790\uff1a\u6279\u51c6\u7684\u5b89\u5168\u8bbe\u7f6e\u53ef\u4f7f\u64cd\u4f5c\u4fdd\u6301\u5728\u89c4\u5b9a\u8303\u56f4\u5185\u3002",
            ]
        )
        for number in range(1, 6)
    )

    assert GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_accepts_concise_stems_and_flexible_answer_labels() -> None:
    content = "\n\n".join(
        "\n".join(
            [
                f"{number}\u3001\u7b2c{number}\u6b21\u542f\u52a8\u524d\u5e94\u68c0\u67e5\u6025\u505c\u72b6\u6001\u662f\u5426\u6b63\u5e38\uff1f",
                "(A) \u4f7f\u7528\u6700\u9ad8\u901f\u5ea6",
                "(B) \u4f7f\u7528\u6279\u51c6\u7684\u5b89\u5168\u8bbe\u7f6e",
                "(C) \u5173\u95ed\u4fdd\u62a4\u88c5\u7f6e",
                "(D) \u5ffd\u7565\u62a5\u8b66",
                "\u7b54\u6848\u662f\uff1aB",
                "\u89e3\u6790 \u6279\u51c6\u7684\u5b89\u5168\u8bbe\u7f6e\u53ef\u4f7f\u64cd\u4f5c\u4fdd\u6301\u5728\u89c4\u5b9a\u8303\u56f4\u5185\u3002",
            ]
        )
        for number in range(1, 6)
    )

    assert GenerationAgent._has_complete_quiz_key({"content": content})


def test_quiz_rejects_a_topic_label_with_a_question_type_suffix() -> None:
    content = "\n\n".join(
        _question(number, "\u62a5\u8b66\u4ee3\u7801\u8bc6\u522b\uff08\u57fa\u7840\u9009\u62e9\u9898\uff09")
        for number in range(1, 6)
    )

    assert not GenerationAgent._has_complete_quiz_key({"content": content})


def test_unrepaired_item_is_not_kept_in_the_quiz() -> None:
    valid_blocks = [
        _question(
            number,
            f"Before task {number}, which operating setting keeps the equipment within safe limits?",
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

    repaired = asyncio.run(NoRepairAgent()._repair_quiz_questions(
        {"title": "Quiz", "content": "\n\n".join([*valid_blocks, invalid_block])},
        "Knowledge source",
    ))

    assert invalid_block not in repaired["content"]
    assert GenerationAgent._quiz_contract_failure(repaired) == "\u9898\u76ee\u6570\u91cf\u4e0d\u8db3\uff1a\u4ec5\u751f\u6210 4 \u9898"


def test_quiz_accepts_a_mix_of_choice_and_short_answer_questions() -> None:
    choice_questions = [
        _question(
            number,
            f"Before task {number}, which operating setting keeps the equipment within safe limits?",
        )
        for number in range(1, 5)
    ]
    short_answer = "\n".join([
        "5. Describe one safety check that must be completed before the equipment is restarted.",
        "Answer: Confirm the safety circuit and emergency stop state are normal.",
        "Explanation: Restarting is only safe after the required protective devices and stop conditions have been checked.",
    ])

    assert GenerationAgent._has_complete_quiz_key({"content": "\n\n".join([*choice_questions, short_answer])})


def test_quiz_rejects_missing_explanation() -> None:
    content = "\n\n".join(
        _question(
            number,
            f"Before task {number}, which operating setting should the learner select to keep the equipment safe?",
        )
        for number in range(1, 6)
    )
    content = content.replace(
        "Explanation: The approved setting keeps the operation within the documented safety limits.",
        "",
        1,
    )

    assert not GenerationAgent._has_complete_quiz_key({"content": content})
    assert GenerationAgent._quiz_contract_failure({"content": content}) == "\u7b2c 1 \u9898\u7f3a\u5c11\u89e3\u6790"


def test_targeted_repair_replaces_only_the_invalid_question() -> None:
    valid_blocks = [
        _question(
            number,
            f"Before task {number}, which operating setting keeps the equipment within safe limits?",
        )
        for number in range(1, 6)
    ]
    invalid_block = valid_blocks[2].replace(
        "Explanation: The approved setting keeps the operation within the documented safety limits.",
        "",
    )
    original_content = "\n\n".join([
        valid_blocks[0],
        valid_blocks[1],
        invalid_block,
        valid_blocks[3],
        valid_blocks[4],
    ])

    class TargetedRepairAgent(GenerationAgent):
        async def call_llm_json(self, _prompt: str) -> dict:
            return {
                "content": _question(
                    3,
                    "During an alarm response, which checked condition must be confirmed before resuming operation?",
                )
            }

    repaired = asyncio.run(TargetedRepairAgent()._repair_quiz_questions(
        {"title": "Quiz", "content": original_content},
        "Knowledge source",
    ))

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
                "_quiz_validation_error": "\u7b2c 1 \u9898\u7f3a\u5c11\u89e3\u6790",
            }

    result = asyncio.run(SoftGateAgent().process({
        "diagnosis_result": {"skill_gaps": []},
        "resource_types": ["quiz"],
        "retrieved_chunks": [{"content": "Knowledge source"}],
    }))

    assert len(result["generated_resources"]) == 1
    assert result["generated_resources"][0]["quiz_validation_status"] == "needs_review"
    assert result["generation_errors"][0]["detail"] == "\u7b2c 1 \u9898\u7f3a\u5c11\u89e3\u6790"

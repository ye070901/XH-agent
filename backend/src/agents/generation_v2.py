"""
Agent 2: 领域知识生成 Agent（融合版）
══════════════════════════════════
负责: 角色5 实现

MVP 版本: 直接用 LLM 自身知识生成内容（不依赖外部知识库）
Phase 2 版本: 接入 RAG 知识库，约束生成 + 溯源

输入: state["diagnosis_result"] + state["resource_types"]
输出: state["generated_resources"] (list of GeneratedResource)

融合改进点:
  - Untitled-1.py: 资源数量上限、结构化内容模板、更清晰的 _fmt_gaps
  - 原 generation.py: prompt 代码块转义、项目代码风格
  - 新增: 循环容错（部分成功）、float() 类型保护、OPTIONAL_STATE_KEYS 补全
"""

import json
import re
import uuid

from .base import BaseAgent

# (难度, 学习风格) → 画像标签 的主映射（与 data/evaluation/learner_profiles.json 的 7 画像对齐）
_PROFILE_TAG_BY_DIFF_STYLE: dict[tuple[str, str], str] = {
    ("beginner", "visual"): "zero_basis",  # D 纯零基础·行业外转行
    ("beginner", "theory_first"): "heard_only",  # E 有背景·仅听过机器人
    ("intermediate", "practice_first"): "hands_on_operator",  # G 实操型·会操作不懂原理
    ("advanced", "practice_first"): "skilled_engineer",  # I 熟练工程师·日常使用
    ("advanced", "project_based"): "authority_expert",  # J 权威型·技术大能
}


def derive_profile_tag(learner_data: dict, difficulty: str, style: str) -> str:
    """按 (难度, 风格) + 背景纯规则推导画像标签（7 画像之一，无 LLM 脑补）。

    intermediate + theory_first 需细分：
      - F 理论型（0 工作年限 / 实习生）→ theory_student
      - H 均衡初级（有工作年限）        → balanced_junior
    其余 (难度, 风格) 组合若未命中 7 画像，返回中性兜底 "custom"。

    供生成 / 修正 Agent 共享，避免画像规则散落多处（CLAUDE.md §6.4 多文件归并）。
    """
    tag = _PROFILE_TAG_BY_DIFF_STYLE.get((difficulty, style))
    if tag:
        return tag
    if (difficulty, style) == ("intermediate", "theory_first"):
        try:
            work_years = float(learner_data.get("work_years") or 0)
        except (ValueError, TypeError):
            work_years = 0.0
        positions = " ".join(learner_data.get("positions") or [])
        if work_years <= 0 or "实习" in positions:
            return "theory_student"
        return "balanced_junior"
    return "custom"


SYSTEM_PROMPT = """你是一个垂直领域的知识专家和教育内容创作者。你的任务是：
1. 根据学习者的知识盲区（skill_gaps）和推荐难度，用你的专业知识生成个性化学习资源
2. 生成的内容必须准确、实用，代码示例可以直接运行
3. 个性化体现在：解释深度、示例复杂度、学习路径建议

生成资源类型：
- lecture（定制讲义）：系统性理论讲解，含代码示例
- guide（实操指南）：分步操作手册，含真实命令行和完整代码
- quiz（分阶测试题）：选择题/填空题/实操题，分基础/进阶/挑战三级

## 难度矩阵（唯一有效标准，禁止使用其他旧标准）
- beginner：零基础入门。多用生活类比与比喻，术语首次出现必须给白话解释，每行代码加注释。
- intermediate：有基础进阶。专业术语可直接使用，仅对关键步骤加注释，引入进阶概念。
- advanced：熟练/专家级。直接用行业术语，精简解释，聚焦架构权衡与高质量代码。

## 学习风格（4 种，唯一有效标准）
- theory_first：先讲清原理（为什么），再给代码/操作。
- practice_first：先给可执行步骤/代码，再解释原理。
- visual：偏好图片、示意图、动画演示，少大段文字，多用步骤拆解，适合零基础入门。
- project_based：以真实案例、项目任务驱动讲解，结合实际场景做练习，适合有基础的学习者。

重要规则：
- 学情盲区标注了 critical 的知识点 → 这是本次生成必须覆盖的核心内容
- 严格遵循系统传入的结构化画像参数（difficulty / learning_style / profile_tag）
- **禁止自行脑补或改写难度与学习风格**：输出 difficulty_level 必须与传入 difficulty 完全一致，
  表达方式必须与传入 learning_style 一致，不得混用其他风格

输出必须为严格的 JSON 格式。

【你仅处理工业机器人故障诊断相关任务，领域包含FANUC、KUKA、ABB工业机器人、示教器、机器人故障代码；拒绝回答和机器人故障无关的问题。】"""


class GenerationAgent(BaseAgent):
    """领域知识生成 Agent — 角色5 在此实现

    根据学情诊断结果（diagnosis_result），为每种请求的资源类型
    （lecture / guide / quiz）生成一份个性化学习资源。

    资源数量上限为 3，防止单次请求过度消耗 token。
    单个资源生成失败不影响其他资源（部分成功）。
    """

    REQUIRED_STATE_KEYS = {"diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "learner_data",
        "resource_types",
        "retrieved_chunks",  # Phase 2 RAG 知识库检索结果，MVP 阶段可选
        "task_id",
        "agent_log",
        "status",
    }

    # 资源数量上限，防止 token 过度消耗
    MAX_RESOURCES = 3

    def __init__(self):
        super().__init__(
            name="知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    async def process(self, state: dict) -> dict:
        """生成个性化学习资源。

        对每种请求的资源类型分别调用 LLM 生成一份资源。
        单个资源生成失败时记录错误但不阻断其他资源的生成（部分成功）。
        """
        diagnosis = state.get("diagnosis_result", {})
        learner_data = state.get("learner_data", {})
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])
        retrieved_chunks = state.get("retrieved_chunks", [])

        # ── 空 KB 生成关闭：无有效知识库 chunk 时禁止凭空生成（杜绝兜底路径幻觉）──
        valid_chunks = [
            c for c in retrieved_chunks if isinstance(c, dict) and str(c.get("content", "")).strip()
        ]
        if not valid_chunks:
            self.log("⚠️ 无有效知识库素材，禁止凭空生成，返回空资源集合")
            return {
                "generated_resources": [],
                "generation_errors": [
                    {"resource_type": "ALL", "error": "no_knowledge_base_chunks"}
                ],
            }

        # 安全上限：防止请求过多类型导致 token 爆炸
        resource_types = resource_types[: self.MAX_RESOURCES]

        resources = []
        errors = []
        learner_id = state.get("learner_id", "")
        # 本次生成覆盖的盲区知识点（与 schemas.GeneratedResource.target_skill_gaps 对齐）
        target_skill_gaps = [
            g.get("topic", "") for g in diagnosis.get("skill_gaps", []) if g.get("topic")
        ]
        for rtype in resource_types:
            try:
                result = await self._generate_one(diagnosis, rtype, retrieved_chunks, learner_data)
                # 解析失败（_parse_error）或空内容同样按失败处理，不当作资源
                if not result or result.get("_parse_error"):
                    self.log(f"⚠️ {rtype} 类型资源生成解析失败，跳过")
                    errors.append({"resource_type": rtype, "error": "json_parse_failed"})
                    continue
                # 与 schemas.GeneratedResource 对齐：resource_id / learner_id /
                # resource_type 由本层补全，target_skill_gaps 从诊断结果推导
                quiz_validation_error = result.pop("_quiz_validation_error", None)
                if quiz_validation_error:
                    self.log(
                        "Quiz generation requires review before it can be automatically scored."
                    )
                    errors.append(
                        {
                            "resource_type": rtype,
                            "error": "invalid_quiz_contract",
                            "detail": quiz_validation_error,
                        }
                    )
                    result["quiz_validation_status"] = "needs_review"
                    result["quiz_validation_error"] = quiz_validation_error
                result["resource_type"] = rtype
                result["resource_id"] = str(uuid.uuid4())
                result["learner_id"] = learner_id
                result.setdefault("target_skill_gaps", target_skill_gaps)
                resources.append(result)
            except Exception as e:
                # 单个资源生成失败不阻断其他资源
                self.log(f"⚠️ {rtype} 类型资源生成失败: {e}")
                errors.append({"resource_type": rtype, "error": str(e)})

        self.log(
            f"生成完成: {len(resources)}/{len(resource_types)} 个资源"
            + (f"，{len(errors)} 个失败" if errors else "")
        )
        return {
            "generated_resources": resources,
            **({"generation_errors": errors} if errors else {}),
        }

    async def _generate_one(
        self,
        diagnosis: dict,
        rtype: str,
        retrieved_chunks: list | None = None,
        learner_data: dict | None = None,
    ) -> dict:
        """为单一资源类型生成内容。

        Args:
            diagnosis:        诊断结果 dict，含 skill_gaps / recommended_difficulty
                              / learning_style / summary / profile_tag(可选)
            rtype:            资源类型字符串（lecture / guide / quiz）
            retrieved_chunks: RAG 知识库检索结果列表
            learner_data:     学习者原始画像（用于纯规则推导 profile_tag，可选）

        Returns:
            LLM 返回的 dict；LLM 解析失败时返回 {}（由调用方过滤）。
        """
        gaps = diagnosis.get("skill_gaps", [])
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "unknown")
        learning_goal = diagnosis.get("summary", "")
        # 画像标签：优先取诊断显式字段，否则按 (难度, 风格, 背景) 纯规则推导
        profile_tag = diagnosis.get("profile_tag") or derive_profile_tag(
            learner_data or {}, difficulty, learning_style
        )

        # ── 结构化画像参数（权威，模型不可改写）──
        profile_params = {
            "difficulty": difficulty,
            "learning_style": learning_style,
            "profile_tag": profile_tag,
        }

        # ── 构建知识库上下文（RAG 约束生成）──
        kb_context = self._fmt_knowledge_base(retrieved_chunks or [])

        prompt = f"""## 结构化画像参数（权威，禁止改写）
{json.dumps(profile_params, ensure_ascii=False)}

## 学习者画像
- 学习目标总结：{learning_goal}
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}

{kb_context}

## 生成任务
请**严格基于上述知识库参考资料**，生成一份 {rtype} 类型的个性化学习资源。

## 输出 JSON
{{
    "title": "资源标题（要具体、有吸引力）",
    "content": "Markdown 格式的完整内容（含代码示例和命令行时用 `````` 标注语言类型）",
    "citations": [
        {{"ref_index": 1, "original_text": "引用的原文片段", "usage": "在内容中的用途说明"}}
    ],
    "difficulty_level": "{difficulty}",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["学完你能掌握什么1", "学完你能掌握什么2", "学完你能掌握什么3"]
}}

## 硬性要求
1. 内容必须准确——这是教育场景，教错了比不教更糟
2. **内容必须基于上方知识库参考资料**，不得编造知识库中没有的技术细节
3. 代码示例完整可运行，命令行标注操作系统（Windows/Linux/Mac）
4. **难度锁定**：difficulty_level 必须严格等于结构化画像参数中的 difficulty（{difficulty}），
   禁止自行调整难度档位
5. **风格锁定**：内容表达方式必须与结构化画像参数中的 learning_style（{learning_style}）
   一致，禁止混用其他风格或自行脑补新风格
6. 三种资源固定内容结构：
   - lecture: 引言 → 3~4小节（概念+可运行代码）→ 总结
   - guide: 概述 → 前置准备 → 分步操作（命令+代码+预期输出）→ 常见问题
   - quiz: 基础选择题2道（含选项/标准答案/解析）→ 进阶题1道 → 挑战实操题1道
7. 优先覆盖 critical 和 high 优先级的知识盲区
8. citations 中至少引用 2 条知识库原文片段"""

        if rtype == "quiz":
            prompt += """

## STRICT QUIZ CONTRACT
Create at least 5 distinct questions. Each question must have a unique, clear
stem and must be numbered in order as `\u7b2c1\u9898\uff1a` through `\u7b2c5\u9898\uff1a`.
The five-question minimum overrides any older resource-template instruction
that mentions a smaller quiz. Do not return fewer than five questions.
Every stem must be a self-contained question: state the operating condition or
task and ask the learner to make a decision. A section title or topic label is
not a question and must never be used as a question stem.
Write all learner-facing content in Simplified Chinese. Keep English only for
unavoidable product names, alarm codes, or technical abbreviations.
Use a mix of multiple-choice questions and one or two short-answer questions.
For a multiple-choice question, include exactly four options labelled A-D,
then include `\u7b54\u6848\uff1a<letter>` and `\u89e3\u6790\uff1a<reason>` immediately after
that question. A short-answer question has no A-D options, but must still have
one `\u7b54\u6848\uff1a<expected answer>` and one `\u89e3\u6790\uff1a<reason>` line.
Never place more than one A-D option group under one question heading. Include a
mix of recall, scenario, and application questions that is
relevant to the learner profile and the retrieved knowledge.
"""

        result = await self.call_llm_json(prompt)
        failure = self._quiz_contract_failure(result)
        if rtype != "quiz" or failure is None:
            return result

        # A quiz without an answer key cannot be submitted, reviewed, or exported
        # as a self-study resource. Ask once more before it reaches the UI.
        # Keep valid question blocks intact. Only malformed questions are
        # regenerated, so a single bad item does not invalidate the whole quiz.
        repaired = await self._repair_quiz_questions(result, kb_context)
        failure = self._quiz_contract_failure(repaired)
        if failure is None:
            return repaired
        if isinstance(repaired, dict):
            return {**repaired, "_quiz_validation_error": failure}
        return {
            "title": "Quiz requiring review",
            "content": str(repaired or ""),
            "_quiz_validation_error": failure or "\u9898\u76ee\u7ed3\u6784\u65e0\u6cd5\u89e3\u6790",
        }

    @staticmethod
    def _quiz_question_blocks(content: str) -> list[str]:
        """Split quiz content into independently repairable question blocks."""
        pattern = re.compile(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898|\d+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?\s*(?P<stem>.+)$"
        )
        matches = list(pattern.finditer(content))
        return [
            content[
                match.start() : (
                    matches[index + 1].start() if index + 1 < len(matches) else len(content)
                )
            ].strip()
            for index, match in enumerate(matches)
        ]

    @staticmethod
    def _quiz_block_stem(block: str) -> str:
        match = re.search(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898|\d+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?\s*(?P<stem>.+)$",
            block,
        )
        return match.group("stem").strip() if match else ""

    @staticmethod
    def _is_clear_quiz_stem(stem: str) -> bool:
        """Require an independently answerable question instead of a topic label."""
        normalized_stem = re.sub(r"\s+", "", stem).lower()
        if len(normalized_stem) < 4:
            return False

        heading_pattern = re.compile(
            r"(?i)^(?:(?:safety\s+operation\s+topic|topic|overview|introduction|basics|practice)\s*\d*|"
            r"(?:\u5b89\u5168\u64cd\u4f5c|\u6545\u969c\u8bca\u65ad|\u57fa\u7840\u539f\u7406|\u5750\u6807\u7cfb|\u64cd\u4f5c\u6d41\u7a0b))$"
        )
        question_type_label = re.compile(
            r"^[^?\uff1f]{1,80}[\(\uff08](?:\u57fa\u7840|\u8fdb\u9636|\u573a\u666f|\u5b9e\u64cd|\u6311\u6218)?"
            r"(?:\u9009\u62e9\u9898|\u7b80\u7b54\u9898|\u586b\u7a7a\u9898|\u5e94\u7528\u9898)?[\)\uff09]$"
        )
        task_signal = re.compile(
            r"[?\uff1f]|\b(?:which|what|how|why|when|where|should|can|does|describe|select|identify|choose|explain|state|list)\b|"
            r"(?:\u4ee5\u4e0b|\u54ea(?:\u4e2a|\u9879|\u79cd)|\u4ec0\u4e48|\u5982\u4f55|\u4e3a\u4ec0\u4e48|\u662f\u5426|\u8bf7(?:\u9009\u62e9|\u5224\u65ad|\u8bf4\u660e|\u5199\u51fa|\u5217\u51fa|\u56de\u7b54)|\u5e94(?:\u8be5|\u5f53)|\u6b63\u786e|\u9519\u8bef|\u6b65\u9aa4|\u539f\u56e0|\u64cd\u4f5c|\u5904\u7406|\u5224\u65ad)",
            re.IGNORECASE,
        )
        return (
            not heading_pattern.fullmatch(stem)
            and not question_type_label.fullmatch(stem)
            and bool(task_signal.search(stem))
        )

    @staticmethod
    def _quiz_block_failure(block: str) -> str | None:
        """Return the automatic-scoring failure for one question block."""
        stem = GenerationAgent._quiz_block_stem(block)
        if not stem:
            return "missing a numbered question stem"

        if not GenerationAgent._is_clear_quiz_stem(stem):
            return "the question stem is not a clear learner task"

        option_pattern = re.compile(
            r"(?im)^\s*(?:[-*]\s*)?(?:[\(\uFF08]\s*)?([A-D])\s*(?:[\)\uFF09]\s*|[.\uFF0E\u3001:\uFF1A\]]\s*)\S.+$"
        )
        answer_pattern = re.compile(
            r"(?im)^\s*(?:answer|\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u6b63\u786e\u7b54\u6848|\u7b54\u6848(?!\u89e3\u6790))\s*(?:is|\u662f|\u4e3a|\u9009)?\s*[:\uFF1A=]?\s*(\S(?:.*\S)?)\s*$"
        )
        explanation_pattern = re.compile(
            r"(?im)^\s*(?:explanation|\u7b54\u6848\u89e3\u6790|\u89e3\u6790)\s*[:\uFF1A=]?\s*(.+\S)\s*$"
        )
        answers = answer_pattern.findall(block)
        explanations = explanation_pattern.findall(block)
        if len(answers) != 1:
            return "the question must contain exactly one answer line"
        if len(explanations) != 1:
            return "the question must contain exactly one explanation line"

        option_ids = option_pattern.findall(block)
        if option_ids:
            if option_ids != ["A", "B", "C", "D"]:
                return "multiple-choice options must be exactly A through D"
            if answers[0].strip().upper() not in {"A", "B", "C", "D"}:
                return "the answer must match one of the A-D options"
        return None

    async def _repair_quiz_question(
        self,
        question_number: int,
        source_block: str,
        reason: str,
        kb_context: str,
        retained_stems: list[str],
    ) -> str | None:
        """Regenerate one invalid question while preserving all valid questions."""
        prompt = f"""Return JSON with a single `content` field containing one replacement
quiz question only. All learner-facing text must be Simplified Chinese, except
for unavoidable product names, alarm codes, or technical abbreviations.
The stem must state a concrete condition or task and clearly ask what the
learner should decide or do. Never use a topic label such as
`\u62a5\u8b66\u4ee3\u7801\u8bc6\u522b\uff08\u57fa\u7840\u9009\u62e9\u9898\uff09` as a stem.
Preserve the original question type when possible. If the original used A-D
options, use this multiple-choice format:

\u7b2c {question_number} \u9898\uff1a<complete standalone question>
A. <option>
B. <option>
C. <option>
D. <option>
\u7b54\u6848\uff1a<A, B, C, or D>
\u89e3\u6790\uff1a<why the answer is correct>

If the original is a short-answer question, use this format instead and do not
include A-D options:

\u7b2c {question_number} \u9898\uff1a<complete standalone question>
\u7b54\u6848\uff1a<expected short answer>
\u89e3\u6790\uff1a<why the answer is correct>

Ground the replacement in this knowledge context. Do not repeat any retained
question stems: {retained_stems}

Original invalid question:
{source_block or "<missing question>"}

Automatic validation failure: {reason}

Knowledge context:
{kb_context[:6000]}
"""
        repaired = await self.call_llm_json(prompt)
        if not isinstance(repaired, dict):
            return None
        for candidate in self._quiz_question_blocks(str(repaired.get("content", ""))):
            if self._quiz_block_failure(candidate) is None:
                return candidate
        return None

    async def _repair_quiz_questions(self, result: dict, kb_context: str) -> dict:
        """Repair failed quiz items independently without rewriting valid ones."""
        candidate = dict(result) if isinstance(result, dict) else {"content": ""}
        blocks = self._quiz_question_blocks(str(candidate.get("content", "")))

        # Bound retries when the model is unavailable, but retry every failed
        # item before the explicit review fallback is returned to the UI.
        for _ in range(5):
            target_count = max(5, len(blocks))
            repaired_blocks: list[str] = []
            retained_stems: list[str] = []
            retained_keys: set[str] = set()

            for index in range(target_count):
                source_block = blocks[index] if index < len(blocks) else ""
                stem = self._quiz_block_stem(source_block)
                stem_key = re.sub(r"\s+", "", stem).lower()
                failure = self._quiz_block_failure(source_block)
                if failure is None and stem_key in retained_keys:
                    failure = "the question stem duplicates a retained question"

                if failure is None:
                    repaired_blocks.append(source_block)
                    retained_stems.append(stem)
                    retained_keys.add(stem_key)
                    continue

                replacement = await self._repair_quiz_question(
                    index + 1,
                    source_block,
                    failure or "missing question",
                    kb_context,
                    retained_stems,
                )
                replacement_stem = self._quiz_block_stem(replacement or "")
                replacement_key = re.sub(r"\s+", "", replacement_stem).lower()
                if replacement and replacement_key and replacement_key not in retained_keys:
                    repaired_blocks.append(replacement)
                    retained_stems.append(replacement_stem)
                    retained_keys.add(replacement_key)
                # Do not put a failed item back into the quiz. The next pass
                # will create a fresh replacement while retaining valid items.

            candidate["content"] = "\n\n".join(repaired_blocks)
            if self._quiz_contract_failure(candidate) is None:
                return candidate
            blocks = self._quiz_question_blocks(str(candidate.get("content", "")))

        return candidate

    @staticmethod
    def _has_legacy_quiz_key(result: dict | None) -> bool:
        """Return whether every recognizable quiz question includes its key."""
        if not isinstance(result, dict):
            return False
        content = str(result.get("content", ""))
        question_count = len(
            re.findall(
                r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*题)",
                content,
            )
        )
        answer_count = len(
            re.findall(r"(?im)^\s*(?:answer|标准答案|参考答案|正确答案|答案)\s*[:：]", content)
        )
        explanation_count = len(
            re.findall(r"(?im)^\s*(?:explanation|答案解析|解析)\s*[:：]", content)
        )
        return (
            question_count >= 5
            and answer_count >= question_count
            and explanation_count >= question_count
        )

    @staticmethod
    def _has_complete_quiz_key(result: dict | None) -> bool:
        """Require each generated quiz block to be a usable, self-contained item."""
        return GenerationAgent._quiz_contract_failure(result) is None

    @staticmethod
    def _quiz_contract_failure(result: dict | None) -> str | None:
        """Return a user-facing reason when a quiz cannot be safely scored."""
        if not isinstance(result, dict):
            return "生成结果不是有效的结构化内容"

        content = str(result.get("content", ""))
        if not content.strip():
            return "\u9898\u76ee\u5185\u5bb9\u4e3a\u7a7a"
        question_pattern = re.compile(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898|\d+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?\s*(?P<stem>.+)$"
        )
        matches = list(question_pattern.finditer(content))
        if len(matches) < 5:
            return f"题目数量不足：仅生成 {len(matches)} 题"

        option_pattern = re.compile(
            r"(?im)^\s*(?:[-*]\s*)?(?:[\(\uFF08]\s*)?([A-D])\s*(?:[\)\uFF09]\s*|[.\uFF0E\u3001:\uFF1A\]]\s*)\S.+$"
        )
        answer_pattern = re.compile(
            r"(?im)^\s*(?:answer|\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u6b63\u786e\u7b54\u6848|\u7b54\u6848(?!\u89e3\u6790))\s*(?:is|\u662f|\u4e3a|\u9009)?\s*[:\uFF1A=]?\s*(\S(?:.*\S)?)\s*$"
        )
        explanation_pattern = re.compile(
            r"(?im)^\s*(?:explanation|\u7b54\u6848\u89e3\u6790|\u89e3\u6790)\s*[:\uFF1A=]?\s*(.+\S)\s*$"
        )

        seen_stems: set[str] = set()
        for index, match in enumerate(matches):
            question_number = index + 1
            block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[match.start() : block_end]
            stem = match.group("stem").strip()
            normalized_stem = re.sub(r"\s+", "", stem).lower()
            if not GenerationAgent._is_clear_quiz_stem(stem):
                return f"第 {question_number} 题题干更像标题，无法确认作答任务"
            if normalized_stem in seen_stems:
                return f"\u7b2c {question_number} \u9898\u4e0e\u524d\u9762\u9898\u76ee\u91cd\u590d"
            seen_stems.add(normalized_stem)

            answers = answer_pattern.findall(block)
            explanations = explanation_pattern.findall(block)
            if not answers:
                return f"\u7b2c {question_number} \u9898\u7f3a\u5c11\u6807\u51c6\u7b54\u6848"
            if len(answers) > 1:
                return f"第 {question_number} 题包含多个标准答案"
            if not explanations:
                return f"\u7b2c {question_number} \u9898\u7f3a\u5c11\u89e3\u6790"
            if len(explanations) > 1:
                return f"\u7b2c {question_number} \u9898\u5305\u542b\u591a\u4e2a\u89e3\u6790"

            option_ids = option_pattern.findall(block)
            if option_ids:
                if option_ids != ["A", "B", "C", "D"]:
                    return f"第 {question_number} 题的选项必须完整标为 A-D"
                if answers[0].strip().upper() not in {"A", "B", "C", "D"}:
                    return f"第 {question_number} 题的标准答案未匹配选项"

        return None

    def _fmt_gaps(self, gaps: list) -> str:
        """格式化知识盲区列表为可读文本，最多展示前 5 条。

        对数值字段做 float() 保护，防止 LLM 返回字符串类型
        导致 .1f 格式化报 TypeError。
        """
        if not gaps:
            return "学习者未提供具体知识盲区，请根据学习目标生成通用的入门内容"

        lines = []
        for g in gaps[:5]:
            priority = g.get("priority", "?")
            topic = g.get("topic", "未知")
            reason = g.get("reason", "")

            # float() 类型保护：LLM JSON 中的数值可能是 int/float/str
            try:
                curr_lv = float(g.get("current_level", 0.0))
            except (ValueError, TypeError):
                curr_lv = 0.0
            try:
                target_lv = float(g.get("target_level", 1.0))
            except (ValueError, TypeError):
                target_lv = 1.0

            lines.append(
                f"- [{priority}] {topic} (当前 {curr_lv:.1f} → 目标 {target_lv:.1f}): {reason}"
            )

        return "\n".join(lines)

    @staticmethod
    def _fmt_knowledge_base(chunks: list) -> str:
        """将 RAG 检索到的知识库 chunks 格式化为 LLM prompt 中的参考资料。

        取前 6 条最相关的 chunk，去重（按 doc_title），
        每条截取前 500 字符防止 prompt 过长。
        """
        if not chunks:
            return "## 知识库参考资料\n（无可用知识库素材——禁止凭空生成内容）"

        seen_titles: set[str] = set()
        unique_chunks: list[dict] = []
        for c in chunks:
            title = c.get("doc_title", "")
            if title not in seen_titles:
                seen_titles.add(title)
                unique_chunks.append(c)
            if len(unique_chunks) >= 6:
                break

        parts = ["## 知识库参考资料（以下是系统检索到的权威文档，请严格基于这些资料生成内容）"]
        for i, c in enumerate(unique_chunks, 1):
            title = c.get("doc_title", "未知文档")
            content = c.get("content", "")
            # 截取关键部分，防止 prompt 过长
            excerpt = content[:500] + ("…" if len(content) > 500 else "")
            parts.append(f"\n### 资料 {i}：{title}\n{excerpt}")

        return "\n".join(parts)

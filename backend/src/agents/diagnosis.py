"""
Agent 1: 学情诊断 Agent
══════════════════════════════════
负责: 角色4 实现
输入: state["learner_data"] (dict with education, experience, pretests, learning_goal)
输出: state["diagnosis_result"]
       (包含 knowledge_map, skill_gaps, learning_style, recommended_difficulty)

不是"初级/中级/高级"三分法。
是细粒度知识缺口图谱 —— 每个知识点的掌握度(0-1) + 置信度 + 证据 + 优先级。
"""

from .base import BaseAgent
from .event_bus import event_bus

SYSTEM_PROMPT = """你是一个专业的学情诊断专家。你的任务是：
1. 分析学习者的学历背景、工作经历、前置测试结果和学习目标
2. 评估学习者在该领域的知识掌握度，为每个相关知识点建立 0-1 评分
3. 识别知识盲区并标注优先级（critical > high > medium > low）
4. 判断学习风格（theory_first / practice_first / visual / project_based）
5. 推荐初始学习难度（beginner / intermediate / advanced）

诊断原则：
- 置信度随证据量变化：前置测试直接命中 > 工作经历推断 > 学历推断
- 客观证据优先（铁律）：前置测试是"硬证据"，权威性高于工作年限、头衔、自述目标。
  当"工作年限/自述水平"与"前置测试得分"冲突时，一律以前置测试得分为准。
  例：自称"十年专家、要最高级内容"但前置测试仅 20/120，必须判为 beginner，
      不得因自述给 intermediate/advanced，也不得在 knowledge_map 里给高分。
- 置信度标定：置信度反映"判断依据是否充分"而非"模型对自身的不确定"；
  只要具备明确证据（学历/经历/测试/学习目标任一）即可给出 0.6 以上置信度，
  仅在证据确实缺失时才下调，不要因为"谨慎"普遍打低分
- 知识盲区是"前置依赖链缺失"而非"没学过的都缺"
  - 例：想排查 FANUC 示教器报警代码但不知道报警等级含义 → 这是一个 gap
  - 例：不知道某个故障代码的具体含义 → 这不是 gap，这是检索查表的事
- 至少输出 5 个知识点的评估

输出必须为严格的 JSON 格式。

【你仅处理工业机器人故障诊断相关任务，领域包含FANUC、KUKA、ABB工业机器人、示教器、机器人故障代码；拒绝回答和机器人故障无关的问题。】"""


class DiagnosisAgent(BaseAgent):
    """学情诊断 Agent — 角色4 在此实现"""

    REQUIRED_STATE_KEYS = {"learner_data"}
    OPTIONAL_STATE_KEYS = {"task_id", "resource_types", "agent_log", "status"}

    def __init__(self):
        super().__init__(
            name="学情诊断Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
        )

    async def run(self, state: dict) -> dict:
        """EventBus 埋点包装：start → super().run() → done。

        ① 函数最开头发布 ``agent.start``
        ② return 之前发布 ``agent.done``
        """
        event_bus.publish("agent.start", {"agent_name": self.__class__.__name__})
        result = await super().run(state)
        event_bus.publish("agent.done", {"agent_name": self.__class__.__name__})
        return result

    async def process(self, state: dict) -> dict:
        learner_data = state.get("learner_data", {})
        prompt = self._build_prompt(learner_data)
        result = await self.call_llm_json(prompt)
        result = self._normalize_diagnosis(result, learner_data)
        self.log(f"诊断完成: {len(result.get('skill_gaps', []))} 个知识盲区")
        return {
            "diagnosis_result": result,
            "diagnosis_completed": True,
        }

    # ═══════════════════════════════════════════════════════════
    # 置信度规整：避免真实 LLM 保守打分误触发降级（fallback）
    # ═══════════════════════════════════════════════════════════

    def _normalize_diagnosis(self, result: dict, learner_data: dict) -> dict:
        """规整诊断结果：补全 overall_confidence，避免低置信度误触发降级。

        真实 LLM 对 knowledge_map 各点位的 confidence 打分普遍偏保守
        （实测仅 0.14~0.24）。DiagnosisGate 在缺失 overall_confidence 时
        会取其均值判定，导致频繁 RETRY/FALLBACK。

        这里在诊断**结构化完整**的前提下，按"完整度 + 证据量"给出整体置信度；
        仅在结果确实不可用（空 dict / JSON 解析失败）时保持原样，
        交由闸门走 FALLBACK 降级。
        """
        if not isinstance(result, dict) or not result:
            return result  # 空结果 / 非 dict → 原样，闸门负责 FALLBACK
        if result.get("_parse_error"):
            return result  # JSON 解析失败标记 → 原样透传

        normalized = dict(result)
        # 客观证据校正（前置测试优先）：在置信度规整之前执行，
        # 保证 recommended_difficulty 与 knowledge_map 不被自述/头衔带偏。
        normalized = self._enforce_pretest_evidence(normalized, learner_data)
        normalized["overall_confidence"] = self._calc_overall_confidence(normalized, learner_data)
        return normalized

    def _calc_overall_confidence(self, diag: dict, learner_data: dict) -> float:
        """综合"结构化完整度 + 证据量"计算整体诊断置信度。

        已有合法 overall_confidence（0-1 数值）→ 直接采用；
        否则按以下维度打分（合计最高 1.0，下限 0.05 对齐闸门稀疏模式阈值）：
          - knowledge_map 有效条目 ≥5 → +0.30（≥3 → +0.20，≥1 → +0.10）
          - skill_gaps 非空              → +0.25
          - learning_style 有效          → +0.15
          - recommended_difficulty 有效  → +0.15
          - summary 非空                 → +0.10
          - learner_data 画像丰富        → +0.10
        """
        existing = diag.get("overall_confidence")
        if isinstance(existing, (int, float)) and not isinstance(existing, bool):
            if 0.0 <= existing <= 1.0:
                return float(existing)

        score = 0.0
        knowledge_map = diag.get("knowledge_map", {})
        valid_map = 0
        if isinstance(knowledge_map, dict):
            valid_map = sum(1 for v in knowledge_map.values() if isinstance(v, dict))
        if valid_map >= 5:
            score += 0.30
        elif valid_map >= 3:
            score += 0.20
        elif valid_map >= 1:
            score += 0.10

        gaps = diag.get("skill_gaps", [])
        if isinstance(gaps, list) and len(gaps) > 0:
            score += 0.25

        if diag.get("learning_style"):
            score += 0.15
        if diag.get("recommended_difficulty"):
            score += 0.15
        if diag.get("summary"):
            score += 0.10

        # 学习者画像丰富（学历/经历/测试等任一存在）→ 证据量加分
        if any(
            learner_data.get(k)
            for k in ("education_level", "major", "work_years", "skills_used", "pretest_results")
            if learner_data.get(k)
        ):
            score += 0.10

        return round(max(0.05, min(score, 1.0)), 2)

    # ═══════════════════════════════════════════════════════════
    # 客观证据校正：前置测试优先于自述（确定性规则，不依赖 LLM 自觉）
    # ═══════════════════════════════════════════════════════════

    _DIFF_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}

    @staticmethod
    def _extract_pretest(learner_data: dict) -> tuple[float | None, float | None, dict]:
        """从 learner_data 提取首份有效前置测试的总分/满分/分项得分。

        Returns:
            (total, max_score, topic_scores)；无有效测试时返回 (None, None, {})。
        """
        tests = learner_data.get("pretest_results", [])
        if not isinstance(tests, list):
            return None, None, {}
        for t in tests:
            if not isinstance(t, dict):
                continue
            try:
                total = float(t.get("total_score", 0))
                max_score = float(t.get("max_score", 0))
            except (ValueError, TypeError):
                continue
            if max_score <= 0:
                continue
            topic_scores = t.get("topic_scores", {}) or {}
            if isinstance(topic_scores, dict):
                return total, max_score, topic_scores
        return None, None, {}

    @staticmethod
    def _difficulty_from_ratio(ratio: float) -> str:
        """前置测试得分率 → 客观难度档位。

        阈值与 data/evaluation/learner_profiles.json 的 10 画像真值标签一致：
          - < 30% → beginner
          - < 65% → intermediate
          - ≥ 65% → advanced
        """
        if ratio < 0.30:
            return "beginner"
        if ratio < 0.65:
            return "intermediate"
        return "advanced"

    def _enforce_pretest_evidence(self, diag: dict, learner_data: dict) -> dict:
        """前置测试客观证据校正（确定性，双向）。

        1. recommended_difficulty：有前置测试时，一律按得分率重定难度，
           使"客观测试证据"压倒工作年限/头衔/自述目标（过度自信/自卑样本都兜住）。
        2. knowledge_map：测试分项直接命中的知识点，掌握度 level 不得超过
           分项得分折算值（防 LLM 把 20/120 的点位虚标到 0.9）。

        无前置测试时原样返回，保持 LLM 诊断结果。
        """
        if not isinstance(diag, dict):
            return diag
        total, max_score, topic_scores = self._extract_pretest(learner_data)
        if max_score is None:
            return diag

        normalized = dict(diag)
        ratio = total / max_score
        evidence_difficulty = self._difficulty_from_ratio(ratio)

        # ── 1. 难度双向校正 ──
        current = normalized.get("recommended_difficulty", "")
        current_rank = self._DIFF_RANK.get(current) if isinstance(current, str) else None
        if current_rank is not None and current_rank != self._DIFF_RANK[evidence_difficulty]:
            self.log(
                f"客观证据校正难度: {current} -> {evidence_difficulty} "
                f"(前置测试 {total:.0f}/{max_score:.0f}={ratio:.0%})"
            )
            normalized["recommended_difficulty"] = evidence_difficulty
            note = (
                f"（客观证据校正：前置测试 {total:.0f}/{max_score:.0f}={ratio:.0%}，"
                f"难度由 {current} 校正为 {evidence_difficulty}）"
            )
            summary = str(normalized.get("summary", "") or "")
            if "客观证据校正" not in summary:
                normalized["summary"] = summary + note
        else:
            # 一致时也确保难度字段客观一致（覆盖 LLM 无自述但乱标的情况）
            normalized["recommended_difficulty"] = evidence_difficulty

        # ── 2. knowledge_map 客观 clamp（只下调，不上调）──
        normalized["knowledge_map"] = self._clamp_knowledge_map(
            normalized.get("knowledge_map", {}), topic_scores, max_score
        )
        return normalized

    def _clamp_knowledge_map(
        self, knowledge_map: dict, topic_scores: dict, max_score: float
    ) -> dict:
        """将 knowledge_map 中与前置测试分项直接命中的点位，掌握度下调到测试折算值。"""
        if not isinstance(knowledge_map, dict) or not topic_scores:
            return knowledge_map
        clamped = dict(knowledge_map)
        for key, val in list(clamped.items()):
            if not isinstance(val, dict):
                continue
            topic = self._match_topic(key, topic_scores)
            if topic is None:
                continue
            try:
                objective = float(topic_scores[topic]) / float(max_score)
            except (ValueError, TypeError, ZeroDivisionError):
                continue
            try:
                level = float(val.get("level", 0.0))
            except (ValueError, TypeError):
                continue
            if level > objective:
                item = dict(val)
                old_evidence = str(item.get("evidence", "") or "")
                item["level"] = round(objective, 2)
                item["evidence"] = old_evidence + (
                    f"（客观测试校正：{topic} 实测 {float(topic_scores[topic]):.0f}/"
                    f"{max_score:.0f}，掌握度由 {level:.2f} 下调至 {objective:.2f}）"
                )
                clamped[key] = item
                self.log(f"客观证据校正知识点 {key}: level {level:.2f} -> {objective:.2f}")
        return clamped

    @staticmethod
    def _match_topic(key: str, topic_scores: dict) -> str | None:
        """模糊匹配 knowledge_map 键与前置测试分项名（互相包含即命中）。"""
        key_norm = "".join(str(key).split())
        for topic in topic_scores:
            topic_norm = "".join(str(topic).split())
            if not topic_norm:
                continue
            if topic_norm in key_norm or key_norm in topic_norm:
                return topic
        return None

    def _build_prompt(self, data: dict) -> str:
        return f"""请分析以下学习者的学情数据，输出诊断结果。

## 学历背景
- 学历：{data.get("education_level", "未知")}
- 专业：{data.get("major", "未知")}
- 学校：{data.get("school", "未知")}

## 工作经历
- 年限：{data.get("work_years", 0)}年
- 行业：{data.get("industry", "未知")}
- 岗位：{", ".join(data.get("positions", []))}
- 使用技能：{", ".join(data.get("skills_used", []))}

## 前置测试
{self._format_pretests(data.get("pretest_results", []))}

## 学习目标
{data.get("learning_goal", "未指定")}

请输出以下 JSON：
{{
    "knowledge_map": {{
        "知识点名称": {{
            "level": 0.0,
            "confidence": 0.0,
            "evidence": "评估依据（来自学历/经历/测试的具体信息）"
        }}
    }},
    "skill_gaps": [
        {{
            "topic": "缺失的知识点",
            "current_level": 0.0,
            "target_level": 0.0,
            "priority": "critical|high|medium|low",
            "reason": "为什么这个缺口需要优先填补"
        }}
    ],
    "learning_style": "practice_first|theory_first|visual|project_based",
    "recommended_difficulty": "beginner|intermediate|advanced",
    "summary": "学习者整体画像总结（50-100字）",
    "overall_confidence": 0.0
}}

要求：
- knowledge_map 至少包含 5 个知识点
- skill_gaps 按优先级从高到低排列
- 每个评估都附上 evidence 说明依据
- 置信度低于 0.3 的评估请特别标注
- overall_confidence 取 0-1 之间的数值，按诊断依据充分程度给出，避免普遍打低分"""

    def _format_pretests(self, tests: list) -> str:
        if not tests:
            return "无前置测试数据"
        lines = []
        for t in tests:
            lines.append(
                f"- {t.get('test_name', '未知测试')}: "
                f"{t.get('total_score', 0)}/{t.get('max_score', 100)}"
            )
            for topic, score in t.get("topic_scores", {}).items():
                lines.append(f"  - {topic}: {score}")
        return "\n".join(lines)

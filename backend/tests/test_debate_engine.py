"""博弈引擎单元测试 — 覆盖 Opt-2 三大核心场景。

对应 PHASE3_PLAN.md §4.2 交付标准：
  1. 三态裁决（支持A2 / 支持A3 / 未覆盖，未覆盖→删除）
  2. 权威等级加权（A > B，冲突取高权威）
  3. 终止边界（每资源 3 轮、每轮 N∈[3,5]，超限收口 + 问题衔接）

运行方式（在 backend/ 目录下）:
    pytest tests/test_debate_engine.py -v
    pytest tests/test_debate_engine.py -v -k ThreeState
    pytest tests/test_debate_engine.py -v -k Authority
    pytest tests/test_debate_engine.py -v -k Termination
"""

from backend.src.debate import rules
from backend.src.debate.engine import DebateEngine
from backend.src.debate.rules import ThreeState

# ═══════════════════════════════════════════════════════════
# 测试数据构造辅助
# ═══════════════════════════════════════════════════════════


def _item(claim: str, verdict: str | None = None, **kwargs) -> dict:
    """构造一条 audit 三态断言条目。"""
    item = {"claim": claim}
    if verdict is not None:
        item["verdict"] = verdict
    item.update(kwargs)
    return item


def _report(items: list[dict], resource_index: int = 0, **kwargs) -> dict:
    """构造单资源审核报告。"""
    return {
        "resource_index": resource_index,
        "resource_type": "lecture",
        "title": f"资源-{resource_index}",
        "fact_check": {"items": items},
        **kwargs,
    }


# ═══════════════════════════════════════════════════════════
# 1. 三态裁决
# ═══════════════════════════════════════════════════════════


class TestThreeStateAdjudication:
    """三态裁决规则（rules.adjudicate_three_state + 映射 + 引擎端到端）。"""

    def test_four_slot_priority(self):
        """四证据槽优先级：A反驳 > A支持 > B反驳 > B支持 > 未覆盖。"""
        assert rules.adjudicate_three_state(contradict_a="A反驳") == ThreeState.SUPPORT_A3
        assert rules.adjudicate_three_state(support_a="A支持") == ThreeState.SUPPORT_A2
        assert rules.adjudicate_three_state(contradict_b="B反驳") == ThreeState.SUPPORT_A3
        assert rules.adjudicate_three_state(support_b="B支持") == ThreeState.SUPPORT_A2
        assert rules.adjudicate_three_state() == ThreeState.UNCOVERED
        # 空字符串视为无证据
        assert rules.adjudicate_three_state(support_a="  ", support_b=None) == ThreeState.UNCOVERED

    def test_map_audit_verdict(self):
        """audit.py 三态 verdict → 博弈三态映射。"""
        assert rules.map_audit_verdict("accurate") == ThreeState.SUPPORT_A2
        assert rules.map_audit_verdict("hallucination") == ThreeState.SUPPORT_A3
        assert rules.map_audit_verdict("unverifiable") == ThreeState.UNCOVERED
        # 未知 verdict 保守判未覆盖（D1 删除）
        assert rules.map_audit_verdict("unknown") == ThreeState.UNCOVERED
        assert rules.map_audit_verdict(None) == ThreeState.UNCOVERED

    def test_decision_mapping(self):
        """三态 → 最终 decision 映射。"""
        assert rules.decision_from_state(ThreeState.SUPPORT_A2) == "keep"
        assert rules.decision_from_state(ThreeState.SUPPORT_A3) == "replace"
        assert rules.decision_from_state(ThreeState.UNCOVERED) == "delete"
        assert rules.decision_from_state("support_a2") == "keep"
        # 未知值保守 keep
        assert rules.decision_from_state("bogus") == "keep"

    def test_engine_end_to_end_three_state(self):
        """引擎端到端：三态断言 → keep/replace/delete，未覆盖→删除。"""
        report = _report(
            [
                _item("正确的断言", "accurate", evidence_from_kb="原文A", authority_level="A"),
                _item(
                    "错误的断言",
                    "hallucination",
                    evidence_from_kb="正确原文",
                    authority_level="A",
                ),
                _item("无法验证的断言", "unverifiable"),
            ]
        )
        result = DebateEngine().adjudicate([report])
        decisions = {a["claim"]: a["decision"] for a in result["adjudications"]}

        assert decisions["正确的断言"] == "keep"
        assert decisions["错误的断言"] == "replace"
        assert decisions["无法验证的断言"] == "delete"  # 未覆盖 → 直接删除
        assert result["unresolved_claims"] == []

    def test_replace_carries_replacement_text(self):
        """replace 裁决必须携带 KB 原文作为替换文本。"""
        report = _report(
            [
                _item(
                    "错误断言",
                    "hallucination",
                    evidence_from_kb="KB正确原文",
                    authority_level="B",
                ),
            ]
        )
        adj = DebateEngine().adjudicate([report])["adjudications"][0]
        assert adj["decision"] == "replace"
        assert adj["replacement_text"] == "KB正确原文"
        assert adj["authority_level"] == "B"


# ═══════════════════════════════════════════════════════════
# 2. 权威等级加权
# ═══════════════════════════════════════════════════════════


class TestAuthorityWeighting:
    """权威等级 A>B 加权：冲突取高权威，同权威反驳优先。"""

    def test_a_contradict_beats_b_support(self):
        """A 级反驳 > B 级支持 → 支持 A3。"""
        assert (
            rules.adjudicate_three_state(support_b="B级支持", contradict_a="A级反驳")
            == ThreeState.SUPPORT_A3
        )

    def test_a_support_beats_b_contradict(self):
        """A 级支持 > B 级反驳 → 支持 A2。"""
        assert (
            rules.adjudicate_three_state(support_a="A级支持", contradict_b="B级反驳")
            == ThreeState.SUPPORT_A2
        )

    def test_same_authority_contradict_priority(self):
        """同权威冲突：反驳优先（审核从严）。"""
        assert (
            rules.adjudicate_three_state(support_a="A支持", contradict_a="A反驳")
            == ThreeState.SUPPORT_A3
        )
        assert (
            rules.adjudicate_three_state(support_b="B支持", contradict_b="B反驳")
            == ThreeState.SUPPORT_A3
        )

    def test_resolve_by_authority(self):
        """resolve_by_authority：证据列表按最高权威裁决。"""
        # A 反驳 vs B 支持 → A 反驳胜
        assert (
            rules.resolve_by_authority(
                [{"text": "B支持", "authority": "B"}],
                [{"text": "A反驳", "authority": "A"}],
            )
            == ThreeState.SUPPORT_A3
        )
        # A 支持 vs B 反驳 → A 支持胜
        assert (
            rules.resolve_by_authority(
                [{"text": "A支持", "authority": "A"}],
                [{"text": "B反驳", "authority": "B"}],
            )
            == ThreeState.SUPPORT_A2
        )
        # 双方均无证据 → 未覆盖
        assert rules.resolve_by_authority([], []) == ThreeState.UNCOVERED
        assert rules.resolve_by_authority(None, None) == ThreeState.UNCOVERED

    def test_engine_raw_evidence_path(self):
        """引擎原始证据路径：A 反驳 + B 支持 → replace。"""
        report = _report(
            [
                {
                    "claim": "有争议的断言",
                    "support_b": "B级二手支持",
                    "contradict_a": "A级一手反驳原文",
                }
            ]
        )
        adj = DebateEngine().adjudicate([report])["adjudications"][0]
        assert adj["decision"] == "replace"
        assert adj["replacement_text"] == "A级一手反驳原文"
        assert adj["authority_level"] == "A"

    def test_normalize_authority(self):
        """权威等级归一化。"""
        assert rules.normalize_authority("a") == "A"
        assert rules.normalize_authority("OFFICIAL") == "A"
        assert rules.normalize_authority("二手") == "B"
        assert rules.normalize_authority(None) == "unknown"
        assert rules.authority_rank("A") > rules.authority_rank("B")


# ═══════════════════════════════════════════════════════════
# 3. 终止边界 + 问题衔接
# ═══════════════════════════════════════════════════════════


class TestTerminationBoundary:
    """终止边界：每资源 3 轮、每轮 N∈[3,5]，超限收口；争议集合清空=辩论结束。"""

    def test_rounds_capped_at_max(self):
        """20 个争议断言，最多 3 轮 × 5 断言，超出收口。"""
        items = [_item(f"争议断言{i}", "unverifiable") for i in range(20)]
        engine = DebateEngine(max_rounds=3, claims_per_round=5)
        result = engine.adjudicate([_report(items)])

        adjs = result["adjudications"]
        summary = result["resource_summaries"][0]

        assert len(adjs) == 20
        # 轮次不超过上限
        assert max(a["round"] for a in adjs) <= 3
        # 前 15 个在 3 轮内（每轮 5 个），后 5 个收口
        rounds = [a["round"] for a in adjs if not a["closeout"]]
        closed = [a for a in adjs if a["closeout"]]
        assert len(rounds) == 15
        assert len(closed) == 5
        assert summary["rounds_used"] == 3
        assert summary["closed_out_count"] == 5
        assert summary["debate_ended"] is True
        assert result["unresolved_claims"] == []

    def test_claims_per_round_clamped(self):
        """每轮 N 收敛到 [3,5] 区间。"""
        assert rules.clamp_claims_per_round(1) == 3
        assert rules.clamp_claims_per_round(3) == 3
        assert rules.clamp_claims_per_round(4) == 4
        assert rules.clamp_claims_per_round(5) == 5
        assert rules.clamp_claims_per_round(10) == 5
        assert rules.clamp_claims_per_round("abc") == 5

    def test_per_round_batch_size(self):
        """每轮最多 N 个断言：10 个争议 + N=3 → 3轮×3 + 1 收口。"""
        items = [_item(f"断言{i}", "hallucination", evidence_from_kb="KB原文") for i in range(10)]
        engine = DebateEngine(max_rounds=3, claims_per_round=3)
        result = engine.adjudicate([_report(items)])

        rounds = [a["round"] for a in result["adjudications"] if not a["closeout"]]
        closed = [a for a in result["adjudications"] if a["closeout"]]
        # 每轮 3 个：round1=3, round2=3, round3=3，收口 1
        from collections import Counter

        counts = Counter(rounds)
        assert counts == {1: 3, 2: 3, 3: 3}
        assert len(closed) == 1

    def test_question_sequencing_and_closure(self):
        """问题衔接：question_id 顺序递增，争议集合清空 → 辩论结束。"""
        items = [
            _item("问题一", "unverifiable"),
            _item("问题二", "hallucination", evidence_from_kb="原文"),
            _item("问题三", "unverifiable"),
        ]
        result = DebateEngine().adjudicate([_report(items)])

        qids = [a["question_id"] for a in result["adjudications"]]
        assert qids == [1, 2, 3]  # 自动衔接下一个争议问题
        assert result["resource_summaries"][0]["debate_ended"] is True
        assert result["resource_summaries"][0]["disputed_count"] == 3

    def test_agreed_claims_skip_rounds(self):
        """支持 A2（accurate）断言不占用轮次，直接 keep。"""
        items = [
            _item("已共识断言", "accurate", evidence_from_kb="原文", authority_level="A"),
            _item("争议断言", "unverifiable"),
        ]
        result = DebateEngine().adjudicate([_report(items)])

        by_claim = {a["claim"]: a for a in result["adjudications"]}
        assert by_claim["已共识断言"]["round"] == 0  # 不进轮次
        assert by_claim["已共识断言"]["decision"] == "keep"
        assert by_claim["争议断言"]["round"] == 1
        assert result["resource_summaries"][0]["agreed_count"] == 1

    def test_downstream_contract_compatible(self):
        """输出形状满足 correction.py 的 debate_result 消费契约。"""
        report = _report(
            [
                _item("保留断言", "accurate", evidence_from_kb="原文", authority_level="A"),
                _item("替换断言", "hallucination", evidence_from_kb="KB原文", authority_level="B"),
                _item("删除断言", "unverifiable"),
            ]
        )
        result = DebateEngine().adjudicate([_report(items=report["fact_check"]["items"])])

        assert "adjudications" in result
        assert "unresolved_claims" in result
        for adj in result["adjudications"]:
            assert adj["resource_id"]
            assert adj["claim"]
            assert adj["decision"] in ("keep", "replace", "delete")


class TestAsyncRun:
    """编排器接入入口 run()。"""

    async def test_run_returns_debate_result(self):
        engine = DebateEngine()
        state = {
            "audit_result": [
                _report([_item("断言", "unverifiable")]),
            ],
            "generated_resources": [
                {"resource_id": "res-100", "resource_type": "lecture"},
            ],
        }
        result = await engine.run(state)
        assert "debate_result" in result
        assert result["debate_result"]["adjudications"][0]["resource_id"] == "res-100"

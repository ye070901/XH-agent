"""博弈引擎主逻辑 — 纯规则裁决，禁止调用 LLM。

对应 PHASE3_PLAN.md §4.2（Opt-2 交付标准）：
  1. 三态裁决：每个争议断言查 KB → 支持A2 / 支持A3 / 未覆盖，未覆盖→删除
  2. 权威等级加权：A>B，冲突取高权威（规则见 rules.py）
  3. 终止边界：每资源最多 3 轮，每轮 N∈[3,5] 个断言，超出直接收口
  4. 问题衔接：完成一个争议问题裁决闭环后，自动切换下一个；
     全部清空争议集合 → 该资源辩论结束
  5. 依赖：上游消费 K2 模块 audit.py 输出的三态结果；本模块不调 LLM

输入（state / 参数）:
  - audit_result:        audit.py 逐资源审核报告（含 fact_check.items 三态断言）
  - generated_resources: 用于把 resource_index 映射为下游所需的 resource_id

输出（debate_result，与 correction.py 的消费契约对齐）:
  {"adjudications": [...], "unresolved_claims": [...], "resource_summaries": [...], "stats": {...}}
  单条 adjudication 字段:
    resource_id / resource_index / claim / decision(keep|replace|delete) /
    replacement_text / doc_id / chunk_index / evidence / authority_level /
    round / question_id / closeout
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from loguru import logger

from ..config import settings
from . import rules


@dataclass
class _ResourceDebate:
    """单资源辩论状态机：维护争议队列 + 轮次 + 裁决结果。"""

    resource_index: int
    resource_id: str
    resource_type: str = ""
    title: str = ""
    max_rounds: int = rules.MAX_ROUNDS_DEFAULT
    claims_per_round: int = rules.MAX_CLAIMS_PER_ROUND
    current_round: int = 0
    question_seq: int = 0                 # 争议问题序号（衔接可视化）
    queue: deque = field(default_factory=deque)
    adjudications: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


class DebateEngine:
    """博弈引擎 — 三态裁决 + 权威加权 + 终止边界 + 问题衔接（纯规则）。"""

    def __init__(
        self,
        max_rounds: int | None = None,
        claims_per_round: int = rules.MAX_CLAIMS_PER_ROUND,
    ) -> None:
        self.max_rounds = max_rounds or settings.DEBATE_MAX_ROUNDS
        self.claims_per_round = rules.clamp_claims_per_round(claims_per_round)

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def adjudicate(
        self,
        audit_result: list[dict] | None = None,
        generated_resources: list[dict] | None = None,
    ) -> dict:
        """逐资源执行三态裁决，返回 debate_result（纯规则，同步）。"""
        id_by_index = self._build_resource_id_map(generated_resources or [])

        adjudications: list[dict] = []
        unresolved_claims: list[str] = []
        summaries: list[dict] = []

        for report in audit_result or []:
            if not isinstance(report, dict):
                continue
            summary, adjs, unresolved = self._adjudicate_resource(
                report, id_by_index)
            summaries.append(summary)
            adjudications.extend(adjs)
            unresolved_claims.extend(unresolved)

        stats = self._summarize(adjudications, summaries, unresolved_claims)
        return {
            "adjudications": adjudications,
            "unresolved_claims": unresolved_claims,
            "resource_summaries": summaries,
            "stats": stats,
        }

    async def run(self, state: dict) -> dict:
        """编排器接入入口：从 state 读取上游三态结果，写回 debate_result。"""
        audit_result = state.get("audit_result", []) or []
        generated_resources = state.get("generated_resources", []) or []
        return {"debate_result": self.adjudicate(audit_result, generated_resources)}

    # ═══════════════════════════════════════════════════════════
    # 单资源辩论
    # ═══════════════════════════════════════════════════════════

    def _adjudicate_resource(
        self, report: dict, id_by_index: dict[int, str]
    ) -> tuple[dict, list[dict], list[str]]:
        idx = int(report.get("resource_index", 0) or 0)
        resource_id = str(
            report.get("resource_id") or id_by_index.get(idx) or f"res-{idx}"
        )
        resource_type = str(report.get("resource_type") or "")
        title = str(report.get("title") or "")
        items = self._extract_items(report)

        state = _ResourceDebate(
            resource_index=idx,
            resource_id=resource_id,
            resource_type=resource_type,
            title=title,
            max_rounds=self.max_rounds,
            claims_per_round=self.claims_per_round,
        )

        # 1. 无争议断言（支持A2）→ 直接 keep，不占用轮次
        agreed = [it for it in items if self._state_of(
            it) == rules.ThreeState.SUPPORT_A2]
        disputed = [it for it in items if self._state_of(
            it) != rules.ThreeState.SUPPORT_A2]

        for it in agreed:
            self._process_one(state, it, resource_id,
                              round_number=0, closeout=False)

        # 2. 争议断言 → 轮次辩论（每轮最多 N 个，最多 max_rounds 轮）
        state.queue = deque(disputed)
        while state.queue and state.current_round < state.max_rounds:
            state.current_round += 1
            batch_size = min(state.claims_per_round, len(state.queue))
            batch = [state.queue.popleft() for _ in range(batch_size)]
            for it in batch:
                self._process_one(
                    state, it, resource_id, round_number=state.current_round, closeout=False
                )
            logger.debug(
                f"[博弈引擎] {resource_id} 第 {state.current_round} 轮辩论闭环："
                f"裁决 {len(batch)} 个争议断言，剩余 {len(state.queue)} 个"
            )

        # 3. 超出轮次上限 → 收口：一次性裁决剩余争议断言（终止边界）
        closed_out = 0
        while state.queue:
            it = state.queue.popleft()
            self._process_one(
                state, it, resource_id, round_number=state.current_round, closeout=True
            )
            closed_out += 1
        if closed_out:
            logger.warning(
                f"[博弈引擎] {resource_id} 超出 {self.max_rounds} 轮上限，"
                f"收口 {closed_out} 个争议断言"
            )

        debate_ended = not state.queue  # 争议集合已清空 → 该资源辩论全部结束
        summary = {
            "resource_index": idx,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "title": title,
            "agreed_count": len(agreed),
            "disputed_count": len(disputed),
            "rounds_used": state.current_round,
            "closed_out_count": closed_out,
            "unresolved_count": len(state.unresolved),
            "debate_ended": debate_ended,
        }
        return summary, state.adjudications, state.unresolved

    def _process_one(
        self,
        state: _ResourceDebate,
        item: dict,
        resource_id: str,
        round_number: int,
        closeout: bool,
    ) -> None:
        """处理单个争议问题：裁决闭环 → 记录 → 自动衔接下一个。"""
        state.question_seq += 1
        adj = self._resolve(
            item,
            resource_id=resource_id,
            resource_index=state.resource_index,
            round_number=round_number,
            question_id=state.question_seq,
            closeout=closeout,
        )
        if adj is None:
            state.unresolved.append(str(item.get("claim") or item))
            return
        state.adjudications.append(adj)

    # ═══════════════════════════════════════════════════════════
    # 单断言裁决
    # ═══════════════════════════════════════════════════════════

    def _resolve(
        self,
        item: dict,
        resource_id: str,
        resource_index: int,
        round_number: int,
        question_id: int,
        closeout: bool,
    ) -> dict | None:
        """把单条断言裁决为最终 decision（keep/replace/delete）。"""
        claim = str(item.get("claim") or "").strip()
        if not claim:
            return None  # 无法定位的断言 → 交由 unresolved 记录

        state = self._state_of(item)
        decision = rules.decision_from_state(state)
        evidence, authority = self._evidence_of(item, state)

        return {
            "resource_id": resource_id,
            "resource_index": resource_index,
            "claim": claim,
            "decision": decision,
            "three_state": state.value,
            "replacement_text": evidence if decision == "replace" else "",
            "doc_id": str(item.get("citation_ref") or ""),
            "chunk_index": item.get("chunk_index"),
            "evidence": evidence,
            "authority_level": authority,
            "round": round_number,
            "question_id": question_id,
            "closeout": closeout,
        }

    @staticmethod
    def _state_of(item: dict) -> rules.ThreeState:
        """判定断言三态：优先原始证据（权威加权），否则映射 audit verdict。"""
        raw_keys = ("support_a", "support_b", "contradict_a", "contradict_b")
        if any(k in item for k in raw_keys):
            return rules.adjudicate_three_state(
                support_a=item.get("support_a"),
                support_b=item.get("support_b"),
                contradict_a=item.get("contradict_a"),
                contradict_b=item.get("contradict_b"),
            )
        return rules.map_audit_verdict(item.get("verdict"))

    @staticmethod
    def _evidence_of(item: dict, state: rules.ThreeState) -> tuple[str, str]:
        """提取获胜证据原文 + 权威等级（用于下游 replace 替换 / keep 溯源）。"""
        evidence = str(item.get("evidence_from_kb") or "").strip()
        if not evidence and state == rules.ThreeState.SUPPORT_A3:
            evidence = str(item.get("contradict_a")
                           or item.get("contradict_b") or "").strip()
        elif not evidence and state == rules.ThreeState.SUPPORT_A2:
            evidence = str(item.get("support_a")
                           or item.get("support_b") or "").strip()

        authority = rules.normalize_authority(item.get("authority_level"))
        if authority == rules.AUTHORITY_UNKNOWN:
            if state == rules.ThreeState.SUPPORT_A3:
                authority = rules.AUTHORITY_A if item.get(
                    "contradict_a") else rules.AUTHORITY_B
            elif state == rules.ThreeState.SUPPORT_A2:
                authority = rules.AUTHORITY_A if item.get(
                    "support_a") else rules.AUTHORITY_B
        return evidence, authority

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_items(report: dict) -> list[dict]:
        """从审核报告中提取三态断言列表（兼容 fact_check.items / 平铺 items）。"""
        fact_check = report.get("fact_check") if isinstance(
            report.get("fact_check"), dict) else {}
        items = fact_check.get("items") or []
        if not items:
            items = report.get("items") or []
        return [it for it in items if isinstance(it, dict)]

    @staticmethod
    def _build_resource_id_map(resources: list[dict]) -> dict[int, str]:
        """构建 resource_index → resource_id 映射（audit 报告按 index 关联资源）。"""
        mapping: dict[int, str] = {}
        for i, r in enumerate(resources or []):
            if isinstance(r, dict) and r.get("resource_id"):
                mapping[i] = r["resource_id"]
        return mapping

    @staticmethod
    def _summarize(
        adjudications: list[dict],
        summaries: list[dict],
        unresolved_claims: list[str],
    ) -> dict:
        """汇总全局统计。"""
        decisions: dict[str, int] = {"keep": 0, "replace": 0, "delete": 0}
        for adj in adjudications:
            d = adj.get("decision")
            if d in decisions:
                decisions[d] += 1
        return {
            "total_resources": len(summaries),
            "total_adjudications": len(adjudications),
            "decisions": decisions,
            "unresolved_count": len(unresolved_claims),
        }


# 全局单例 — 编排器（Arch-L）通过此实例接入博弈引擎
debate_engine = DebateEngine()

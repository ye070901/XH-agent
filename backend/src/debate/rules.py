"""博弈引擎裁决规则 — 纯代码模块，禁止调用 LLM。

对应 PHASE3_PLAN.md §4.2（Opt-2 交付标准）与 D2/D3/D4 决策：
  - 三态裁决：每个争议断言查 KB → 支持A2 / 支持A3 / 未覆盖 三态
      · 支持A2  = KB 原文支持 Agent2 的原始断言 → 保持原文 + 标来源
      · 支持A3  = KB 原文支持 Agent3 的质疑 → Agent2 撤回 / 用原文替换
      · 未覆盖  = KB 无对应原文，无法验证 → 直接删除（D1 无权威参考=删除）
  - 权威等级加权：A 级一手原文 > B 级二手，冲突取高权威；同权威冲突反驳优先（审核从严）
  - 终止边界常量：每资源最多轮次、每轮断言数区间

本模块只包含纯函数与常量，不 import 任何 LLM / Agent / 网络模块，
保证裁决逻辑可独立单测、零幻觉引入。
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class ThreeState(str, Enum):
    """三态裁决结果（争议断言的 KB 比对结论）。"""

    SUPPORT_A2 = "support_a2"  # 支持 A2：保持原文 + 标来源
    SUPPORT_A3 = "support_a3"  # 支持 A3：撤回 / 用 KB 原文替换
    UNCOVERED = "uncovered"  # 未覆盖：直接删除（D1）


# ═══════════════════════════════════════════════════════════
# 权威等级常量
# ═══════════════════════════════════════════════════════════

AUTHORITY_A = "A"  # 一手原文（官方手册 / 说明书 / 规格书等）
AUTHORITY_B = "B"  # 二手资料（教程 / 课程 / 指南 / 社区整理等）
AUTHORITY_UNKNOWN = "unknown"

# 权威等级 → 数值权重（越大越权威）
_AUTHORITY_RANK: dict[str, int] = {
    AUTHORITY_A: 2,
    AUTHORITY_B: 1,
    AUTHORITY_UNKNOWN: 0,
}

# A 级（一手原文）别名
_A_LEVEL_ALIASES = ("A", "OFFICIAL", "PRIMARY", "一手", "一级", "官方")
# B 级（二手资料）别名
_B_LEVEL_ALIASES = ("B", "SECONDARY", "二手", "二级")

# ═══════════════════════════════════════════════════════════
# 终止边界常量（D4）
# ═══════════════════════════════════════════════════════════

MAX_ROUNDS_DEFAULT = 3  # 每资源最多辩论轮次
MIN_CLAIMS_PER_ROUND = 3  # 每轮争议断言下限
MAX_CLAIMS_PER_ROUND = 5  # 每轮争议断言上限（N ∈ [3, 5]）

# ═══════════════════════════════════════════════════════════
# 映射表
# ═══════════════════════════════════════════════════════════

# 三态 → 下游最终 decision（correction.py 契约：keep / replace / delete）
STATE_TO_DECISION: dict[ThreeState, str] = {
    ThreeState.SUPPORT_A2: "keep",
    ThreeState.SUPPORT_A3: "replace",
    ThreeState.UNCOVERED: "delete",
}

# audit.py 四态 verdict → 博弈三态（K2 上游输出对齐）
AUDIT_VERDICT_TO_STATE: dict[str, ThreeState] = {
    "accurate": ThreeState.SUPPORT_A2,
    "hallucination": ThreeState.SUPPORT_A3,
    # 核心事实成立但细节缺失：仍属"支持"而非未覆盖，避免被保守兜底删掉
    "partially_supported": ThreeState.SUPPORT_A2,
    "unverifiable": ThreeState.UNCOVERED,
}


# ═══════════════════════════════════════════════════════════
# 权威等级工具
# ═══════════════════════════════════════════════════════════


def normalize_authority(level: str | None) -> str:
    """把任意权威等级写法归一化为 A / B / unknown。"""
    if not level:
        return AUTHORITY_UNKNOWN
    raw = str(level).strip().upper()
    if raw in _A_LEVEL_ALIASES:
        return AUTHORITY_A
    if raw in _B_LEVEL_ALIASES:
        return AUTHORITY_B
    return AUTHORITY_UNKNOWN


def authority_rank(level: str | None) -> int:
    """返回权威等级的数值权重（A=2 > B=1 > unknown=0）。"""
    return _AUTHORITY_RANK.get(normalize_authority(level), 0)


def _has_text(value) -> bool:
    """判断证据文本是否非空。"""
    return bool(str(value or "").strip())


# ═══════════════════════════════════════════════════════════
# 核心裁决：三态 + 权威加权
# ═══════════════════════════════════════════════════════════


def adjudicate_three_state(
    support_a=None,
    support_b=None,
    contradict_a=None,
    contradict_b=None,
) -> ThreeState:
    """按权威等级 A>B 裁决三态（四证据槽形式，对齐 audit.py 内部比对）。

    优先级（A 级一手原文 > B 级二手；同权威冲突反驳优先，审核从严）：
      1. contradict_a（A 级反驳）→ 支持 A3
      2. support_a    （A 级支持）→ 支持 A2
      3. contradict_b（B 级反驳）→ 支持 A3
      4. support_b    （B 级支持）→ 支持 A2
      5. 全部无证据            → 未覆盖
    """
    if _has_text(contradict_a):
        return ThreeState.SUPPORT_A3
    if _has_text(support_a):
        return ThreeState.SUPPORT_A2
    if _has_text(contradict_b):
        return ThreeState.SUPPORT_A3
    if _has_text(support_b):
        return ThreeState.SUPPORT_A2
    return ThreeState.UNCOVERED


def resolve_by_authority(
    support_evidence: Iterable[dict] | dict | None,
    contradict_evidence: Iterable[dict] | dict | None,
) -> ThreeState:
    """支持 / 反驳证据冲突时，取更高权威一方裁决（权威加权通用入口）。

    每条证据形如 {"text"/"content": ..., "authority"/"authority_level": "A"|"B"}。
    - 双方最高权威相等时，反驳优先（审核从严）；
    - 仅一方有证据时，直接取该方结论；
    - 双方均无证据 → 未覆盖。
    """
    supports = _normalize_evidence(support_evidence)
    contradicts = _normalize_evidence(contradict_evidence)

    best_support = max((authority_rank(auth) for _, auth in supports), default=-1)
    best_contradict = max((authority_rank(auth) for _, auth in contradicts), default=-1)

    if best_support < 0 and best_contradict < 0:
        return ThreeState.UNCOVERED
    # 反驳权威 ≥ 支持权威 → 反驳胜出（含同权威反驳优先）
    if best_contradict >= best_support:
        return ThreeState.SUPPORT_A3
    return ThreeState.SUPPORT_A2


def _normalize_evidence(evidence) -> list[tuple[str, str]]:
    """把证据规整为 [(text, authority), ...]，过滤空文本，附带归一化权威。"""
    if not evidence:
        return []
    if isinstance(evidence, dict):
        evidence = [evidence]
    out: list[tuple[str, str]] = []
    for e in evidence:
        if not isinstance(e, dict):
            continue
        text = str(e.get("text") or e.get("content") or "").strip()
        if not text:
            continue
        auth = normalize_authority(e.get("authority") or e.get("authority_level"))
        out.append((text, auth))
    return out


# ═══════════════════════════════════════════════════════════
# 三态 → 映射工具
# ═══════════════════════════════════════════════════════════


def map_audit_verdict(verdict: str | None) -> ThreeState:
    """把 audit.py 三态 verdict 映射为博弈三态；未知值保守判「未覆盖」（删除）。"""
    return AUDIT_VERDICT_TO_STATE.get(str(verdict or "").strip().lower(), ThreeState.UNCOVERED)


def decision_from_state(state: ThreeState | str) -> str:
    """三态 → 下游最终 decision（keep / replace / delete）。未知值保守 keep。"""
    if isinstance(state, ThreeState):
        return STATE_TO_DECISION.get(state, "keep")
    try:
        key = ThreeState(str(state).lower())
    except ValueError:
        return "keep"
    return STATE_TO_DECISION.get(key, "keep")


def clamp_claims_per_round(n: int) -> int:
    """把每轮断言数收敛到 [3, 5] 区间（D4：每轮 N 取值 3~5）。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = MAX_CLAIMS_PER_ROUND
    return max(MIN_CLAIMS_PER_ROUND, min(MAX_CLAIMS_PER_ROUND, n))

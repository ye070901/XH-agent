# -*- coding: utf-8 -*-
"""
K1 画像回写：答题对错 → 规则化更新 learner 画像（B 的组成部分）
═══════════════════════════════════════════════════════
对应 PHASE3_PLAN.md §4.5 画像回写（纯规则驱动，不调 LLM）：
  答错 → knowledge_map 对应知识点掌握度下调 + 置信度上调（获得实测证据）、
         skill_gaps.current_level 修正；
  答对 → 掌握度上调。
  回写自动刷新 learner_profiles.updated_at。

对接持久化层：backend/src/persistence/profile_store.py 的 ProfileStore
  （仓库真实 SQLite 持久化层，绝不写死模拟路径）。
  默认使用模块级 ProfileStore 单例 profile_store；update_profile 内部负责
  “深合并 + updated_at 自动刷新”。profile_id 缺省时自动取该学习者的
  最新画像快照，无快照则先创建初始画像再回写。

对外统一入口函数：
  async update_learner_profile(learner_id, knowledge_point, is_correct,
                               store=None, profile_id=None)
  同步便捷入口：profile_write_pipeline(...)（内部 asyncio.run 包装）
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════
# 持久化层导入：优先按包内相对导入使用仓库真实 ProfileStore；
# 独立脚本运行时递归向上定位仓库 src 包后导入；仍不可得则置空
# （此时业务调用将给出清晰报错，绝不伪造模拟路径）。
# ═══════════════════════════════════════════════════════════

try:
    from ..persistence.profile_store import ProfileStore
    from ..persistence.profile_store import profile_store as default_profile_store
except ImportError:  # pragma: no cover - 独立运行兜底
    try:
        _repo_found = None
        _here = Path(__file__).resolve()
        for _parent in _here.parents:  # 向上回溯，找含 src/persistence/profile_store.py 的仓库根
            if (_parent / "src" / "persistence" / "profile_store.py").exists():
                _repo_found = _parent
                break
        if _repo_found is not None:
            if str(_repo_found) not in sys.path:
                sys.path.insert(0, str(_repo_found))
            from src.persistence.profile_store import ProfileStore  # type: ignore
            from src.persistence.profile_store import profile_store as default_profile_store  # type: ignore
        else:
            ProfileStore = None  # type: ignore
            default_profile_store = None  # type: ignore
    except Exception:  # 持久化层依赖缺失等 → 置空，业务调用时给出明确报错，不伪造模拟路径
        ProfileStore = None  # type: ignore
        default_profile_store = None  # type: ignore

# ═══════════════════════════════════════════════════════════
# 规则参数（步长与阈值，统一集中便于调参）
# ═══════════════════════════════════════════════════════════

LEVEL_STEP_UP = 0.12          # 答对：掌握度上调步长
LEVEL_STEP_DOWN = 0.18        # 答错：掌握度下调步长（略大于奖励，引导巩固）
CONFIDENCE_GAIN_CORRECT = 0.15  # 答对：置信度向 1 靠拢的比例（获得正向实测证据）
CONFIDENCE_GAIN_WRONG = 0.30    # 答错：置信度上调更多（获得“不会”的反向实测证据）
GAP_TARGET_DEFAULT = 0.85       # 缺口目标掌握度（无既有目标时的默认值）


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """数值收敛到 [low, high]。"""
    return max(low, min(high, value))


def _now_iso() -> str:
    """UTC ISO8601 时间戳（与 ProfileStore.updated_at 同构）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gap_priority(level: float) -> str:
    """按当前掌握度推断缺口优先级（critical > high > medium > low）。"""
    if level < 0.30:
        return "critical"
    if level < 0.60:
        return "high"
    if level < 0.85:
        return "medium"
    return "low"


def apply_rules(
    profile: dict[str, Any],
    knowledge_point: str,
    is_correct: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """纯规则核心：根据对错计算新的 knowledge_map 与 skill_gaps（不落库）。

    规则：
      - knowledge_map[kp].level：答对 +LEVEL_STEP_UP，答错 -LEVEL_STEP_DOWN（clamp 0~1）
      - knowledge_map[kp].confidence：无论对错都上调（获得实测证据），
        错题上调更多并追加“实测错题”证据。
      - skill_gaps：答错 → 更新/新增该知识点缺口（current_level=新 level，
        优先级按新 level 定档）；答对 → 若缺口达成目标则移除，否则降档保留；
        答对且无缺口则不新增。

    Args:
        profile:        当前画像快照的 profile dict（含 knowledge_map / skill_gaps）。
        knowledge_point: 本次作答对应的知识点。
        is_correct:      是否答对。

    Returns:
        (new_knowledge_map, new_skill_gaps, diff)：
          diff 记录 level / confidence 前后值，供调用方回显与统计。
    """
    kp = knowledge_point
    knowledge_map = dict(profile.get("knowledge_map") or {})
    gaps = [dict(g) for g in (profile.get("skill_gaps") or [])]

    entry = dict(
        knowledge_map.get(kp)
        or {"level": 0.30, "confidence": 0.10, "evidence": "初始默认评估"}
    )
    old_level = _clamp(float(entry.get("level", 0.30)))
    old_confidence = _clamp(float(entry.get("confidence", 0.10)))

    # 1) 掌握度调整
    new_level = old_level + (LEVEL_STEP_UP if is_correct else -LEVEL_STEP_DOWN)
    new_level = round(_clamp(new_level), 4)

    # 2) 置信度调整（获得实测证据 → 上调，向 1 收敛）
    gain = CONFIDENCE_GAIN_CORRECT if is_correct else CONFIDENCE_GAIN_WRONG
    new_confidence = round(old_confidence + (1.0 - old_confidence) * gain, 4)

    # 3) 证据链追加（按“对/错”两类记录，保留最近一次）
    verdict = "对" if is_correct else "错"
    evidence = entry.get("evidence") or ""
    new_evidence = f"{evidence}；[{_now_iso()}] 习题实测答{verdict}" if evidence else f"[{_now_iso()}] 习题实测答{verdict}"

    entry.update(
        level=new_level,
        confidence=new_confidence,
        evidence=new_evidence,
    )
    knowledge_map[kp] = entry

    # 4) skill_gaps 修正
    gap = next((g for g in gaps if g.get("topic") == kp or g.get("knowledge_point") == kp), None)
    if not is_correct:
        # 答错 → 更新或新增缺口
        if gap is not None:
            gap["current_level"] = new_level
            gap["target_level"] = float(gap.get("target_level", GAP_TARGET_DEFAULT))
            gap["priority"] = _gap_priority(new_level)
            gap["reason"] = "习题实测答错，掌握度下调"
        else:
            gaps.append(
                {
                    "topic": kp,
                    "knowledge_point": kp,
                    "current_level": new_level,
                    "target_level": GAP_TARGET_DEFAULT,
                    "priority": _gap_priority(new_level),
                    "reason": "习题实测答错，新增待补缺口",
                }
            )
    else:
        # 答对 → 掌握度上调；已达标则移除缺口，否则保留并降档
        if gap is not None:
            gap["current_level"] = new_level
            target = float(gap.get("target_level", GAP_TARGET_DEFAULT))
            if new_level >= target:
                gaps = [g for g in gaps if g is not gap]
            else:
                gap["priority"] = _gap_priority(new_level)
                gap["reason"] = "习题实测答对，掌握度回升"

    diff = {
        "level_before": old_level,
        "level_after": new_level,
        "confidence_before": old_confidence,
        "confidence_after": new_confidence,
    }
    return knowledge_map, gaps, diff


async def update_learner_profile(
    learner_id: str,
    knowledge_point: str,
    is_correct: bool,
    store: Any = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """画像回写统一入口（对外调用）。

    规则驱动、不调 LLM：将单次作答对错回写到学习者最新画像快照。

    Args:
        learner_id:      学习者 ID。
        knowledge_point: 本次作答知识点。
        is_correct:      是否答对。
        store:           ProfileStore 实例；默认使用仓库单例 profile_store。
        profile_id:      指定画像快照；缺省时取该学习者最新快照，
                         无快照则先创建初始画像。

    Returns:
        dict: profile_id / learner_id / knowledge_point / is_correct /
              level_before / level_after / confidence_before / confidence_after /
              gaps / updated_at
    """
    target_store = store if store is not None else default_profile_store
    if target_store is None:
        raise RuntimeError(
            "无法定位仓库持久化层（ProfileStore）——请以 backend 包内模块方式运行，"
            "或显式传入 store 参数；绝不使用模拟路径回写。"
        )

    await target_store.initialize()
    pid = profile_id
    current = None

    if pid is None:
        listing = await target_store.list_profiles(learner_id=learner_id, limit=1)
        if listing["items"]:
            current = listing["items"][0]
            pid = current["profile_id"]
        else:
            # 首次回写：先建立初始画像快照
            record = await target_store.save_profile(
                {
                    "learner_id": learner_id,
                    "label": "k1_initial",
                    "profile": {
                        "name": f"learner_{learner_id}",
                        "knowledge_map": {},
                        "skill_gaps": [],
                    },
                }
            )
            pid = record["profile_id"]
    else:
        current = await target_store.get_profile(pid)
        if current is None:
            raise ValueError(f"画像快照不存在: profile_id={pid}")

    profile = dict(current["profile"]) if current and current.get("profile") else {}
    km, gaps, diff = apply_rules(profile, knowledge_point, is_correct)

    # update_profile：深合并 + 自动刷新 updated_at（持久化层既有能力）
    updated = await target_store.update_profile(pid, {"knowledge_map": km, "skill_gaps": gaps})
    return {
        "profile_id": pid,
        "learner_id": learner_id,
        "knowledge_point": knowledge_point,
        "is_correct": bool(is_correct),
        "level_before": diff["level_before"],
        "level_after": diff["level_after"],
        "confidence_before": diff["confidence_before"],
        "confidence_after": diff["confidence_after"],
        "gaps": gaps,
        "updated_at": updated["updated_at"],
    }


def profile_write_pipeline(
    learner_id: str,
    knowledge_point: str,
    is_correct: bool,
    store: Any = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """同步便捷入口：直接调用即完成一次画像回写。

    说明：内部使用 asyncio.run 包装异步入口；在已有事件循环的异步
    环境中请直接调用 update_learner_profile。
    """
    return asyncio.run(
        update_learner_profile(
            learner_id, knowledge_point, is_correct,
            store=store, profile_id=profile_id,
        )
    )


if __name__ == "__main__":
    # ── 单元自测（独立运行） ──
    # 1) 先验证纯规则函数（不依赖持久化层，任何环境可跑）
    print("== 纯规则自测：答错 → 掌握度下调 + 置信度上调 + 新增缺口 ==")
    base = {"knowledge_map": {"FANUC点位编程": {"level": 0.5, "confidence": 0.2, "evidence": "前置摸底"}},
            "skill_gaps": []}
    km1, gaps1, diff1 = apply_rules(base, "FANUC点位编程", is_correct=False)
    assert km1["FANUC点位编程"]["level"] < 0.5, km1
    assert km1["FANUC点位编程"]["confidence"] > 0.2, km1
    assert len(gaps1) == 1 and gaps1[0]["topic"] == "FANUC点位编程", gaps1
    print("答错后 level:", km1["FANUC点位编程"]["level"],
          "| confidence:", km1["FANUC点位编程"]["confidence"],
          "| gap priority:", gaps1[0]["priority"])

    print("== 纯规则自测：答对 → 掌握度上调 ==")
    km2, gaps2, diff2 = apply_rules(km1, "FANUC点位编程", is_correct=True)
    assert km2["FANUC点位编程"]["level"] > km1["FANUC点位编程"]["level"], km2
    print("答对后 level:", km2["FANUC点位编程"]["level"])

    # 2) 若可导入仓库 ProfileStore → 用临时库做端到端落库自测
    if ProfileStore is not None:
        import tempfile

        print("== 端到端自测：ProfileStore 临时库回写落库 ==")
        # 使用唯一临时目录中的自测库，避免覆盖既有文件；自测后由系统临时目录统一回收
        _tmp_dir = Path(tempfile.mkdtemp(prefix="k1_profile_selftest_"))
        tmp_db = _tmp_dir / "k1_selftest.db"
        store = ProfileStore(db_path=tmp_db)

        async def _demo() -> None:
            r1 = await update_learner_profile("stu_k1_001", "FANUC点位编程", False, store=store)
            r2 = await update_learner_profile("stu_k1_001", "FANUC点位编程", True, store=store)
            prof = await store.list_profiles(learner_id="stu_k1_001", limit=1)
            item = prof["items"][0]["profile"]
            self_km = item["knowledge_map"]["FANUC点位编程"]
            uses_repo_store = r1["profile_id"] == r2["profile_id"]
            print("两次回写同一快照:", uses_repo_store,
                  "| level:", self_km["level"],
                  "| confidence:", self_km["confidence"],
                  "| updated_at:", r2["updated_at"])
            assert r1["profile_id"] == r2["profile_id"]
            assert r1["level_after"] < r2["level_after"]

        asyncio.run(_demo())
    else:
        print("[跳过] 当前环境无法导入仓库 ProfileStore，仅完成纯规则自测。")

    print("\n全部自测通过")

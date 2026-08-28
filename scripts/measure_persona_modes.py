"""分模式实测「用户输入 → 人物画像」的五字段准确率（离线 demo + 在线真实 LLM）。

画像五字段：
  1. recommended_difficulty   —— 难度档位（既有金标）
  2. learning_style           —— 学习风格（既有金标）
  3. knowledge_map            —— 知识缺口图（本轮新增金标：主题掌握度 level）
  4. skill_gaps               —— 技能短板（本轮新增金标：主题 + 优先级）
  5. summary                  —— 用户总结（本轮新增金标：须自洽包含难度/风格关键事实）

区分两档：
  * raw   = LLM 层原始输出（demo 用 _infer_* 规则 / 真实用 DeepSeek），
            未经 _normalize_diagnosis 兜底
  * final = 经过 _normalize_diagnosis 确定性校正后的最终画像输出

金标：learner_profiles.json 的 expected_profile（外部预先定义，评测时禁止从
模型诊断输出回填，见 meta.truth_policy）。三字段金标由 topic_scores 确定性
推导（0-100 百分制 → level=score/100），见 scripts/build_persona_gold.py。

三字段口径：
  * knowledge_map：主题覆盖率（金标主题被命中的比例）+ level 命中率（命中主题中
    level 与金标一致的比例，两侧均已 round(2)）。
  * skill_gaps：短板召回率（金标短板主题被识别的比例）+ 优先级命中率 +
    误报率（1 - precision，识别出的短板中不在金标里的比例）。
  * summary：客观结论在场率（总结中含客观难度/风格规范值的比例，严格子串匹配；
    在线 LLM 散文用中文表述故 raw 低，_enforce_summary_evidence 兜底补入规范值后 final 应为 100%）。

Run:
    python scripts/measure_persona_modes.py [--demo-only]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.agents.diagnosis import DiagnosisAgent  # noqa: E402
from backend.src.llm.client import LLMClient, _lazy_load_openai_exceptions  # noqa: E402

TRUTH = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"


def load_profiles() -> list[dict[str, Any]]:
    doc = json.loads(TRUTH.read_text(encoding="utf-8"))
    return [dict(p) for p in doc.get("profiles", []) if isinstance(p, dict)]


def _make_demo_client() -> LLMClient:
    client = LLMClient.__new__(LLMClient)
    client._clients = {}
    client._is_demo = True
    _lazy_load_openai_exceptions()
    return client


def _eq(pred: Any, truth: str) -> bool:
    return isinstance(pred, str) and pred.strip().casefold() == truth.strip().casefold()


# ═══════════════════════════════════════════════════════════
# 三字段金标打分
# ═══════════════════════════════════════════════════════════


def _score_knowledge_map(pred: Any, gold: dict[str, float]) -> dict[str, Any]:
    pred = pred if isinstance(pred, dict) else {}
    entries = {str(k): v for k, v in pred.items() if isinstance(v, dict)}
    n = len(gold)
    matched = level_ok = 0
    for topic, gold_level in gold.items():
        key = topic if topic in entries else None
        if key is None:
            for candidate in entries:
                if DiagnosisAgent._match_topic(candidate, gold) == topic:
                    key = candidate
                    break
        if key is None:
            continue
        matched += 1
        try:
            pred_level = float(entries[key].get("level", 0.0))
        except (ValueError, TypeError):
            pred_level = 0.0
        if abs(pred_level - float(gold_level)) < 1e-9:
            level_ok += 1
    return {"matched": matched, "level_ok": level_ok, "n": n}


def _score_skill_gaps(pred: Any, gold: list[dict[str, str]]) -> dict[str, Any]:
    pred = pred if isinstance(pred, list) else []
    pred_items = [dict(g) for g in pred if isinstance(g, dict) and g.get("topic")]
    gold_by_topic = {g["topic"]: g["priority"] for g in gold}
    n = len(gold)
    recall = priority_ok = 0
    used: set[int] = set()
    for g in gold:
        topic = g["topic"]
        item: dict[str, Any] | None = None
        for i, p in enumerate(pred_items):
            if i in used:
                continue
            ptopic = str(p.get("topic", ""))
            if ptopic == topic or DiagnosisAgent._match_topic(ptopic, gold_by_topic) == topic:
                item = p
                used.add(i)
                break
        if item is None:
            continue
        recall += 1
        if str(item.get("priority", "")).strip().casefold() == g["priority"].casefold():
            priority_ok += 1
    precision = recall / len(pred_items) if pred_items else None
    return {
        "recall": recall,
        "priority_ok": priority_ok,
        "n": n,
        "precision": precision,
        "pred_n": len(pred_items),
    }


def _score_summary(pred: Any, gold: dict[str, str]) -> dict[str, Any]:
    text = str(pred or "").casefold()
    d = str(gold.get("must_include_difficulty") or "").casefold()
    s = str(gold.get("must_include_style") or "").casefold()
    return {"difficulty_ok": bool(d) and d in text, "style_ok": bool(s) and s in text}


# ═══════════════════════════════════════════════════════════
# 采样：demo / 真实
# ═══════════════════════════════════════════════════════════


def _row(p: dict[str, Any], raw: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    exp = p["expected_profile"]
    return {
        "id": p["id"],
        "true_diff": exp.get("expected_difficulty"),
        "true_style": exp.get("expected_learning_style"),
        "raw": raw,
        "final": final,
        "raw_diff": raw.get("recommended_difficulty"),
        "raw_style": raw.get("learning_style"),
        "final_diff": final.get("recommended_difficulty"),
        "final_style": final.get("learning_style"),
        "gold_km": exp.get("expected_knowledge_map") or {},
        "gold_gaps": exp.get("expected_skill_gaps") or [],
        "gold_summary": exp.get("expected_summary") or {},
    }


async def _measure_real(
    agent: DiagnosisAgent, profiles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in profiles:
        learner = p["input"]
        raw = await agent.call_llm_json(agent._build_prompt(learner))
        final = agent._normalize_diagnosis(dict(raw), learner)
        rows.append(_row(p, dict(raw), final))
    return rows


def _measure_demo(
    agent: DiagnosisAgent, client: LLMClient, profiles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in profiles:
        learner = p["input"]
        raw = json.loads(client._demo_diagnosis(agent.system_prompt, agent._build_prompt(learner)))
        final = agent._normalize_diagnosis(dict(raw), learner)
        rows.append(_row(p, dict(raw), final))
    return rows


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════


def _agg_fields(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """对某一档（raw/final）汇总三字段准确率（micro 平均）。"""
    km_n = km_matched = km_level = 0
    gap_n = gap_recall = gap_priority = 0
    gap_pred_n = 0
    sum_d = sum_s = 0
    total = len(rows)
    for r in rows:
        km = _score_knowledge_map(r[mode].get("knowledge_map"), r["gold_km"])
        km_n += km["n"]
        km_matched += km["matched"]
        km_level += km["level_ok"]

        sg = _score_skill_gaps(r[mode].get("skill_gaps"), r["gold_gaps"])
        gap_n += sg["n"]
        gap_recall += sg["recall"]
        gap_priority += sg["priority_ok"]
        gap_pred_n += sg["pred_n"]

        ss = _score_summary(r[mode].get("summary"), r["gold_summary"])
        sum_d += 1 if ss["difficulty_ok"] else 0
        sum_s += 1 if ss["style_ok"] else 0

    return {
        "km_coverage": km_matched / km_n if km_n else None,
        "km_level": km_level / km_n if km_n else None,
        "gap_recall": gap_recall / gap_n if gap_n else None,
        "gap_priority": gap_priority / gap_n if gap_n else None,
        "gap_fpr": (1 - gap_recall / gap_pred_n) if gap_pred_n else None,
        "summary_difficulty": sum_d / total if total else None,
        "summary_style": sum_s / total if total else None,
        "gap_gold_n": gap_n,
        "gap_pred_n": gap_pred_n,
    }


def _summarize(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)

    def rate(field: str, truth: str) -> float | None:
        if not n:
            return None
        return sum(1 for r in rows if _eq(r[field], r[truth])) / n

    return {
        "label": label,
        "raw_diff": rate("raw_diff", "true_diff"),
        "raw_style": rate("raw_style", "true_style"),
        "final_diff": rate("final_diff", "true_diff"),
        "final_style": rate("final_style", "true_style"),
        "raw": _agg_fields(rows, "raw"),
        "final": _agg_fields(rows, "final"),
    }


def _pct(v: float | None) -> str:
    return "N/A" if v is None else f"{v:.0%}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-only", action="store_true")
    args = parser.parse_args()

    profiles = load_profiles()
    agent = DiagnosisAgent()

    summaries: list[dict[str, Any]] = []

    demo_client = _make_demo_client()
    demo_rows = _measure_demo(agent, demo_client, profiles)
    summaries.append(_summarize("离线 demo", demo_rows))

    if not args.demo_only:
        real_rows = asyncio.run(_measure_real(agent, profiles))
        summaries.append(_summarize("在线 真实API", real_rows))
    else:
        real_rows = None

    print("===== 人物画像步骤 · 分模式实测（难度 / 学习风格 vs 金标） =====")
    print()
    header = f"{'画像':<24} {'真值难度':<12} {'真值风格':<16} | "
    if real_rows is not None:
        header += f"{'在线raw':<28} {'在线final':<28} | "
    header += f"{'离线raw':<28} {'离线final':<28}"
    print(header)
    print("-" * len(header))
    for i, p in enumerate(profiles):
        dr = demo_rows[i]
        row = f"{p['id']:<24} {str(dr['true_diff']):<12} {str(dr['true_style']):<16} | "
        if real_rows is not None:
            rr = real_rows[i]
            row += f"{rr['raw_diff']}/{rr['raw_style']}".ljust(28)
            row += f"{rr['final_diff']}/{rr['final_style']}".ljust(28)
            row += " | "
        else:
            row += f"{'':<28} {'':<28} | "
        row += f"{dr['raw_diff']}/{dr['raw_style']}".ljust(28)
        row += f"{dr['final_diff']}/{dr['final_style']}".ljust(28)
        print(row)
    print()

    print("【汇总：难度 / 学习风格 准确率 vs 金标】")
    for s in summaries:
        print(f"  {s['label']}:")
        print(f"    难度 raw={_pct(s['raw_diff'])}  final={_pct(s['final_diff'])}")
        print(f"    风格 raw={_pct(s['raw_style'])}  final={_pct(s['final_style'])}")
    print()

    print("【汇总：knowledge_map / skill_gaps / summary 准确率 vs 金标】")
    print("  口径：")
    print("    knowledge_map 覆盖率=金标主题命中比例；level命中=命中主题中 level 一致比例")
    print(
        "    skill_gaps 召回=金标短板识别比例；优先级命中=识别到且优先级一致比例；"
        "误报=识别出的短板中不在金标里的比例"
    )
    print("    summary 客观结论在场=总结含客观难度+风格规范值的比例（严格子串匹配）")
    print()
    for s in summaries:
        raw_, final_ = s["raw"], s["final"]
        print(f"  {s['label']}:")
        print(
            "    knowledge_map: "
            f"覆盖率 raw={_pct(raw_['km_coverage'])} final={_pct(final_['km_coverage'])}"
            f" | level命中 raw={_pct(raw_['km_level'])} final={_pct(final_['km_level'])}"
        )
        print(
            "    skill_gaps: "
            f"召回 raw={_pct(raw_['gap_recall'])} final={_pct(final_['gap_recall'])}"
            f" | 优先级 raw={_pct(raw_['gap_priority'])} final={_pct(final_['gap_priority'])}"
            f" | 误报率 raw={_pct(raw_['gap_fpr'])} final={_pct(final_['gap_fpr'])}"
        )
        print(
            "    summary: "
            f"难度事实 raw={_pct(raw_['summary_difficulty'])} "
            f"final={_pct(final_['summary_difficulty'])}"
            f" | 风格事实 raw={_pct(raw_['summary_style'])} "
            f"final={_pct(final_['summary_style'])}"
        )
    print()
    print(
        "  注：skill_gaps 误报率中，专家画像（如 profile-j）无客观短板（金标 gaps=0），"
        "兜底会补一条「相对最薄弱」低优先条目，属系统性误报，计入该栏。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""从 topic_scores 确定性推导「画像三字段」外部金标并落盘到 learner_profiles.json。

金标推导规则（落盘后见 learner_profiles.json 的 meta.gold_derivation）：
  * expected_knowledge_map[topic] = round(topic_score / 100, 2)
      —— topic_scores 为 0-100 百分制掌握度（backend/src/evaluation/pretest.py
         score_pretest 定义），知识点掌握度 level = topic_score / 100。
  * expected_skill_gaps = [ {topic, priority} for topic with level < 0.65 ]
      —— 优先级按得分率定档：<0.30 critical / <0.50 high / 其余 medium。
         全主题 ≥0.65 时 expected_skill_gaps 为空数组（无客观短板）。
  * expected_summary = { must_include_difficulty, must_include_style }
      —— 总结须自洽地包含客观难度与学习风格两个关键事实。

本脚本只在金标需要（重新）生成时运行；评测脚本只读 learner_profiles.json，
不调用本脚本，也不从模型诊断输出回填（对齐 meta.truth_policy）。

Run:
    python scripts/build_persona_gold.py
"""

from __future__ import annotations

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
TRUTH = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"

_TOPIC_SCALE = 100.0
_WEAK_THRESHOLD = 0.65
_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2}

GOLD_DERIVATION = {
    "knowledge_map": (
        "topic_scores 为 0-100 百分制掌握度（backend/src/evaluation/pretest.py "
        "score_pretest 定义），知识点掌握度 level = topic_score / 100，四舍五入 2 位。"
    ),
    "skill_gaps": (
        "level < 0.65 的主题即知识短板；优先级按得分率定档：<0.30 critical / "
        "<0.50 high / 其余 medium；全主题 ≥0.65 时 expected_skill_gaps 为空数组。"
    ),
    "summary": (
        "总结须自洽地包含客观难度与学习风格两个关键事实（must_include_*），不得与前置测试证据冲突。"
    ),
}


def _priority(level: float) -> str:
    if level < 0.30:
        return "critical"
    if level < 0.50:
        return "high"
    return "medium"


def _extract_topic_scores(profile: dict[str, Any]) -> dict[str, float]:
    """取首个含非空 topic_scores 的前置测试（与 DiagnosisAgent 对齐）。"""
    for pretest in profile.get("input", {}).get("pretest_results", []):
        if not isinstance(pretest, dict):
            continue
        scores = pretest.get("topic_scores") or {}
        if isinstance(scores, dict) and scores:
            return {str(k): float(v) for k, v in scores.items()}
    return {}


def build_gold(profile: dict[str, Any]) -> dict[str, Any]:
    """返回要并入 expected_profile 的三个金标字段。"""
    topic_scores = _extract_topic_scores(profile)
    knowledge_map = {topic: round(score / _TOPIC_SCALE, 2) for topic, score in topic_scores.items()}
    gaps = [
        {"topic": topic, "priority": _priority(level)}
        for topic, level in knowledge_map.items()
        if level < _WEAK_THRESHOLD
    ]
    # 规范排序：优先级 → 掌握度升序 → 主题名，保证可读且确定性
    gaps.sort(key=lambda g: (_PRIORITY_RANK[g["priority"]], knowledge_map[g["topic"]], g["topic"]))

    expected = profile.get("expected_profile", {})
    return {
        "expected_knowledge_map": knowledge_map,
        "expected_skill_gaps": gaps,
        "expected_summary": {
            "must_include_difficulty": expected.get("expected_difficulty"),
            "must_include_style": expected.get("expected_learning_style"),
        },
    }


def main() -> int:
    doc = json.loads(TRUTH.read_text(encoding="utf-8"))
    profiles = doc.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError(f"{TRUTH} 缺少 profiles 列表")

    doc.setdefault("meta", {})["version"] = "4.0"
    doc["meta"]["gold_derivation"] = GOLD_DERIVATION

    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        expected = profile.setdefault("expected_profile", {})
        expected.update(build_gold(profile))

    TRUTH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已更新 {len(profiles)} 个画像的三字段金标 → {TRUTH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

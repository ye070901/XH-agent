"""分层采样：从 420 正例按 profile × domain 分层抽「全局幻觉率」样本。

口径：eval（模型原生能力）+ 分层采样。
- 分层维度一：10 个 learner profile（全覆盖，画像多样性 → 难度/风格差异）
- 分层维度二：11 个 counted 领域 K1..K11（全覆盖，内容多样性）
- 每领域取 1 个知识点（core/high 大致 1:1 平衡），× 10 profile = 110 正例
- 附加 4 个负例（负样本评估单独计，不计入幻觉率分母）

用途：输出 case-id 清单，供 collect_phase3_outputs.py --case-id 消费。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = REPO_ROOT / "data" / "evaluation" / "phase3_test_cases.json"
OUT = REPO_ROOT / "data" / "evaluation" / "runs" / "stratified_sample_ids.json"

# 每领域 1 个代表点，core/high 平衡（5 core + 6 high，接近 21:21 的 1:1）
# K11 仅有 high，故 K11 取 high。
SELECTED_POINTS = [
    "K1-CORE-001",  # core  工业机器人基础安全与急停
    "K2-HIGH-004",  # high  KUKA KRL 离线仿真
    "K3-CORE-001",  # core  SRVO-068 数据传输故障诊断
    "K4-HIGH-004",  # high  逆运动学
    "K5-CORE-001",  # core  2D/3D 视觉系统与相机选型
    "K6-HIGH-002",  # high  拖动示教与力控制
    "K7-CORE-001",  # core  PROFINET 设备调试
    "K8-HIGH-002",  # high  上下料单元部署
    "K9-CORE-001",  # core  弧焊工艺
    "K10-HIGH-002",  # high KUKA 安全功能
    "K11-HIGH-001",  # high 动力学建模（K11 无 core）
]


def main() -> int:
    cases = json.load(open(CASES, encoding="utf-8"))["cases"]
    pos = [c for c in cases if c.get("kind") == "positive"]
    neg = [c for c in cases if c.get("kind") == "negative"]

    profile_nn: dict[str, str] = {}
    for c in pos:
        profile_nn.setdefault(c["profile_id"], c["id"].split("-")[1])

    selected = set(SELECTED_POINTS)
    picked = [c["id"] for c in pos if c.get("knowledge_point_id") in selected]
    neg_ids = [c["id"] for c in neg]

    expected = len(SELECTED_POINTS) * len(profile_nn)
    if len(picked) != expected:
        print(f"ERROR: 期望 {expected} 正例，实际 {len(picked)}")
        return 1

    result = {
        "meta": {
            "name": "分层采样（eval 全局幻觉率）",
            "strategy": "10 profile × 11 counted domain × 1 知识点 + 4 负例",
            "core_high_balance": "5 core + 6 high",
            "selected_points": SELECTED_POINTS,
            "positive_count": len(picked),
            "negative_count": len(neg_ids),
            "profile_count": len(profile_nn),
        },
        "positive_case_ids": picked,
        "negative_case_ids": neg_ids,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"正例 {len(picked)} / 负例 {len(neg_ids)} / profile {len(profile_nn)}")
    print(f"保存到 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

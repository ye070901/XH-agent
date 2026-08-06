"""Day 3 联调脚本：InputGate check -> Agent1 mock -> DiagnosisGate check

三环节串行执行，验证闸门与 mock Agent 的数据流通。

Run:
    python scripts/test_day3_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from backend.src.quality_gate.gates.input_gate import InputGate
from backend.src.schemas import GateVerdict


# ============================================================
# Agent1 mock
# ============================================================


def mock_agent1_diagnosis(state: dict) -> dict:
    """模拟 Agent1 输出正常的 diagnosis_result。"""
    state["diagnosis_result"] = {
        "knowledge_map": {
            "FANUC - 基础操作": {"level": 0.8, "confidence": 0.9},
            "FANUC - 示教器编程": {"level": 0.6, "confidence": 0.7},
            "FANUC - 安全规范": {"level": 0.9, "confidence": 0.95},
            "FANUC - IO 配置": {"level": 0.4, "confidence": 0.6},
            "FANUC - 运动指令": {"level": 0.5, "confidence": 0.65},
        },
        "skill_gaps": [
            {
                "topic": "工具坐标系标定",
                "current_level": 0.2,
                "target_level": 0.8,
                "priority": "high",
                "reason": "缺少实操经验",
            }
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "intermediate",
        "overall_confidence": 0.76,
        "summary": "该学习者有基础操作经验，但缺少坐标系标定实操。",
    }
    return state


# ============================================================
# 主流程
# ============================================================


async def main():
    print("=" * 60)
    print("  Day 3: InputGate -> Agent1(mock) -> DiagnosisGate")
    print("=" * 60)

    state: dict = {
        "learner_data": {
            "learning_goal": "FANUC 机器人 SRVO-068 故障怎么处理",
            "major": "自动化",
            "industry": "汽车制造",
            "positions": ["机器人调试员"],
            "skills_used": ["FANUC 示教器"],
        },
        "agent_log": [],
        "gate_results": {},
    }

    # ---- [1/3] InputGate ----
    print("\n[1/3] InputGate check...")
    input_gate = InputGate()
    state = await input_gate.validate(state)
    input_result = state["gate_results"][InputGate.GATE_NAME]

    if not input_result.get("passed"):
        print(f"  [FAIL] InputGate blocked: {input_result.get('violations', [])}")
        return 1
    print(f"  [OK] InputGate passed | intent={input_result['details'].get('intent')}")

    # ---- [2/3] Agent1 mock ----
    print("\n[2/3] Agent1 (mock) diagnosis...")
    state = mock_agent1_diagnosis(state)
    diag = state.get("diagnosis_result", {})
    print(f"  [OK] Diagnosis done | confidence={diag.get('overall_confidence')} "
          f"| difficulty={diag.get('recommended_difficulty')} "
          f"| gaps={len(diag.get('skill_gaps', []))}")

    # ---- [3/3] DiagnosisGate ----
    print("\n[3/3] DiagnosisGate check...")
    diag_gate = DiagnosisGate()
    state = await diag_gate.validate(state)
    result = state["gate_results"][DiagnosisGate.GATE_NAME]
    verdict = result.get("verdict", "?")

    if verdict == GateVerdict.PASS.value:
        print(f"  [OK] DiagnosisGate PASS | score={result.get('score')}")
    elif verdict == GateVerdict.RETRY.value:
        print(f"  [RETRY] DiagnosisGate | hint={result.get('retry_hint', '')[:120]}")
    elif verdict == GateVerdict.FALLBACK.value:
        fb = result.get("fallback_data", {})
        print(f"  [FALLBACK] DiagnosisGate | default_level={fb.get('recommended_difficulty')}")
    else:
        print(f"  [?] Unknown verdict: {verdict}")

    # ---- 终判 ----
    print("\n" + "=" * 60)
    if verdict == GateVerdict.PASS.value:
        print("  Day 3 Pipeline: PASS (联调通过)")
    else:
        print(f"  Day 3 Pipeline: done (verdict={verdict})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

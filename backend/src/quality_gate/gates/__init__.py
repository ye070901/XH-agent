"""三道质量闸门实现。

闸门1（输入特异性检测）：纯规则，不调用 LLM
闸门2（学情诊断质量）：三路裁决 PASS / RETRY / FALLBACK
闸门3（RAG 召回质量）：三路裁决 PASS / RETRY / FALLBACK

旧版闸门（硬规则 + LLM 复核模型）已归档：
  - diagnosis_gate_old.py
  - recall_gate_old.py
"""

from backend.src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from backend.src.quality_gate.gates.input_gate import InputGate
from backend.src.quality_gate.gates.recall_gate import RecallGate

__all__ = ["InputGate", "DiagnosisGate", "RecallGate"]

# Agent 4 双入口：correction.py（主实现）+ agent4.py（标准入口）
from .agent4 import CorrectionAgent as CorrectionAgentV4  # noqa: F401
from .audit import AuditAgent
from .base import BaseAgent
from .correction import CorrectionAgent
from .diagnosis import DiagnosisAgent
from .generation import GenerationAgent
from .generation_v2 import GenerationAgent as GenerationAgentV2

__all__ = [
    "BaseAgent",
    "DiagnosisAgent",
    "GenerationAgent",
    "GenerationAgentV2",
    "AuditAgent",
    "CorrectionAgent",
    "CorrectionAgentV4",
]

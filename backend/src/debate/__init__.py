"""博弈引擎包 — 纯规则裁决，禁止调用 LLM。

对外暴露：
  - DebateEngine / debate_engine  博弈引擎主逻辑与全局单例
  - rules                         裁决规则纯代码模块
"""

from . import rules
from .engine import DebateEngine, debate_engine

__all__ = ["DebateEngine", "debate_engine", "rules"]

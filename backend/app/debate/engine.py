"""辩论与交叉验证引擎 — 生成Agent与审核Agent的多轮博弈"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import json
from typing import Optional
from loguru import logger

from ..core.config import settings


class DebateEngine:
    """辩论引擎：当审核Agent发现问题时，组织多轮辩论"""

    def __init__(self):
        self.max_rounds = settings.DEBATE_MAX_ROUNDS

    def run_debate(
        self,
        resource: dict,
        audit_report: dict,
        knowledge_chunks: list,
    ) -> dict:
        """执行多轮辩论，返回最终裁决"""
        verdict = audit_report.get("verdict", "approved")
        if verdict == "approved":
            logger.info("[辩论引擎] 审核通过，无需辩论")
            return {
                "debate_needed": False,
                "final_verdict": "approved",
                "rounds": [],
                "final_resource": resource,
                "resolution": "审核Agent直接通过",
            }

        logger.info(f"[辩论引擎] 审核意见: {verdict}，启动辩论")
        rounds = []

        for round_num in range(1, self.max_rounds + 1):
            logger.info(f"[辩论引擎] 第{round_num}轮辩论")

            # 模拟辩论过程（实际生产环境会调用LLM）
            defense = self._generate_defense(resource, audit_report, knowledge_chunks)
            review = self._review_again(audit_report, knowledge_chunks)
            arbitration = self._arbitrate(resource, audit_report, knowledge_chunks)

            rounds.append({
                "round_number": round_num,
                "defense": defense,
                "review": review,
                "arbitration": arbitration,
            })

            if arbitration.get("consensus_reached"):
                logger.info(f"[辩论引擎] 第{round_num}轮达成共识")
                return {
                    "debate_needed": True,
                    "final_verdict": arbitration.get("final_verdict", "approved"),
                    "rounds": rounds,
                    "final_resource": resource,
                    "resolution": arbitration.get("resolution", ""),
                }

        # 达到最大轮数仍未共识
        logger.warning(f"[辩论引擎] {self.max_rounds}轮未达成共识，标注存疑")
        return {
            "debate_needed": True,
            "final_verdict": "uncertain",
            "rounds": rounds,
            "final_resource": resource,
            "resolution": f"经{self.max_rounds}轮辩论未达成共识，建议人工审核",
        }

    def _generate_defense(self, resource: dict, audit: dict, chunks: list) -> str:
        """生成Agent的辩护"""
        flags = audit.get("hallucination_flags", [])
        if not flags:
            return "审核Agent未标注具体幻觉问题"
        # 检查知识库是否有证据
        for flag in flags:
            location = flag.get("location", "")
            for chunk in chunks:
                if any(kw in chunk.get("content", "") for kw in location.split()):
                    return f"知识库有证据支持: {chunk.get('content', '')[:200]}"
        return "知识库未找到直接证据，但基于行业通用规范，内容合理"

    def _review_again(self, audit: dict, chunks: list) -> str:
        """审核Agent复审"""
        flags = audit.get("hallucination_flags", [])
        if not flags:
            return "无争议项"
        resolved = len([f for f in flags if f.get("severity") == "minor"])
        total = len(flags)
        return f"复审: {resolved}/{total}个问题已解决"

    def _arbitrate(self, resource: dict, audit: dict, chunks: list) -> dict:
        """仲裁裁决 — 以知识库原文为标准"""
        flags = audit.get("hallucination_flags", [])
        if not flags:
            return {"consensus_reached": True, "final_verdict": "approved", "resolution": "无争议"}

        unresolved = []
        for flag in flags:
            location = flag.get("location", "")
            found = False
            for chunk in chunks:
                if any(kw in chunk.get("content", "") for kw in location.split()):
                    found = True
                    # 知识库有支持 → 审核方的质疑不成立
                    break
            if not found:
                unresolved.append(flag)

        if not unresolved:
            return {
                "consensus_reached": True,
                "final_verdict": "approved",
                "resolution": "全部争议已解决",
            }
        elif len(unresolved) == 1 and unresolved[0].get("severity") == "minor":
            return {
                "consensus_reached": True,
                "final_verdict": "approved",
                "resolution": "剩余1个minor问题，不阻碍通过",
            }
        else:
            return {
                "consensus_reached": False,
                "final_verdict": "needs_revision",
                "resolution": f"仍有{len(unresolved)}个争议未解决",
            }

    def process(self, state: dict) -> dict:
        """兼容LangGraph节点调用"""
        resource = state.get("generated_resource", {})
        audit = state.get("audit_report", {})
        chunks = state.get("retrieved_chunks", [])
        return self.run_debate(resource, audit, chunks)

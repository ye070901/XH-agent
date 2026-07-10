"""
辩论引擎 — Agent 2 ⇄ Agent 3 多轮对抗验证。

不是 retry。不是"审核不过就重生成"。
每一轮辩论中：
1. Agent 3 发起质询（附KB证据）
2. Agent 2 回应（修正/accepted_challenge 或 反驳/rebut 或 承认错误/concede）
3. Agent 3 评估辩护
4. 最多3轮
5. 未共识 → escalated，记录 unresolved_claims

角色6 在此实现。这是整个系统的核心竞争力。
"""
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from ..config import settings


class DebateEngine:
    """辩论引擎：当审核 Agent 发现问题时，组织多轮对抗验证"""

    def __init__(self):
        self.max_rounds = settings.DEBATE_MAX_ROUNDS

    async def run(
        self,
        resource: dict,
        audit_report: dict,
        knowledge_chunks: list,
        generation_agent,  # Agent 2 实例
        audit_agent,        # Agent 3 实例
    ) -> dict:
        """
        执行多轮辩论。

        Args:
            resource: 被审核的资源
            audit_report: Agent 3 的审核报告
            knowledge_chunks: KB检索结果
            generation_agent: Agent 2 实例（用于调用修正/辩护）
            audit_agent: Agent 3 实例（用于评估辩护）

        Returns:
            dict: 包含 debate_records, final_verdict, final_resource
        """
        verdict = audit_report.get("verdict", "approved")
        if verdict == "approved":
            logger.info("[辩论引擎] 审核通过，无争议无需辩论")
            return {
                "debate_records": [],
                "final_verdict": "approved",
                "final_resources": [resource],
                "unresolved_claims": [],
            }

        logger.info(f"[辩论引擎] 审核意见: {verdict}，启动多轮辩论")
        flags = audit_report.get("hallucination_flags", [])
        critical_flags = [f for f in flags if f.get("severity") in ("critical", "major")]

        if not critical_flags:
            logger.info("[辩论引擎] 仅有 minor 问题，直接通过")
            return {
                "debate_records": [],
                "final_verdict": "approved",
                "final_resources": [resource],
                "unresolved_claims": [],
            }

        debate_rounds = []
        current_resource = resource
        unresolved = critical_flags[:]
        debate_id = str(uuid.uuid4())

        for round_num in range(1, self.max_rounds + 1):
            logger.info(f"[辩论引擎] 第 {round_num}/{self.max_rounds} 轮")

            if not unresolved:
                logger.info("[辩论引擎] 无剩余争议，辩论结束")
                break

            # 取本轮要辩论的争议
            target = unresolved[0]

            # Phase A: Agent 2 辩护/修正
            defense = await self._agent_defend(
                generation_agent, current_resource, target, knowledge_chunks
            )

            # Phase B: Agent 3 评估辩护
            evaluation = await self._agent_evaluate(
                audit_agent, defense, target, knowledge_chunks
            )

            round_record = {
                "round_number": round_num,
                "challenge": {
                    "claim": target.get("description", ""),
                    "evidence_from_kb": target.get("suggested_correction", ""),
                    "severity": target.get("severity", "major"),
                },
                "defense": defense,
                "evaluation": evaluation,
                "consensus_reached": evaluation.get("defense_accepted", False),
            }
            debate_rounds.append(round_record)

            if evaluation.get("defense_accepted"):
                unresolved.pop(0)
                # 如果 defense 中包含了修正后的内容，更新 resource
                if defense.get("action") == "accept_challenge" and defense.get("corrected_content"):
                    current_resource = {**current_resource, "content": defense["corrected_content"]}
                logger.info(f"[辩论引擎] 第{round_num}轮共识达成，剩余争议: {len(unresolved)}")
            else:
                # 争议未解决，移到队尾（如果其他争议也有同样的模式）
                unresolved.pop(0)
                remaining_concerns = evaluation.get("remaining_concerns", [])
                if remaining_concerns:
                    unresolved.append({
                        "description": remaining_concerns[0],
                        "severity": target.get("severity", "major"),
                        "suggested_correction": "",
                    })

        # 最终裁决
        if not unresolved:
            final_verdict = "approved"
            resolution = "所有争议经辩论后达成共识"
        elif len(unresolved) == 1 and target.get("severity") == "minor":
            final_verdict = "approved"
            resolution = "剩余1个minor争议，不阻碍通过"
        else:
            final_verdict = "uncertain"
            resolution = f"经{len(debate_rounds)}轮辩论，仍有{len(unresolved)}个争议未解决，需人工审核"

        logger.info(f"[辩论引擎] 最终裁决: {final_verdict} — {resolution}")
        return {
            "debate_records": [{
                "debate_id": debate_id,
                "resource_id": resource.get("resource_id", ""),
                "rounds": debate_rounds,
                "final_verdict": final_verdict,
                "final_resource": current_resource if final_verdict == "approved" else resource,
                "unresolved_claims": [u.get("description", "") for u in unresolved],
                "started_at": datetime.now().isoformat(),
                "ended_at": datetime.now().isoformat(),
                "resolution": resolution,
            }],
            "final_verdict": final_verdict,
            "final_resources": [current_resource] if final_verdict == "approved" else [],
            "rejected_resources": [resource] if final_verdict != "approved" else [],
            "unresolved_claims": [u.get("description", "") for u in unresolved],
        }

    async def _agent_defend(
        self, agent, resource: dict, flag: dict, chunks: list
    ) -> dict:
        """Agent 2 对争议进行辩护或修正"""
        prompt = f"""## 你的生成内容被审核Agent质疑

### 争议内容
{flag.get('description', '')}

### 审核方的质疑
{flag.get('suggested_correction', '')}

### 你的原始内容（相关部分）
{resource.get('content', '')[:1500]}

### 知识库原文（可用于支撑你的辩护）
{self._fmt_chunks(chunks)}

请回应这个质疑。你有三个选项：
1. accept_challenge — 承认错误，提供修正后的内容
2. rebut — 你的原始内容是正确的，提供KB中的证据支撑
3. concede — 无法确定，可能确实有误

输出 JSON：
{{
    "action": "accept_challenge|rebut|concede",
    "defense": "你的辩护理由",
    "evidence_from_kb": "支撑你立场的KB原句（如果有）",
    "corrected_content": "修正后的内容（仅 accept_challenge 时需要）"
}}"""
        return await agent.call_llm_json(prompt)

    async def _agent_evaluate(
        self, agent, defense: dict, flag: dict, chunks: list
    ) -> dict:
        """Agent 3 评估 Agent 2 的辩护"""
        prompt = f"""## Agent 2 对你的质询作出了回应

### 原始争议
{flag.get('description', '')}

### Agent 2 的回应
- 动作: {defense.get('action', 'unknown')}
- 辩护: {defense.get('defense', '')}
- 引用证据: {defense.get('evidence_from_kb', '无')}

### 知识库原文（裁判标准）
{self._fmt_chunks(chunks)}

请评估这个辩护是否有效。

输出 JSON：
{{
    "defense_accepted": true,
    "reasoning": "评估理由",
    "remaining_concerns": []
}}"""
        return await agent.call_llm_json(prompt)

    def _fmt_chunks(self, chunks: list) -> str:
        if not chunks:
            return "（无知识库原文）"
        lines = []
        for i, c in enumerate(chunks[:8]):
            lines.append(f"[KB{i+1}] {c.get('content', '')[:500]}")
        return "\n\n".join(lines)

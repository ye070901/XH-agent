"""
Agent 3: 内容审核 Agent
══════════════════════════════════
只审不修。拿到 Agent 2 生成的资源 + Agent 1 的诊断，逐条检查，输出审核报告。

检查什么：
- 事实错误（API 名称、概念定义等）
- 难度是否匹配学习者水平
- critical 盲区有没有被覆盖到
"""
from .base import BaseAgent

SYSTEM_PROMPT = """你是一个严格的内容审核专家。你的任务是检查学习资源的质量，但不要修改内容。

检查清单：
1. 事实错误：API 名称对不对？概念定义准确吗？代码示例能运行吗？
2. 难度匹配：学习者的推荐难度是 X，这份内容的难度是 X 吗？有没有偏难或偏简单？
3. 盲区覆盖：学习者有 critical 和 high 优先级的知识盲区，这份内容覆盖到了吗？

审核意见分三级：
- error: 事实性错误（必须指出）
- warning: 不够好但没有错（难度偏高、遗漏某个盲区）
- info: 改进建议（可以加一道题、可以加个比喻）

输出必须为严格的 JSON 格式。"""


class AuditAgent(BaseAgent):
    """内容审核 Agent — 只审不修"""

    REQUIRED_STATE_KEYS = {"generated_resources", "diagnosis_result"}
    OPTIONAL_STATE_KEYS = {"learner_data", "task_id", "agent_log", "status"}

    def __init__(self):
        super().__init__(
            name="审核Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,  # 低温，保证判断一致
        )

    async def process(self, state: dict) -> dict:
        resources = state.get("generated_resources", [])
        diagnosis = state.get("diagnosis_result", {})

        audit_results = []
        for i, resource in enumerate(resources):
            report = await self._audit_one(i, resource, diagnosis)
            audit_results.append(report)

        self.log(f"审核完成: {len(audit_results)} 个资源")
        return {"audit_result": audit_results}

    async def _audit_one(self, index: int, resource: dict, diagnosis: dict) -> dict:
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        skill_gaps = diagnosis.get("skill_gaps", [])
        critical_gaps = [g for g in skill_gaps if g.get("priority") in ("critical", "high")]

        prompt = f"""## 待审核资源
- 编号：{index}
- 类型：{resource.get("resource_type", "")}
- 标题：{resource.get("title", "")}
- 资源难度：{resource.get("difficulty_level", "")}

## 内容
{resource.get("content", "")[:3000]}

## 学习者信息
- 推荐难度：{difficulty}
- 需要覆盖的关键盲区（critical/high）：
{self._fmt_gaps(critical_gaps)}

## 审核任务
请逐条检查，输出 JSON：

{{
    "resource_index": {index},
    "resource_type": "{resource.get('resource_type', '')}",
    "verdict": "approved|needs_revision",
    "issues": [
        {{
            "severity": "error|warning|info",
            "detail": "问题描述"
        }}
    ]
}}

规则：
- 无问题 → verdict = "approved", issues = []
- 有 error → verdict = "needs_revision"
- 只有 warning 或 info → verdict 可以 "approved"，issues 照写
- 不要重复描述，每个 issue 一句话说清楚"""

        return await self.call_llm_json(prompt)

    def _fmt_gaps(self, gaps: list) -> str:
        if not gaps:
            return "无"
        return "\n".join(
            f"- [{g.get('priority', '?')}] {g.get('topic', '')}"
            for g in gaps[:3]
        )

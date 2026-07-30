"""
Agent 4: 保真修正 Agent
══════════════════════════════════
负责: 人员3 实现（与 Agent 2 同一开发者，prompt 风格统一）

输入: state["generated_resources"] + state["audit_result"]
      + state["diagnosis_result"] + state["retrieved_chunks"]
输出: state["corrected_resources"] + state["correction_log"] + state["correction_stats"]

修正策略:
  - error   → 必须修正（查 KB 原文替换错误断言）
  - warning → 尽量修正（调整解释深度、难度匹配、遗漏覆盖）
  - info    → 可选修正（改进建议酌情采纳）

关键约束:
  1. 只改有问题的部分，不重写整个资源
  2. 修改后重新标注来源 [来源: {doc_id}]
  3. KB 冲突内容并列展示，不自动选边
  4. 修正后不引入新的事实断言（无 KB 支撑标注 [暂无权威参考]）
  5. downgrade_mode=True 时只做一致性修正，不做事实判断
"""

from __future__ import annotations

import time
import uuid

from .base import BaseAgent

SYSTEM_PROMPT = """你是一个严格的内容修正专家。你的任务是：
1. 根据审核报告（audit_result）中标记的问题，逐条修正学习资源中的错误
2. 知识库原文（retrieved_chunks）是你的"真理基准"——事实修正必须以 KB 原文为准
3. 修正后不能引入新的事实断言，无 KB 支撑的技术细节标注 [暂无权威参考，建议补充学习]

修正策略（按 severity 分级）：
- error（事实错误）：必须修正。查 KB 找到正确表述，直接替换错误内容。
- warning（不够好但没大错）：尽量修正。调整解释深度、补充缺失细节、对齐难度。
- info（改进建议）：酌情采纳。不影响准确性 → 采纳；会引入新断言 → 跳过。

关键规则：
1. **只改有问题的部分**：保留原内容中正确的段落、代码、示例。
2. **修改后重新标注来源**：涉及事实修改的段落，标注 [来源: {doc_id}, 段落 {chunk_idx}]。
3. **KB 冲突内容并列**：同一主题 KB 中存在多个说法时，用 "说法A: ... / 说法B: ..." 并列呈现。
4. **不引入新事实断言**：修正完成后额外检查——是否有 KB 未覆盖的新技术声明？有则删除或标注。
5. **降级模式**：如果 KB 素材为空或覆盖不足，只做一致性修正
   （自相矛盾、概念混用等），不要凭空判断对错。
6. **溯源意识**：每条技术断言、代码示例的核心逻辑、概念定义，必须能从 KB 中找到对应原文。
7. **内容结构保持**：修正后的资源保持原资源类型对应的内容结构：
   - lecture: 引言 → 3~4小节 → 总结
   - guide: 概述 → 前置准备 → 分步操作 → 常见问题
   - quiz: 基础选择题×2 → 进阶题×1 → 挑战实操题×1

输出必须为严格的 JSON 格式。"""


class CorrectionAgent(BaseAgent):
    """保真修正 Agent — 人员3 在此实现

    根据 Agent 3 的审核报告（audit_result）和知识库检索素材（retrieved_chunks），
    逐条修正 Agent 2 生成的学习资源中的事实错误、逻辑偏差和难度不匹配问题。

    修正策略矩阵：
      error   → 必须修正（查 KB 原文替换）
      warning → 尽量修正（调整解释深度）
      info    → 可选修正（酌情采纳）
    """

    REQUIRED_STATE_KEYS = {"generated_resources", "audit_result", "diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "retrieved_chunks",
        "learner_data",
        "task_id",
        "agent_log",
        "status",
        "downgrade_mode",
        "diagnosis_completed",
        "resource_types",
    }

    # 修正超时保护：单个资源修正不超过 120 秒
    SINGLE_RESOURCE_TIMEOUT_SECONDS = 120

    def __init__(self):
        super().__init__(
            name="保真修正Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,  # 低温保证修正准确性，与诊断 Agent 一致
        )

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    async def process(self, state: dict) -> dict:
        """逐资源执行保真修正。

        对每份 generated_resource 找到对应的 audit_result，
        提取需要修正的 issues 并调用 LLM 生成修正后内容。
        修正失败时保留原内容并记录错误日志。
        """
        resources = state.get("generated_resources", [])
        audit_results = state.get("audit_result", [])
        chunks = state.get("retrieved_chunks", [])
        diagnosis = state.get("diagnosis_result", {})
        downgrade_mode = state.get("downgrade_mode", False)

        if not resources:
            self.log("⚠️ generated_resources 为空，跳过修正")
            return {
                "corrected_resources": [],
                "correction_log": [],
                "correction_stats": self._empty_stats(),
            }

        # ── 对齐检查：audit_result 数量警告 ──
        if len(audit_results) != len(resources):
            self.log(
                f"⚠️ audit_result 数量 ({len(audit_results)}) "
                f"与 generated_resources 数量 ({len(resources)}) 不一致"
            )

        start_time = time.time()
        corrected_resources = []
        all_logs = []
        errors_fixed = 0
        warnings_addressed = 0
        infos_applied = 0

        for i, resource in enumerate(resources):
            resource_id = resource.get("resource_id", f"unknown-{i}")
            resource_type = resource.get("resource_type", "unknown")

            # 找到对应的审核报告
            audit_report = audit_results[i] if i < len(audit_results) else {}

            try:
                result = await self._correct_one(
                    resource=resource,
                    audit_report=audit_report,
                    diagnosis=diagnosis,
                    chunks=chunks,
                    downgrade_mode=downgrade_mode,
                )

                corrected_resources.append(result["corrected_resource"])
                all_logs.extend(result["logs"])

                # 累计统计
                for log_entry in result["logs"]:
                    severity = log_entry.get("severity", "")
                    if severity == "error":
                        errors_fixed += 1
                    elif severity == "warning":
                        warnings_addressed += 1
                    elif severity == "info":
                        infos_applied += 1

                self.log(
                    f"[{i + 1}/{len(resources)}] {resource_type} "
                    f"修正完成: {len(result['logs'])} 处修正"
                )

            except Exception as e:
                # 修正失败：保留原内容，记录错误
                self.log(f"❌ [{i + 1}/{len(resources)}] {resource_type} 修正失败: {e}")
                corrected_resources.append(resource)
                all_logs.append(
                    {
                        "resource_id": resource_id,
                        "resource_type": resource_type,
                        "issue_index": -1,
                        "severity": "error",
                        "original_text": "",
                        "corrected_text": "",
                        "correction_basis": "correction_failed",
                        "kb_source": None,
                        "action": "failed",
                        "error_detail": str(e),
                    }
                )

        elapsed_ms = int((time.time() - start_time) * 1000)
        stats = {
            "total_resources": len(resources),
            "resources_corrected": sum(
                1 for r in corrected_resources if r.get("_was_corrected", False)
            ),
            "total_issues": errors_fixed + warnings_addressed + infos_applied,
            "errors_fixed": errors_fixed,
            "warnings_addressed": warnings_addressed,
            "infos_applied": infos_applied,
            "correction_time_ms": elapsed_ms,
        }

        self.log(
            f"修正全部完成: {stats['resources_corrected']}/{stats['total_resources']}"
            f" 个资源有改动, {stats['errors_fixed']} error"
            f" / {stats['warnings_addressed']} warning"
            f" / {stats['infos_applied']} info, 耗时 {elapsed_ms}ms"
        )

        return {
            "corrected_resources": corrected_resources,
            "correction_log": all_logs,
            "correction_stats": stats,
        }

    # ═══════════════════════════════════════════════════════════
    # 私有：单资源修正
    # ═══════════════════════════════════════════════════════════

    async def _correct_one(
        self,
        resource: dict,
        audit_report: dict,
        diagnosis: dict,
        chunks: list[dict],
        downgrade_mode: bool = False,
    ) -> dict:
        """修正单份学习资源。

        Args:
            resource:      Agent 2 生成的原始资源 dict
            audit_report:  Agent 3 的审核报告 dict
            diagnosis:     Agent 1 的诊断结果 dict
            chunks:        RAG 检索知识库素材 list[dict]
            downgrade_mode: 是否降级模式（无 KB 覆盖）

        Returns:
            {"corrected_resource": dict, "logs": list[dict]}
        """
        resource_id = resource.get("resource_id", str(uuid.uuid4()))
        resource_type = resource.get("resource_type", "lecture")
        original_content = resource.get("content", "")

        # ── 提取审核 issues ──
        issues = audit_report.get("issues", [])
        fact_check_items = audit_report.get("fact_check", {}).get("items", [])

        # 如果无问题，原样返回
        if not issues and not fact_check_items:
            self.log(f"  {resource_type}: 无审核问题，跳过修正")
            return {
                "corrected_resource": resource,
                "logs": [],
            }

        # ── 分类 issues ──
        errors = [iss for iss in issues if iss.get("severity") == "error"]
        warnings = [iss for iss in issues if iss.get("severity") == "warning"]
        infos = [iss for iss in issues if iss.get("severity") == "info"]

        # 将 fact_check_items 中 is_accurate=False 的提升为 error
        for fc_item in fact_check_items:
            if not fc_item.get("is_accurate", True):
                errors.append(
                    {
                        "severity": "error",
                        "detail": (
                            f"事实校验不通过: {fc_item.get('claim', '')} — "
                            f"{fc_item.get('explanation', '')}"
                        ),
                        "kb_evidence": fc_item.get("evidence_from_kb", ""),
                    }
                )

        self.log(
            f"  {resource_type}: {len(errors)} errors / {len(warnings)} warnings "
            f"/ {len(infos)} infos"
        )

        # ── 构建修正 prompt ──
        prompt = self._build_correction_prompt(
            resource=resource,
            errors=errors,
            warnings=warnings,
            infos=infos,
            diagnosis=diagnosis,
            chunks=chunks,
            downgrade_mode=downgrade_mode,
        )

        # ── 调用 LLM 生成修正后内容 ──
        corrected = await self.call_llm_json(prompt, temperature=0.2)

        # ── 防御：LLM 解析失败时保留原内容 ──
        if not corrected or corrected.get("_parse_error"):
            self.log(f"  ⚠️ {resource_type}: LLM 返回解析失败，保留原内容")
            return {
                "corrected_resource": resource,
                "logs": self._build_fallback_logs(
                    resource_id, resource_type, errors, warnings, "json_parse_failed"
                ),
            }

        # ── 组装修正后的资源 ──
        corrected_resource = {
            **resource,
            "content": corrected.get("content", original_content),
            "title": corrected.get("title", resource.get("title", "")),
            "difficulty_level": corrected.get(
                "difficulty_level", resource.get("difficulty_level", "beginner")
            ),
            "citations": corrected.get("citations", resource.get("citations", [])),
            "key_takeaways": corrected.get("key_takeaways", resource.get("key_takeaways", [])),
            "_was_corrected": True,
            "_correction_summary": corrected.get(
                "correction_summary", f"修正了 {len(errors) + len(warnings)} 处问题"
            ),
        }

        # ── 构建修正日志 ──
        logs = self._build_correction_logs(
            resource_id=resource_id,
            resource_type=resource_type,
            errors=errors,
            warnings=warnings,
            infos=infos,
            corrected_result=corrected,
            original_content=original_content,
        )

        return {
            "corrected_resource": corrected_resource,
            "logs": logs,
        }

    # ═══════════════════════════════════════════════════════════
    # 私有：prompt 构建
    # ═══════════════════════════════════════════════════════════

    def _build_correction_prompt(
        self,
        resource: dict,
        errors: list[dict],
        warnings: list[dict],
        infos: list[dict],
        diagnosis: dict,
        chunks: list[dict],
        downgrade_mode: bool = False,
    ) -> str:
        """构建修正 prompt，包含原始内容 + 审核问题 + KB 素材 + 修正指令。

        格式对齐 Agent 2 generation_v2.py 的 _generate_one() prompt 风格。
        """
        resource_type = resource.get("resource_type", "lecture")
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "unknown")

        # ── KB 素材格式化 ──
        kb_section = self._fmt_kb_chunks(chunks)

        # ── 修正模式提示 ──
        downgrade_note = ""
        if downgrade_mode:
            downgrade_note = (
                "\n## ⚠️ 降级模式\n"
                "当前为降级模式（知识库覆盖不足）。修正策略调整为：\n"
                "- 只做一致性修正：概念前后矛盾、API 名称写法不一致、"
                "代码缺少 import、步骤跳跃缺失\n"
                "- **禁止做事实判断**：不要凭自己的知识判断对错，"
                "不确定的内容标注 [暂无权威参考，建议补充学习]\n"
                "- 难度不匹配问题照常修正（调整解释深度即可）\n"
            )

        # ── 结构模板提示 ──
        structure_guide = self._fmt_structure_guide(resource_type)

        prompt = f"""## 学习者信息
- 推荐难度：{difficulty}
- 学习风格：{learning_style}
- 学习目标：{diagnosis.get("summary", "未指定")}
{downgrade_note}
## 原始资源
- 类型：{resource_type}
- 标题：{resource.get("title", "")}
- 难度标注：{resource.get("difficulty_level", "")}

### 原始内容
{resource.get("content", "")[:5000]}

## 审核发现的问题

### 🔴 必须修正（error）
{self._fmt_issues(errors) if errors else "无"}

### 🟡 尽量修正（warning）
{self._fmt_issues(warnings) if warnings else "无"}

### 🔵 可选修正（info）
{self._fmt_issues(infos) if infos else "无"}

## 知识库参考素材
{kb_section}

## 修正任务
请根据以上信息，对原始资源进行修正。输出 JSON：

{{
    "title": "修正后的标题（如无修改则用原标题）",
    "content": "修正后的 Markdown 完整内容",
    "difficulty_level": "{resource.get("difficulty_level", "")}",
    "citations": [
        {{
            "doc_id": "知识库文档ID",
            "chunk_index": 0,
            "original_text": "知识库原文片段（逐字引用）",
            "relevance_score": 0.95
        }}
    ],
    "key_takeaways": ["修正后的学习要点1", "修正后的学习要点2", "修正后的学习要点3"],
    "correction_summary": "一句话概括做了哪些修正"
    "（如：修正了LangGraph开发者归属错误，调整了RAG概念定义，"
    "并列展示了两种检索策略）"
}}

## 硬性要求
1. **只改有问题的部分**：保留原内容中正确的段落、代码、示例、结构
2. **error 必须修正**：每个 error 级别 issue 必须处理，查 KB 原文替换错误内容
3. **warning 尽量修正**：调整解释深度对齐 {difficulty} 水平、补充缺失细节
4. **info 酌情采纳**：不引入新事实断言的前提下可采纳改进建议
5. **KB 冲突并列**：同一主题存在多版本说法时，用 "说法A: ... / 说法B: ..." 并列展示
6. **不引入新断言**：修正完成后检查——是否新增了 KB 未覆盖的技术声明？有则删除或标注 [暂无权威参考]
7. {structure_guide}
8. 内容格式为 Markdown，代码示例和命令行用 `````` 标注语言类型
9. citations 列表包含所有引用 KB 原文的溯源记录，
   每条 citation 的 original_text 必须是 KB 中的逐字原文"""

        return prompt

    # ═══════════════════════════════════════════════════════════
    # 私有：格式化辅助方法（风格对齐 Agent 2 generation_v2.py）
    # ═══════════════════════════════════════════════════════════

    def _fmt_issues(self, issues: list[dict]) -> str:
        """格式化审核问题列表为可读文本。

        与 Agent 2 generation_v2.py 的 _fmt_gaps() 排版风格对齐：
          - 使用 [severity] 标签
          - 每条一行，信息简洁
        """
        if not issues:
            return "无"

        lines = []
        for idx, iss in enumerate(issues):
            severity = iss.get("severity", "unknown")
            detail = iss.get("detail", str(iss))
            kb_evidence = iss.get("kb_evidence", "")

            line = f"{idx + 1}. [{severity}] {detail}"
            if kb_evidence:
                line += f"\n   KB 原文: {kb_evidence[:200]}"
            lines.append(line)

        return "\n".join(lines)

    def _fmt_kb_chunks(self, chunks: list[dict]) -> str:
        """格式化知识库检索素材为参考信息。

        最多展示 8 个 chunk，超出则截断并提示。
        每个 chunk 显示 doc_id + chunk_index + 内容摘要。
        """
        if not chunks:
            return (
                "⚠️ 无知识库参考素材。\n"
                "修正时只做一致性检查（概念矛盾、API 不一致等），"
                "禁止凭自身知识判断技术对错。\n"
                "所有无法验证的技术声明标注 [暂无权威参考，建议补充学习]。"
            )

        lines = []
        for idx, chunk in enumerate(chunks[:8]):
            doc_id = chunk.get("doc_id", "unknown")
            chunk_idx = chunk.get("chunk_index", 0)
            content = chunk.get("content", "")[:500]
            score = chunk.get("relevance_score", 0.0)

            lines.append(
                f"### KB素材 {idx + 1}: {doc_id}#chunk_{chunk_idx} "
                f"(相关度: {score:.2f})\n"
                f"```\n{content}\n```"
            )

        if len(chunks) > 8:
            lines.append(f"\n…（还有 {len(chunks) - 8} 个 chunks 未列出）")

        return "\n\n".join(lines)

    def _fmt_structure_guide(self, resource_type: str) -> str:
        """根据资源类型返回对应的内容结构描述。

        对齐 Agent 2 generation_v2.py 的"三种资源固定内容结构"。
        """
        guides = {
            "lecture": ("保持 lecture 结构：引言 → 3~4小节（概念+可运行代码）→ 总结"),
            "guide": (
                "保持 guide 结构：概述 → 前置准备 → 分步操作（命令+代码+预期输出）→ 常见问题"
            ),
            "quiz": (
                "保持 quiz 结构：基础选择题2道（含选项/标准答案/解析）→ "
                "进阶题1道 → 挑战实操题1道。修正时保持原题号和格式"
            ),
        }
        return guides.get(resource_type, "保持原内容结构不变")

    # ═══════════════════════════════════════════════════════════
    # 私有：修正日志构建
    # ═══════════════════════════════════════════════════════════

    def _build_correction_logs(
        self,
        resource_id: str,
        resource_type: str,
        errors: list[dict],
        warnings: list[dict],
        infos: list[dict],
        corrected_result: dict,
        original_content: str,
    ) -> list[dict]:
        """构建修正日志，逐条记录修正动作。

        每条日志包含：原内容、修正后内容、修正依据、操作类型。
        """
        logs = []

        # error → 必须修正
        for idx, err in enumerate(errors):
            logs.append(
                {
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "issue_index": idx,
                    "severity": "error",
                    "original_text": err.get("detail", "")[:300],
                    "corrected_text": (
                        corrected_result.get("content", "")[:300]
                        if corrected_result.get("content")
                        else ""
                    ),
                    "correction_basis": (
                        "knowledge_base" if err.get("kb_evidence") else "consistency_check"
                    ),
                    "kb_source": err.get("kb_evidence", None),
                    "action": "replaced",
                }
            )

        # warning → 尽量修正
        for idx, warn in enumerate(warnings):
            logs.append(
                {
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "issue_index": idx,
                    "severity": "warning",
                    "original_text": warn.get("detail", "")[:300],
                    "corrected_text": "[难度/深度调整]",
                    "correction_basis": "difficulty_adjust",
                    "kb_source": None,
                    "action": "adjusted",
                }
            )

        # info → 可选修正
        infos_applied = corrected_result.get("_infos_applied", 0)
        for idx, info in enumerate(infos):
            logs.append(
                {
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "issue_index": idx,
                    "severity": "info",
                    "original_text": info.get("detail", "")[:300],
                    "corrected_text": (
                        "[已采纳改进]"
                        if idx < infos_applied
                        else "[未采纳 — 可能引入新断言或影响范围过大]"
                    ),
                    "correction_basis": "improvement",
                    "kb_source": None,
                    "action": "accepted" if idx < infos_applied else "skipped",
                }
            )

        return logs

    def _build_fallback_logs(
        self,
        resource_id: str,
        resource_type: str,
        errors: list[dict],
        warnings: list[dict],
        reason: str,
    ) -> list[dict]:
        """构建兜底日志（LLM 调用失败或 JSON 解析失败时使用）。"""
        logs = []
        for idx, err in enumerate(errors):
            logs.append(
                {
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "issue_index": idx,
                    "severity": "error",
                    "original_text": err.get("detail", "")[:300],
                    "corrected_text": "",
                    "correction_basis": "failed",
                    "kb_source": None,
                    "action": "failed",
                    "error_detail": reason,
                }
            )
        for idx, warn in enumerate(warnings):
            logs.append(
                {
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "issue_index": idx,
                    "severity": "warning",
                    "original_text": warn.get("detail", "")[:300],
                    "corrected_text": "",
                    "correction_basis": "failed",
                    "kb_source": None,
                    "action": "failed",
                    "error_detail": reason,
                }
            )
        return logs

    @staticmethod
    def _empty_stats() -> dict:
        """返回空的修正统计。"""
        return {
            "total_resources": 0,
            "resources_corrected": 0,
            "total_issues": 0,
            "errors_fixed": 0,
            "warnings_addressed": 0,
            "infos_applied": 0,
            "correction_time_ms": 0,
        }


# ═══════════════════════════════════════════════════════════
# 使用示例（开发调试用）
# ═══════════════════════════════════════════════════════════
"""
import asyncio
from backend.src.agents.correction import CorrectionAgent


async def demo():
    agent = CorrectionAgent()
    state = {
        "diagnosis_result": {
            "summary": "学习 LangGraph 开发 AI Agent",
            "recommended_difficulty": "beginner",
            "learning_style": "theory_first",
            "skill_gaps": [
                {
                    "priority": "critical",
                    "topic": "LangGraph 状态管理",
                    "current_level": 0.1,
                    "target_level": 0.9,
                    "reason": "不清楚图状态流转机制",
                },
            ],
        },
        "generated_resources": [
            {
                "resource_id": "res-001",
                "resource_type": "lecture",
                "title": "LangGraph 入门讲义",
                "content": (
                    "# LangGraph 入门讲义\\n\\n"
                    "LangGraph 是 Google 开发的图状态管理框架。\\n\\n"
                    "## 核心概念\\n"
                    "StateGraph 让你用状态字典在节点间传递数据。\\n"
                ),
                "difficulty_level": "beginner",
                "citations": [],
                "key_takeaways": ["理解 LangGraph", "掌握 StateGraph"],
            },
        ],
        "audit_result": [
            {
                "verdict": "needs_revision",
                "issues": [
                    {
                        "severity": "error",
                        "detail": "LangGraph 不是 Google 开发的，是 LangChain 团队开发的",
                        "kb_evidence": "LangGraph is a library built by the LangChain team",
                    },
                    {
                        "severity": "warning",
                        "detail": "缺少对 StateGraph 三个要素（节点、边、状态字典）的逐一说明",
                    },
                    {
                        "severity": "info",
                        "detail": "建议在引言中加入一个生活类比帮助理解",
                    },
                ],
            },
        ],
        "retrieved_chunks": [
            {
                "doc_id": "langgraph_intro.md",
                "chunk_index": 2,
                "content": (
                    "LangGraph is a library built by the LangChain team "
                    "for building stateful, multi-actor applications with LLMs."
                ),
                "relevance_score": 0.95,
            },
            {
                "doc_id": "langgraph_intro.md",
                "chunk_index": 5,
                "content": (
                    "StateGraph 的三个核心要素：节点（Node）定义处理逻辑、"
                    "边（Edge）定义流转方向、状态字典（State）传递上下文数据。"
                ),
                "relevance_score": 0.90,
            },
        ],
    }
    result = await agent.run(state)
    print(f"修正完成: {len(result.get('corrected_resources', []))} 个资源")
    print(f"修正统计: {result.get('correction_stats', {})}")
    if result.get("correction_log"):
        print(f"修正日志: {len(result['correction_log'])} 条")


if __name__ == "__main__":
    asyncio.run(demo())
"""

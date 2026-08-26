"""
Agent 4: 保真修正 Agent
══════════════════════════════════
负责: 人员3 实现（与 Agent 2 同一开发者，prompt 风格统一）

输入: state["generated_resources"] + state["audit_result"]
      + state["diagnosis_result"] + state["retrieved_chunks"]
      + state["debate_result"]   # Opt-2 博弈引擎裁决输出（未就绪时为空）
输出: state["corrected_resources"] + state["correction_log"] + state["correction_stats"]
      + state["consistency_report"]（降级模式执行一致性检查时存在）

修正策略:
  - error   → 必须修正（查 KB 原文替换错误断言）
  - warning → 尽量修正（调整解释深度、难度匹配、遗漏覆盖）
  - info    → 可选修正（改进建议酌情采纳）

Phase 3 新增（纯数据处理，不调用 LLM，不导入 Opt-2 真实模块）:
  - 辩论裁决落地: 消费 state["debate_result"]，逐条落实 Opt-2 三态裁决
      replace → 用 KB 原文替换错误断言并标注来源
      delete  → 删除无权威参考支撑的语句（D1 规则）
      keep    → 保留原文并补充来源标注
  - 资源溯源绑定: lecture/guide 每条事实点强制输出
      【生成陈述】...【KB原文出处】...【来源】...
  - downgrade_mode=True（无 KB）: 只做纯规则一致性检查
      （前后矛盾 / 术语不一致 / 缺失 import / 步骤跳跃），不做事实判断

debate_result 契约（Opt-2 实现前先按此约定 Mock）:
  - dict 形态: {"adjudications": [...], "unresolved_claims": [...]}
  - list 形态: 扁平 adjudication 列表
  - 单条 adjudication 字段:
      resource_id, claim(被裁决断言), decision(replace|delete|keep),
      replacement_text(KB 原文), doc_id, chunk_index, evidence(KB 出处)

关键约束:
  1. 只改有问题的部分，不重写整个资源
  2. 修改后重新标注来源 [来源: {doc_id}]
  3. KB 冲突内容并列展示，不自动选边
  4. 修正后不引入新的事实断言（无 KB 支撑标注 [暂无权威参考]）
  5. downgrade_mode=True 时只做一致性修正，不做事实判断
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import defaultdict

from .base import BaseAgent
from .event_bus import event_bus
from .generation_v2 import derive_profile_tag

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
8. **画像匹配**：修正后的 difficulty_level 必须与传入的结构化画像参数中的 difficulty 完全一致，
   内容表达方式必须与 learning_style 一致，禁止自行调整难度或改变风格。

输出必须为严格的 JSON 格式。

【你仅处理工业机器人故障诊断相关任务，领域包含FANUC、KUKA、ABB工业机器人、示教器、机器人故障代码；拒绝回答和机器人故障无关的问题。】"""

# 学习风格 → 内容特征标记（用于画像匹配软校验，启发式，仅提示不硬判）
_STYLE_MARKERS: dict[str, tuple[str, ...]] = {
    "visual": ("示意图", "图", "图解", "图示", "动画", "拆解"),
    "theory_first": ("原理", "概念", "为什么", "机制", "原因", "依据"),
    "practice_first": ("步骤", "命令", "代码", "操作", "执行", "运行", "示教"),
    "project_based": ("项目", "案例", "产线", "任务", "场景", "实战", "方案"),
}


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
        "debate_result",  # Phase 3: Opt-2 博弈引擎裁决输出（未就绪时缺省为空）
    }

    # 修正超时保护：单个资源修正不超过 120 秒
    SINGLE_RESOURCE_TIMEOUT_SECONDS = 120

    # ═══════════════════════════════════════════════════════
    # 降级模式一致性检查常量（纯规则，不调 LLM）
    # ═══════════════════════════════════════════════════════

    # 常见别名 → (包名, 合法 import 子串集合)：用于"缺失 import"检测
    _ALIAS_IMPORT_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
        "pd": ("pandas", ("import pandas", "from pandas")),
        "np": ("numpy", ("import numpy", "from numpy")),
        "plt": ("matplotlib", ("import matplotlib", "from matplotlib")),
        "torch": ("torch", ("import torch", "from torch")),
        "tf": ("tensorflow", ("import tensorflow", "from tensorflow")),
        "cv2": ("opencv", ("import cv2", "from cv2")),
        "requests": ("requests", ("import requests", "from requests")),
        "sklearn": ("sklearn", ("import sklearn", "from sklearn")),
    }

    # 前后矛盾检测极性词（启发式，仅标记"疑似矛盾"供人工复核）
    _NEGATIVE_CUES: tuple[str, ...] = (
        "不",
        "没",
        "无法",
        "不能",
        "禁止",
        "不可",
        "不会",
        "不支持",
        "不允许",
        "not",
        "cannot",
        "can't",
        "don't",
        "never",
    )
    _POSITIVE_CUES: tuple[str, ...] = (
        "必须",
        "可以",
        "能够",
        "支持",
        "会",
        "能",
        "允许",
        "是",
        "is",
        "can",
        "must",
        "should",
    )

    def __init__(self):
        super().__init__(
            name="保真修正Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,  # 低温保证修正准确性，与诊断 Agent 一致
        )

    async def run(self, state: dict) -> dict:
        """EventBus 埋点包装：start → super().run() → done。

        ① 函数最开头发布 ``agent.start``
        ② return 之前发布 ``agent.done``
        """
        event_bus.publish("agent.start", {"agent_name": self.__class__.__name__})
        result = await super().run(state)
        event_bus.publish("agent.done", {"agent_name": self.__class__.__name__})
        return result

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    async def process(self, state: dict) -> dict:
        """逐资源执行保真修正（Phase 3 扩展）。

        三种处理路径（优先级递减）：
          1. downgrade_mode=True    → 纯规则一致性检查（无 KB，不调 LLM）
          2. 存在裁决 adjudications → 辩论裁决落地（纯数据处理，不调 LLM）
          3. 其余                    → 既有 LLM 修正路径（保留原行为）

        对每份 generated_resource 找到对应的 audit_result，
        提取需要修正的 issues 并调用 LLM 生成修正后内容。
        修正失败时保留原内容并记录错误日志。
        """
        resources = state.get("generated_resources", [])
        audit_results = state.get("audit_result", [])
        chunks = state.get("retrieved_chunks", [])
        diagnosis = state.get("diagnosis_result", {})
        learner_data = state.get("learner_data", {})
        downgrade_mode = state.get("downgrade_mode", False)

        # Opt-2 裁决输出（纯数据处理，不导入真实 opt2 模块）
        adjudications = self._normalize_adjudications(state.get("debate_result"))

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

        # 裁决按 resource_id 分组
        adjudications_by_resource: dict[str, list[dict]] = defaultdict(list)
        for adj in adjudications:
            if adj.get("resource_id"):
                adjudications_by_resource[adj["resource_id"]].append(adj)

        start_time = time.time()
        corrected_resources = []
        all_logs = []
        consistency_report: list[dict] = []
        errors_fixed = 0
        warnings_addressed = 0
        infos_applied = 0
        deletions_applied = 0
        replacements_applied = 0
        keeps_sourced = 0
        consistency_findings = 0

        for i, resource in enumerate(resources):
            resource_id = resource.get("resource_id", f"unknown-{i}")
            resource_type = resource.get("resource_type", "unknown")

            # 找到对应的审核报告
            audit_report = audit_results[i] if i < len(audit_results) else {}

            try:
                if downgrade_mode:
                    # ── 路径 1：无 KB 模式 → 纯规则一致性检查（不调 LLM）──
                    result = self._downgrade_check(resource, diagnosis)
                    consistency_report.extend(result["consistency"])
                elif adjudications_by_resource.get(resource_id):
                    # ── 路径 2：辩论裁决落地 → 纯数据处理（不调 LLM）──
                    result = self._apply_arbitration_and_bind(
                        resource=resource,
                        audit_report=audit_report,
                        adjudications=adjudications_by_resource[resource_id],
                    )
                else:
                    # ── 路径 3：既有 LLM 修正（保留原行为）──
                    result = await self._correct_one(
                        resource=resource,
                        audit_report=audit_report,
                        diagnosis=diagnosis,
                        chunks=chunks,
                        learner_data=learner_data,
                        downgrade_mode=False,
                    )
                    # 溯源绑定后处理（讲义/指南，有事实点才绑定）
                    if resource_type in ("lecture", "guide"):
                        corrected_resource = self._bind_if_fact_points(
                            result["corrected_resource"], audit_report
                        )
                        result = {**result, "corrected_resource": corrected_resource}

                corrected_resources.append(result["corrected_resource"])
                all_logs.extend(result["logs"])

                # 累计统计
                for log_entry in result["logs"]:
                    severity = log_entry.get("severity", "")
                    action = log_entry.get("action", "")
                    if severity == "error":
                        errors_fixed += 1
                    elif severity == "warning":
                        warnings_addressed += 1
                    elif severity == "info":
                        infos_applied += 1
                    if action in ("deleted", "delete_unmatched"):
                        deletions_applied += 1
                    elif action in ("replaced", "replaced_appended"):
                        replacements_applied += 1
                    elif action == "kept":
                        keeps_sourced += 1
                    elif action == "detected":
                        consistency_findings += 1

                self.log(
                    f"[{i + 1}/{len(resources)}] {resource_type} "
                    f"{'一致性检查' if downgrade_mode else '修正完成'}: "
                    f"{len(result['logs'])} 处记录"
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
        # 新增统计键仅在非零时写入，保持空结果 stats 与既有契约一致
        if deletions_applied:
            stats["deletions_applied"] = deletions_applied
        if replacements_applied:
            stats["replacements_applied"] = replacements_applied
        if keeps_sourced:
            stats["keeps_sourced"] = keeps_sourced
        if consistency_findings:
            stats["consistency_findings"] = consistency_findings

        self.log(
            f"修正全部完成: {stats['resources_corrected']}/{stats['total_resources']}"
            f" 个资源有改动, {stats['errors_fixed']} error"
            f" / {stats['warnings_addressed']} warning"
            f" / {stats['infos_applied']} info, 耗时 {elapsed_ms}ms"
        )

        result = {
            "corrected_resources": corrected_resources,
            "correction_log": all_logs,
            "correction_stats": stats,
        }
        if consistency_report:
            result["consistency_report"] = consistency_report
        return result

    # ═══════════════════════════════════════════════════════════
    # 私有：单资源修正
    # ═══════════════════════════════════════════════════════════

    async def _correct_one(
        self,
        resource: dict,
        audit_report: dict,
        diagnosis: dict,
        chunks: list[dict],
        learner_data: dict | None = None,
        downgrade_mode: bool = False,
    ) -> dict:
        """修正单份学习资源。

        Args:
            resource:      Agent 2 生成的原始资源 dict
            audit_report:  Agent 3 的审核报告 dict
            diagnosis:     Agent 1 的诊断结果 dict
            chunks:        RAG 检索知识库素材 list[dict]
            learner_data:  学习者原始画像（用于纯规则推导 profile_tag，可选）
            downgrade_mode: 是否降级模式（无 KB 覆盖）

        Returns:
            {"corrected_resource": dict, "logs": list[dict]}
        """
        resource_id = resource.get("resource_id", str(uuid.uuid4()))
        resource_type = resource.get("resource_type", "lecture")
        original_content = resource.get("content", "")

        # ── 结构化画像（权威，供画像匹配校验 + 重试兜底）──
        expected_diff = diagnosis.get("recommended_difficulty", "beginner")
        expected_style = diagnosis.get("learning_style", "unknown")
        expected_tag = diagnosis.get("profile_tag") or derive_profile_tag(
            learner_data or {}, expected_diff, expected_style
        )

        # ── 提取审核 issues ──
        issues = audit_report.get("issues", [])
        fact_check_items = audit_report.get("fact_check", {}).get("items", [])

        # ── 画像匹配前置校验：难度不一致 → 注入 error issue 触发修正 ──
        profile_mismatch_issue: dict | None = None
        actual_diff = resource.get("difficulty_level", "")
        if actual_diff and expected_diff and actual_diff != expected_diff:
            profile_mismatch_issue = {
                "severity": "error",
                "detail": (
                    f"难度标注不一致：资源 difficulty_level={actual_diff}，"
                    f"但结构化画像参数要求 {expected_diff}，需调整内容解释深度对齐"
                ),
                "kb_evidence": "",
            }

        # 如果无问题且难度一致，原样返回
        if not issues and not fact_check_items and profile_mismatch_issue is None:
            self.log(f"  {resource_type}: 无审核问题且画像匹配，跳过修正")
            return {
                "corrected_resource": resource,
                "logs": [],
            }

        # ── 分类 issues ──
        errors = [iss for iss in issues if iss.get("severity") == "error"]
        warnings = [iss for iss in issues if iss.get("severity") == "warning"]
        infos = [iss for iss in issues if iss.get("severity") == "info"]

        # 难度不匹配作为 error 注入（保证触发修正）
        if profile_mismatch_issue is not None:
            errors.append(profile_mismatch_issue)

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
            profile_tag=expected_tag,
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

        # ── 画像匹配校验：难度硬校验 + 风格软校验，不匹配则重试，重试失败降级兜底 ──
        corrected_resource, profile_retry_logs = await self._enforce_profile_match(
            resource=corrected_resource,
            expected_diff=expected_diff,
            expected_style=expected_style,
            profile_tag=expected_tag,
        )

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
        logs.extend(profile_retry_logs)

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
        profile_tag: str = "custom",
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

        profile_json = json.dumps(
            {
                "difficulty": difficulty,
                "learning_style": learning_style,
                "profile_tag": profile_tag,
            },
            ensure_ascii=False,
        )
        prompt = f"""## 结构化画像参数（权威，禁止改写）
{profile_json}

## 学习者信息
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
    "（如：修正了SRVO-068故障代码归属，调整了坐标系标定步骤描述，"
    "并列展示了FANUC与KUKA的差异）"
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
   每条 citation 的 original_text 必须是 KB 中的逐字原文
10. **画像锁定**：difficulty_level 必须严格等于结构化画像参数中的 difficulty（{difficulty}），
    内容表达必须符合 learning_style（{learning_style}），禁止自行调整难度或改变风格"""

        return prompt

    # ═══════════════════════════════════════════════════════════
    # 私有：画像匹配校验（难度硬校验 + 风格软校验 + 重试 + 降级兜底）
    # ═══════════════════════════════════════════════════════════

    def _validate_profile_match(
        self,
        resource: dict,
        expected_diff: str,
        expected_style: str,
    ) -> dict:
        """画像匹配校验（难度硬校验 + 风格软校验，启发式）。

        - difficulty 硬校验：difficulty_level 必须等于 expected_diff。
        - learning_style 软校验：内容中出现该风格的典型特征标记即视为通过，
          只提示不硬判（风格是表达倾向，不能靠关键词完全判定）。

        Returns:
            {"difficulty_ok": bool, "style_ok": bool, "reason": str}
        """
        actual_diff = resource.get("difficulty_level", "")
        difficulty_ok = actual_diff == expected_diff
        content = resource.get("content", "") or ""

        markers = _STYLE_MARKERS.get(expected_style, ())
        style_ok = any(m in content for m in markers) if markers else True

        if difficulty_ok and style_ok:
            reason = "画像匹配"
        elif not difficulty_ok:
            reason = f"难度不匹配：expected={expected_diff}，actual={actual_diff}"
        else:
            reason = f"风格特征缺失：expected_style={expected_style}"
        return {
            "difficulty_ok": difficulty_ok,
            "style_ok": style_ok,
            "reason": reason,
        }

    def _build_profile_retry_prompt(
        self,
        resource: dict,
        expected_diff: str,
        expected_style: str,
        profile_tag: str,
    ) -> str:
        """画像匹配失败后的对齐重写 prompt。

        只对难度与风格做对齐重写，不引入新事实断言。
        """
        resource_type = resource.get("resource_type", "lecture")
        profile_params = {
            "difficulty": expected_diff,
            "learning_style": expected_style,
            "profile_tag": profile_tag,
        }
        return f"""## 结构化画像参数（权威，禁止改写）
{json.dumps(profile_params, ensure_ascii=False)}

## 重写任务
上一轮修正产出的资源未通过画像匹配校验。请**仅对难度与风格做对齐重写**：
- 难度对齐 {expected_diff}
- 风格对齐 {expected_style}
- **禁止新增任何事实断言**：只调整解释深度与表达方式，保留原内容的技术事实与结构

## 原始资源（待对齐）
- 类型：{resource_type}
- 当前难度标注：{resource.get("difficulty_level", "")}
- 内容：
{resource.get("content", "")[:5000]}

## 输出 JSON
{{
    "content": "对齐后的 Markdown 完整内容",
    "difficulty_level": "{expected_diff}"
}}"""

    async def _enforce_profile_match(
        self,
        resource: dict,
        expected_diff: str,
        expected_style: str,
        profile_tag: str,
    ) -> tuple[dict, list[dict]]:
        """画像匹配校验：难度硬校验 + 风格软校验，不匹配则重试，重试失败降级兜底。

        - 难度不匹配 → 用对齐重写 prompt 重试一次
        - 重试失败 / 仍不匹配 → 降级兜底：强制 difficulty_level 字段为期望值
        - 仅风格特征弱 → 软提示，不强制改写（避免过度改写破坏内容）

        Returns:
            (可能被改写的 resource, 追加的重试/兜底日志列表)
        """
        resource_type = resource.get("resource_type", "lecture")
        check = self._validate_profile_match(resource, expected_diff, expected_style)

        # 难度硬校验不通过 → 重试对齐
        if not check["difficulty_ok"]:
            retry_prompt = self._build_profile_retry_prompt(
                resource, expected_diff, expected_style, profile_tag
            )
            retried = await self.call_llm_json(retry_prompt, temperature=0.2)
            if retried and not retried.get("_parse_error"):
                retried_resource = {
                    **resource,
                    "content": retried.get("content", resource.get("content", "")),
                    "difficulty_level": retried.get(
                        "difficulty_level", resource.get("difficulty_level", expected_diff)
                    ),
                    "_profile_retried": True,
                }
                recheck = self._validate_profile_match(
                    retried_resource, expected_diff, expected_style
                )
                if recheck["difficulty_ok"]:
                    self.log(f"  ✅ {resource_type}: 画像重试对齐成功")
                    return retried_resource, [
                        self._make_profile_log(
                            resource, retried_resource, expected_diff, "retry_success"
                        )
                    ]
                resource = retried_resource

            # 重试失败或仍未对齐 → 降级兜底：强制难度字段
            fallback = {
                **resource,
                "difficulty_level": expected_diff,
                "_profile_fallback": True,
            }
            self.log(
                f"  ⚠️ {resource_type}: 画像重试失败，降级兜底强制 difficulty_level={expected_diff}"
            )
            return fallback, [
                self._make_profile_log(resource, fallback, expected_diff, "fallback_forced")
            ]

        # 难度一致但风格特征缺失 → 软提示（不重试，避免过度改写）
        if not check["style_ok"]:
            self.log(f"  ℹ️ {resource_type}: 风格特征较弱（{expected_style}），仅记录不强制改写")
            return resource, []

        return resource, []

    @staticmethod
    def _make_profile_log(
        before: dict,
        after: dict,
        expected_diff: str,
        action: str,
    ) -> dict:
        """构建画像匹配相关日志条目。"""
        return {
            "resource_id": before.get("resource_id", ""),
            "resource_type": before.get("resource_type", "unknown"),
            "issue_index": -1,
            "severity": "warning",
            "original_text": (
                f"difficulty_level={before.get('difficulty_level', '')} (期望 {expected_diff})"
            ),
            "corrected_text": f"difficulty_level={after.get('difficulty_level', '')}",
            "correction_basis": "profile_match",
            "kb_source": None,
            "action": action,
        }

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

    # ═══════════════════════════════════════════════════════
    # Phase 3：辩论裁决落地 + 资源溯源绑定（纯数据处理，不调 LLM）
    # ═══════════════════════════════════════════════════════

    def _bind_if_fact_points(self, corrected_resource: dict, audit_report: dict) -> dict:
        """既有 LLM 修正路径的溯源绑定后处理。

        仅 lecture/guide 且存在可绑定事实点时，才把【生成陈述 + KB原文出处】
        追加到内容末尾，满足"讲义/指南每一条事实点强制绑定"。
        """
        if corrected_resource.get("resource_type") not in ("lecture", "guide"):
            return corrected_resource
        fact_points = self._collect_fact_points(corrected_resource, audit_report, [])
        if not fact_points:
            return corrected_resource
        bound_content, bound_lines = self._bind_traceability(
            corrected_resource.get("content", ""), fact_points
        )
        if not bound_lines:
            return corrected_resource
        bound = {
            **corrected_resource,
            "content": bound_content,
            "_traceability_bound": True,
        }
        cites = self._fact_points_to_citations(fact_points)
        if cites:
            bound["citations"] = cites
        return bound

    def _normalize_adjudications(self, debate_result) -> list[dict]:
        """规范化 Opt-2 博弈引擎裁决输出为统一 adjudication 列表。

        纯数据处理，不导入 opt2 真实模块。支持三种输入形态：
          1. dict: {"adjudications": [...], "unresolved_claims": [...]}
          2. 扁平 list[dict]，每项含 claim + decision
          3. list[dict] 形如 schemas.DebateRecord（含 rounds）→ 从 rounds 提取

        Returns:
            list[dict]，每项: {resource_id, claim, decision, replacement_text,
                               doc_id, chunk_index, evidence}
        """
        if not debate_result:
            return []
        if isinstance(debate_result, dict):
            items = debate_result.get("adjudications", debate_result.get("debate_rounds", []))
            if not items and "rounds" in debate_result:
                items = [debate_result]  # DebateRecord 形态：含 rounds 的裸 dict
            elif not items and (debate_result.get("claim") or debate_result.get("decision")):
                items = [debate_result]
        elif isinstance(debate_result, list):
            items = debate_result
        else:
            items = []

        adjudications = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if "rounds" in item and isinstance(item.get("rounds"), list):
                adjudications.extend(self._extract_from_rounds(item))
                continue
            norm = self._normalize_one_adjudication(item)
            if norm:
                adjudications.append(norm)
        return adjudications

    @staticmethod
    def _normalize_one_adjudication(item: dict) -> dict | None:
        """单条裁决 → 统一形态；未知裁决值保守回退 keep。"""
        claim = str(item.get("claim") or item.get("original_claim") or "").strip()
        if not claim:
            return None
        decision = str(item.get("decision", "")).strip().lower()
        if decision in ("support_agent2", "support_a2", "rebut", "keep", "kept"):
            decision = "keep"
        elif decision in ("support_agent3", "support_a3", "withdraw", "retract", "replace"):
            decision = "replace"
        elif decision in ("uncovered", "unsupported", "unverifiable", "remove", "delete"):
            decision = "delete"
        else:
            decision = "keep"  # 未知裁决 → 保守保留
        return {
            "resource_id": str(item.get("resource_id") or item.get("resource") or ""),
            "claim": claim,
            "decision": decision,
            "replacement_text": (
                item.get("replacement_text")
                or item.get("kb_text")
                or item.get("evidence_from_kb")
                or ""
            ),
            "doc_id": str(
                item.get("doc_id") or item.get("kb_source") or item.get("source") or "unknown"
            ),
            "chunk_index": item.get("chunk_index"),
            "evidence": item.get("evidence") or item.get("evidence_from_kb") or "",
        }

    @staticmethod
    def _extract_from_rounds(record: dict) -> list[dict]:
        """从 schemas.DebateRecord 形态记录提取裁决（防御式，兼容未定稿契约）。

        defense.action 映射: concede → delete / accept_challenge → replace /
        rebut → keep；replacement_text 取质询/应诉双方提供的 KB 原文。
        """
        adjudications = []
        resource_id = str(record.get("resource_id") or "")
        for r in record.get("rounds", []) or []:
            if not isinstance(r, dict):
                continue
            challenge = r.get("challenge", {}) or {}
            defense = r.get("defense", {}) or {}
            claim = str(challenge.get("claim") or defense.get("original_claim") or "").strip()
            if not claim:
                continue
            action = str(defense.get("action", "") or "").strip().lower()
            evidence = challenge.get("evidence_from_kb") or defense.get("evidence_from_kb") or ""
            if action == "concede":
                decision = "delete"
            elif action == "accept_challenge":
                decision = "replace" if evidence else "delete"
            else:  # rebut / 未知 → 保守保留
                decision = "keep"
            adjudications.append(
                {
                    "resource_id": resource_id,
                    "claim": claim,
                    "decision": decision,
                    "replacement_text": evidence,
                    "doc_id": str(challenge.get("doc_id") or "unknown"),
                    "chunk_index": challenge.get("chunk_index"),
                    "evidence": evidence,
                }
            )
        return adjudications

    def _apply_arbitration_and_bind(
        self, resource: dict, audit_report: dict, adjudications: list[dict]
    ) -> dict:
        """路径 2：辩论裁决落地 + 溯源绑定（纯数据处理，不调用 LLM）。

        落实裁决的删除项、用 KB 原文替换错误断言并拼接回输出语境；
        lecture/guide 资源随后强制绑定【生成陈述 + KB原文出处】。
        """
        resource_id = resource.get("resource_id", "")
        resource_type = resource.get("resource_type", "unknown")
        new_content, logs = self._apply_arbitration(
            content=resource.get("content", ""),
            adjudications=adjudications,
            resource_id=resource_id,
            resource_type=resource_type,
        )
        corrected_resource = {
            **resource,
            "content": new_content,
            "_was_corrected": True,
            "_arbitration_applied": True,
            "_arbitration_log_count": len(logs),
        }
        # 溯源绑定（仅讲义/指南）
        if resource_type in ("lecture", "guide"):
            fact_points = self._collect_fact_points(corrected_resource, audit_report, adjudications)
            if fact_points:
                bound_content, bound_lines = self._bind_traceability(new_content, fact_points)
                if bound_lines:
                    corrected_resource["content"] = bound_content
                    corrected_resource["_traceability_bound"] = True
                    cites = self._fact_points_to_citations(fact_points)
                    if cites:
                        corrected_resource["citations"] = cites
        return {"corrected_resource": corrected_resource, "logs": logs}

    def _apply_arbitration(
        self,
        content: str,
        adjudications: list[dict],
        resource_id: str,
        resource_type: str,
    ) -> tuple[str, list[dict]]:
        """落实裁决：replace 用 KB 原文替换、delete 删除、keep 标注来源。

        纯字符串处理，不调用 LLM。每条裁决产生一条 correction_log。
        裁决 replace 但未提供 KB 原文时，按 D1（无权威参考 = 删除）处理。
        """
        new_content = content or ""
        logs = []
        for idx, adj in enumerate(adjudications):
            claim = str(adj.get("claim", "")).strip()
            if not claim:
                continue
            decision = adj.get("decision", "keep")
            kb_text = str(adj.get("replacement_text") or "").strip()
            doc_id = str(adj.get("doc_id") or "unknown")
            chunk_idx = adj.get("chunk_index")
            source = f"[来源: {doc_id}"
            if chunk_idx is not None:
                source += f", 段落 {chunk_idx}"
            source += "]"

            if decision == "delete":
                new_content, matched = self._remove_sentence(new_content, claim)
                logs.append(
                    {
                        "resource_id": resource_id,
                        "resource_type": resource_type,
                        "issue_index": idx,
                        "severity": "error",
                        "original_text": claim[:300],
                        "corrected_text": (
                            "[已按裁决删除 — 无权威参考支撑]" if matched else "[未能定位待删除语句]"
                        ),
                        "correction_basis": "arbitration",
                        "kb_source": doc_id,
                        "action": "deleted" if matched else "delete_unmatched",
                        "decision": "delete",
                    }
                )
            elif decision == "replace":
                if kb_text:
                    replacement = f"{kb_text} {source}"
                    if claim in new_content:
                        new_content = new_content.replace(claim, replacement, 1)
                        action = "replaced"
                    else:
                        note = (
                            f"\n\n> ⚠️ 更正声明：原文「{claim}」未能定位，"
                            f"按 KB 修正为「{kb_text}」{source}"
                        )
                        if note not in new_content:
                            new_content = (new_content.rstrip() + note).strip()
                        action = "replaced_appended"
                    logs.append(
                        {
                            "resource_id": resource_id,
                            "resource_type": resource_type,
                            "issue_index": idx,
                            "severity": "error",
                            "original_text": claim[:300],
                            "corrected_text": replacement[:300],
                            "correction_basis": "arbitration",
                            "kb_source": doc_id,
                            "action": action,
                            "decision": "replace",
                        }
                    )
                else:
                    # 裁决 replace 但无 KB 原文 → 按 D1 删除（无权威参考）
                    new_content, matched = self._remove_sentence(new_content, claim)
                    logs.append(
                        {
                            "resource_id": resource_id,
                            "resource_type": resource_type,
                            "issue_index": idx,
                            "severity": "error",
                            "original_text": claim[:300],
                            "corrected_text": "[已按 D1 删除：裁决方未提供 KB 原文]",
                            "correction_basis": "arbitration",
                            "kb_source": doc_id,
                            "action": "deleted" if matched else "delete_unmatched",
                            "decision": "delete",
                        }
                    )
            else:  # keep
                new_content, matched = self._append_source_marker(
                    new_content, claim, doc_id, chunk_idx
                )
                logs.append(
                    {
                        "resource_id": resource_id,
                        "resource_type": resource_type,
                        "issue_index": idx,
                        "severity": "info",
                        "original_text": claim[:300],
                        "corrected_text": (
                            f"[保留原文并标注来源 {source}]" if matched else "[未能定位待标注语句]"
                        ),
                        "correction_basis": "arbitration",
                        "kb_source": doc_id,
                        "action": "kept",
                        "decision": "keep",
                    }
                )
        return new_content, logs

    @staticmethod
    def _remove_sentence(content: str, claim: str) -> tuple[str, bool]:
        """删除包含 claim 的整句（纯字符串，不调 LLM）。

        句边界为换行或中英文句末标点；claim 未定位时原样返回。
        """
        if not claim or claim not in content:
            return content, False
        start = content.find(claim)
        i = start - 1
        while i >= 0 and content[i] not in "\n。！？!?":
            i -= 1
        sent_start = i + 1
        # 句尾：claim 若已含句末标点（。！？!?），则句尾即 claim 结束处，
        # 否则向后扫描到本句的结束标点（避免误删相邻下一句）。
        claim_end = start + len(claim)
        if claim_end > 0 and content[claim_end - 1] in "。！？!?":
            sent_end = claim_end
        else:
            j = claim_end
            while j < len(content) and content[j] not in "\n。！？!?":
                j += 1
            sent_end = j
            if sent_end < len(content) and content[sent_end] in "。！？!?":
                sent_end += 1
        return (content[:sent_start] + content[sent_end:]).strip(), True

    @staticmethod
    def _append_source_marker(
        content: str, claim: str, doc_id: str, chunk_index=None
    ) -> tuple[str, bool]:
        """在 claim 后追加来源标注（keep 裁决用）；已标注过则不重复。"""
        if not claim or claim not in content:
            return content, False
        loc = f"（来源：{doc_id}"
        if chunk_index is not None:
            loc += f"，段落 {chunk_index}"
        loc += "）"
        if loc in content:
            return content, True
        return content.replace(claim, claim + loc, 1), True

    def _collect_fact_points(
        self, resource: dict, audit_report: dict, adjudications: list[dict]
    ) -> list[dict]:
        """收集本资源可绑定的事实点（用于【生成陈述 + KB原文出处】溯源）。

        来源优先级：裁决 keep/replace 断言 → 审核 fact_check 中通过校验的断言。
        is_accurate=False 的错误断言已被修正，不作为事实点绑定。
        """
        points = []
        seen = set()

        def add(statement, source_text, doc_id, chunk_index):
            if not statement:
                return
            key = (statement, source_text or "", doc_id or "")
            if key in seen:
                return
            seen.add(key)
            points.append(
                {
                    "statement": statement,
                    "source_text": source_text or "",
                    "doc_id": doc_id or "",
                    "chunk_index": chunk_index,
                }
            )

        for adj in adjudications or []:
            decision = adj.get("decision", "")
            if decision not in ("keep", "replace"):
                continue
            if decision == "replace":
                statement = adj.get("replacement_text") or adj.get("claim")
            else:
                statement = adj.get("claim")
            source = adj.get("evidence") or adj.get("replacement_text") or ""
            add(statement, source, adj.get("doc_id", ""), adj.get("chunk_index"))

        for fc in (audit_report or {}).get("fact_check", {}).get("items", []) or []:
            if fc.get("is_accurate") is False:
                continue
            add(
                fc.get("claim", ""),
                fc.get("evidence_from_kb", ""),
                fc.get("citation_ref", "") or "",
                fc.get("chunk_index"),
            )
        return points

    @staticmethod
    def _format_fact_point(point: dict) -> str:
        """格式化单条事实点溯源行为：【生成陈述】...【KB原文出处】...【来源】..."""
        loc = point.get("doc_id") or ""
        chunk = point.get("chunk_index")
        if loc and chunk is not None:
            loc = f"{loc}#chunk_{chunk}"
        elif not loc:
            loc = "未标注"
        source_part = point.get("source_text") or "暂无权威参考，建议补充学习"
        return f"- 【生成陈述】{point.get('statement')}【KB原文出处】{source_part}【来源】{loc}"

    @staticmethod
    def _bind_traceability(content: str, fact_points: list[dict]) -> tuple[str, list[str]]:
        """追加事实溯源块到讲义/指南内容末尾。返回 (新内容, 绑定行列表)。

        已有溯源块时不重复追加；无事实点时原样返回。
        """
        if not fact_points or "## 事实溯源" in (content or ""):
            return content, []
        lines = [CorrectionAgent._format_fact_point(p) for p in fact_points]
        section = "\n\n## 事实溯源\n" + "\n".join(lines)
        return (content or "").rstrip() + section, lines

    @staticmethod
    def _fact_points_to_citations(fact_points: list[dict]) -> list[dict]:
        """从事实点构建 citations 溯源记录（与 schemas.Citation 对齐）。"""
        cites = []
        seen = set()
        for p in fact_points:
            doc = p.get("doc_id") or ""
            src = p.get("source_text") or ""
            if not doc or not src:
                continue
            key = (doc, src)
            if key in seen:
                continue
            seen.add(key)
            cites.append(
                {
                    "doc_id": doc,
                    "chunk_index": p.get("chunk_index") or 0,
                    "original_text": src,
                    "relevance_score": 1.0,
                }
            )
        return cites

    # ═══════════════════════════════════════════════════════
    # Phase 3：降级模式一致性检查（纯规则，无 KB，不调 LLM）
    # ═══════════════════════════════════════════════════════

    def _downgrade_check(self, resource: dict, diagnosis: dict) -> dict:
        """路径 1：降级模式一致性检查（无 KB，不调 LLM）。

        纯规则检测前后矛盾 / 术语不一致 / 缺失 import / 步骤跳跃，
        只记录 findings 不自动改内容（不做事实判断）。
        """
        content = resource.get("content", "") or ""
        terms = [g.get("topic", "") for g in diagnosis.get("skill_gaps", []) if g.get("topic")]
        issues = self._consistency_check(content, terms)
        logs = []
        for idx, issue in enumerate(issues):
            logs.append(
                {
                    "resource_id": resource.get("resource_id", ""),
                    "resource_type": resource.get("resource_type", "unknown"),
                    "issue_index": idx,
                    "severity": issue.get("severity", "warning"),
                    "original_text": issue.get("detail", ""),
                    "corrected_text": "[降级模式：待人工确认，不做自动修正]",
                    "correction_basis": "consistency_check",
                    "kb_source": None,
                    "action": "detected",
                    "check_type": issue.get("check_type", ""),
                }
            )
        corrected_resource = {
            **resource,
            "_consistency_checked": True,
            "_downgrade_mode": True,
        }
        return {
            "corrected_resource": corrected_resource,
            "logs": logs,
            "consistency": issues,
        }

    def _consistency_check(self, content: str, terms: list[str] | None = None) -> list[dict]:
        """降级模式纯规则一致性检查：四项规则汇总。"""
        terms = terms or []
        issues = []
        issues.extend(self._check_missing_imports(content))
        issues.extend(self._check_step_jumps(content))
        issues.extend(self._check_term_inconsistency(content, terms))
        issues.extend(self._check_contradictions(content, terms))
        return issues

    def _check_missing_imports(self, content: str) -> list[dict]:
        """检测代码块中使用了别名但全文缺少对应 import 语句。"""
        issues = []
        blocks = self._extract_code_blocks(content or "")
        if not blocks:
            return issues
        for alias, (pkg, patterns) in self._ALIAS_IMPORT_MAP.items():
            used = any(re.search(rf"\b{re.escape(alias)}\.\w+", block) for block in blocks)
            if not used:
                continue
            if not any(p in content for p in patterns):
                issues.append(
                    {
                        "check_type": "missing_import",
                        "severity": "warning",
                        "detail": (f"代码使用了 `{alias}.` 但全文未找到 `{pkg}` 的 import 语句"),
                        "location": f"alias `{alias}`",
                    }
                )
        return issues

    @staticmethod
    def _extract_code_blocks(content: str) -> list[str]:
        """提取 Markdown 围栏代码块内容（``` 开头/结尾）。"""
        blocks = []
        in_block = False
        buf = []
        for line in content.split("\n"):
            if line.strip().startswith("```"):
                if in_block:
                    blocks.append("\n".join(buf))
                    buf = []
                    in_block = False
                else:
                    in_block = True
            elif in_block:
                buf.append(line)
        return blocks

    @staticmethod
    def _check_step_jumps(content: str) -> list[dict]:
        """检测编号步骤跳跃（如 1,2,4 → 缺 3）。

        覆盖两种写法：编号列表 "N." 与 "步骤 N" / "Step N"。
        """
        issues = []
        lines = content.split("\n")
        block: list[int] = []

        def flush():
            if len(block) >= 2:
                present = set(block)
                gaps = sorted(set(range(min(block), max(block) + 1)) - present)
                if gaps:
                    issues.append(
                        {
                            "check_type": "step_jump",
                            "severity": "warning",
                            "detail": (
                                f"步骤编号跳跃，缺少第 {', '.join(map(str, gaps))} 步 "
                                f"（当前顺序: {block}）"
                            ),
                            "location": f"行序 {block}",
                        }
                    )
            block.clear()

        for line in lines:
            m = re.match(r"^\s*(\d+)[.、．:：)]\s*\S", line)
            if m:
                block.append(int(m.group(1)))
            else:
                flush()
        flush()

        # "步骤 N" 写法
        step_nums = [int(x) for x in re.findall(r"(?:步骤|step)\s*(\d+)", content, re.IGNORECASE)]
        if len(step_nums) >= 2:
            gaps = sorted(set(range(min(step_nums), max(step_nums) + 1)) - set(step_nums))
            if gaps:
                issues.append(
                    {
                        "check_type": "step_jump",
                        "severity": "warning",
                        "detail": f"步骤编号跳跃，缺少第 {', '.join(map(str, gaps))} 步",
                        "location": f"步骤序列 {step_nums}",
                    }
                )
        return issues

    @staticmethod
    def _check_term_inconsistency(content: str, terms: list[str]) -> list[dict]:
        """检测含字母术语的大小写/拼写不一致写法（如 LangGraph vs langgraph）。"""
        issues = []
        for term in terms:
            if not term or not isinstance(term, str) or not re.search(r"[A-Za-z]", term):
                continue
            spellings = {m.group(0) for m in re.finditer(re.escape(term), content, re.IGNORECASE)}
            if len(spellings) > 1:
                issues.append(
                    {
                        "check_type": "term_inconsistency",
                        "severity": "warning",
                        "detail": (f"术语 `{term}` 存在不一致写法: {', '.join(sorted(spellings))}"),
                        "location": term,
                    }
                )
        return issues

    @staticmethod
    def _check_contradictions(content: str, terms: list[str]) -> list[dict]:
        """启发式前后矛盾检测：同一段内同一术语同时出现肯定与否定表述。

        仅标记"疑似矛盾"供人工复核，不自动改内容。
        """
        issues = []
        paragraphs = re.split(r"\n\s*\n", content)
        for pid, para in enumerate(paragraphs):
            if not para.strip():
                continue
            sentences = [s.strip() for s in re.split(r"[。！？!?]+|\n", para) if s.strip()]
            for term in terms:
                if not term or not isinstance(term, str):
                    continue
                tl = term.lower()
                hit = [s for s in sentences if tl in s.lower()]
                if len(hit) < 2:
                    continue
                negative = [s for s in hit if any(c in s for c in CorrectionAgent._NEGATIVE_CUES)]
                positive = [
                    s
                    for s in hit
                    if not any(c in s for c in CorrectionAgent._NEGATIVE_CUES)
                    and any(c in s for c in CorrectionAgent._POSITIVE_CUES)
                ]
                if negative and positive:
                    issues.append(
                        {
                            "check_type": "contradiction",
                            "severity": "warning",
                            "detail": (
                                f"段落 {pid + 1} 中术语 `{term}` 同时出现肯定与否定表述，"
                                f"疑似前后矛盾"
                            ),
                            "location": f"段落 {pid + 1}",
                            "evidence": {
                                "positive": positive[0][:80],
                                "negative": negative[0][:80],
                            },
                        }
                    )
        return issues


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
            "summary": "系统入门工业机器人示教编程与故障诊断",
            "recommended_difficulty": "intermediate",
            "learning_style": "practice_first",
            "skill_gaps": [
                {
                    "priority": "critical",
                    "topic": "SRVO-068 数据传输故障",
                    "current_level": 0.3,
                    "target_level": 0.9,
                    "reason": "不清楚示教器与主机间通信链路排查顺序",
                },
            ],
        },
        "generated_resources": [
            {
                "resource_id": "res-001",
                "resource_type": "guide",
                "title": "SRVO-068 故障排查指南",
                "content": (
                    "# SRVO-068 故障排查指南\\n\\n"
                    "SRVO-068 是 ABB 机器人伺服报警。\\n\\n"
                    "## 步骤 1：检查通信链路\\n"
                    "先断电，再检查示教器与主机间的电缆连接。\\n"
                ),
                "difficulty_level": "beginner",  # 与诊断难度不符，应被画像校验纠正
                "citations": [],
                "key_takeaways": ["定位 SRVO-068 报警", "掌握通信链路排查"],
            },
        ],
        "audit_result": [
            {
                "verdict": "needs_revision",
                "issues": [
                    {
                        "severity": "error",
                        "detail": "SRVO-068 是 FANUC 的数据传输故障代码，不是 ABB 伺服报警",
                        "kb_evidence": "FANUC 手册：SRVO-068 表示数据传输故障",
                    },
                    {
                        "severity": "warning",
                        "detail": "缺少通信链路排查的完整步骤（供电→电缆→参数→复位）",
                    },
                ],
            },
        ],
        "retrieved_chunks": [
            {
                "doc_id": "fanuc_srvo068.md",
                "chunk_index": 2,
                "content": (
                    "FANUC 手册：SRVO-068 表示数据传输故障，"
                    "需检查示教器与主机间的通信链路。"
                ),
                "relevance_score": 0.95,
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

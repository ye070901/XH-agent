"""
Agent 3: 内容审核 Agent — KB 逐条比对版（Phase 3）
══════════════════════════════════════════════════════════
只审不修。拿到 Agent 2 生成的资源 + Agent 1 的诊断，把资源拆成一条条
"事实断言"，逐条与知识库原文比对，输出四态裁决报告。

对应 PHASE3_PLAN.md §4.6（K2 交付标准）：
  提取资源中每条"事实断言" → 逐条比对 KB 原文 → 四态输出
    - accurate            知识库原文支持该断言（核心事实与次要细节均匹配）
    - partially_supported 核心事实被原文支持，仅次要修饰/参数/同义转述细节缺失
    - hallucination       知识库原文反驳该断言（事实错误，须修正/替换为原文）
    - unverifiable        知识库无对应原文，核心事实无法验证（无权威参考，按 D1 删除）

权威等级 A>B 加权（对应 D3）：
  A 级 = 一手原文（官方手册/说明书/规格书等）
  B 级 = 二手资料（教程/课程/指南/社区整理等）
  冲突时以更高权威等级为准；同权威冲突按"反驳优先"（审核从严）。
  最终裁决为纯代码规则（不调 LLM），避免第二层幻觉。

无 KB 模式（downgrade_mode=True，对应 4.6「无 KB 模式」）：
  不做 KB 比对，改为内部一致性检查（前后矛盾 / 术语不一致 / 步骤跳跃）。
"""

from __future__ import annotations

import asyncio
import re

from ..config import settings
from ..knowledge.store import knowledge_base
from .base import BaseAgent

# ═══════════════════════════════════════════════════════════
# 权威等级常量 + 关键词推断
# ═══════════════════════════════════════════════════════════

AUTHORITY_A = "A"  # 一手原文（官方）
AUTHORITY_B = "B"  # 二手资料
AUTHORITY_UNKNOWN = "unknown"

# A 级（一手原文）关键词：官方手册 / 说明书 / 规格书等
_A_LEVEL_KEYWORDS = (
    "官方",
    "手册",
    "说明书",
    "操作手册",
    "参考手册",
    "用户指南",
    "规格",
    "规格书",
    "技术参数",
    "datasheet",
    "manual",
    "specification",
    "official",
)
# B 级（二手资料）关键词：教程 / 课程 / 指南 / 社区整理等
_B_LEVEL_KEYWORDS = (
    "课程",
    "教程",
    "指南",
    "入门",
    "概述",
    "简介",
    "在线",
    "社区",
    "博客",
    "tutorial",
    "course",
    "guide",
    "blog",
    "community",
    "intro",
    "overview",
)

# 每条资源最多提取的断言数（对应 D4 终止边界，控制 LLM 调用与延迟）
MAX_CLAIMS_PER_RESOURCE = 8
# 每条断言最多检索的 KB 原文条数（召回失败→unverifiable 的主因，适当调大）
KB_TOP_K_PER_CLAIM = 5
# 逐条比对时，是否复用流水线已检索的 retrieved_chunks（默认复用）
REUSE_RETRIEVED_CHUNKS = True
# 调试日志中检索片段内容的打印长度上限（便于观察召回，又不刷爆日志）
_LOG_CONTENT_CHARS = 200

# 规则兜底比对：claim 关键词在 KB 原文中的覆盖率阈值（≥ 此值判"部分支持"）
_RULE_SUPPORT_THRESHOLD = 0.5
# 规则兜底比对：覆盖率 ≥ 此值判"完整支持"（核心事实与细节全部逐字命中 → accurate）
_RULE_COMPLETE_THRESHOLD = 1.0
# 规则兜底覆盖等级权重（用于多级降级取最高等级）
_RULE_LEVEL_RANK = {"none": 0, "partial": 1, "full": 2}
# 规则兜底反驳：命中否定词的最小集合（仅作辅助弱参考：须先有支撑命中才判反驳，
# 不单独驱动降级——核心事实已覆盖时不会因否定词缺失细节而被一步降级）
_NEGATION_MARKERS = (
    "不",
    "不是",
    "并非",
    "错误",
    "不正确",
    "无",
    "没有",
    "禁止",
    "避免",
    "不可",
    "不能",
    "应避免",
    "不推荐",
)

SYSTEM_PROMPT = """你是一个严格的内容审核专家，负责把学习资源拆解为"事实断言"并逐条
与知识库原文比对，只审不修。

你的任务分两步：
1. 提取事实断言：从资源内容中识别所有可验证的事实性断言
（技术名词、参数、型号、步骤、因果、配置关系等），忽略纯过渡性/修辞性语句。
2. 逐条比对知识库原文：对每条断言，从给定的知识库原文片段中寻找"支撑"或"反驳"的证据。

裁决四态（最终由代码按权威等级裁决，你只需填证据）：
- accurate            知识库原文明确支持该断言（核心事实与次要细节均匹配）
- partially_supported 核心事实被原文支持，但次要修饰/参数/同义转述细节未逐字匹配
- hallucination       知识库原文明确反驳该断言（事实错误）
- unverifiable        知识库原文没有覆盖该断言的核心事实，无法验证

硬性底线：只要断言的核心业务事实被知识库原文覆盖，无论多少次要细节缺失，
禁止直接输出 unverifiable——最多判定 partially_supported；只有核心事实无原文
依据时才允许落 unverifiable。

权威等级 A>B 加权：每条知识库原文已标注权威等级（A=一手原文/官方，B=二手/教程）。
你输出时必须把"支撑证据"和"反驳证据"分别归入 A 级、B 级四类字段（无则填 null），
并额外给出 support_complete 与 missing_detail 两个字段，代码会按 A>B 规则做最终裁决。
切勿把 A 级证据错填到 B 级字段。
若知识库原文明确反驳断言（如"并非/不是/不支持/与...无关/错误"），必须把反驳原文
填入 contradict 槽（contradict_a/contradict_b），严禁只写进 explanation；有反驳时
support 槽必须为 null。

输出必须为严格的 JSON 格式。"""


class AuditAgent(BaseAgent):
    """内容审核 Agent — KB 逐条比对（只审不修）。"""

    REQUIRED_STATE_KEYS = {"generated_resources", "diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "learner_data",
        "task_id",
        "agent_log",
        "status",
        "resource_types",
        "retrieved_chunks",
        "downgrade_mode",
        "diagnosis_completed",
        "generation_errors",
    }

    def __init__(self) -> None:
        super().__init__(
            name="审核Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=settings.LLM_TEMPERATURE_AUDIT,  # 0.1 低温，保证判断一致
        )

    # ═══════════════════════════════════════════════════════════
    # 主流程
    # ═══════════════════════════════════════════════════════════

    async def process(self, state: dict) -> dict:
        """逐资源执行 KB 逐条比对。

        Returns:
            dict: {"audit_result": list[dict]}，每个元素为单资源审核报告。
        """
        resources = state.get("generated_resources", [])
        diagnosis = state.get("diagnosis_result", {})
        downgrade_mode = bool(state.get("downgrade_mode", False))
        retrieved_chunks = state.get("retrieved_chunks", []) or []

        audit_results: list[dict] = []
        for i, resource in enumerate(resources):
            try:
                report = await self._audit_one(
                    i, resource, diagnosis, downgrade_mode, retrieved_chunks
                )
            except Exception as e:  # 单资源失败不阻断整批审核
                self.log(f"资源 {i} 审核异常 ({type(e).__name__})，使用兜底报告")
                report = self._fallback_report(i, resource, str(e))
            audit_results.append(report)

        self.log(f"审核完成: {len(audit_results)} 个资源")
        return {"audit_result": audit_results}

    # ═══════════════════════════════════════════════════════════
    # 单资源审核
    # ═══════════════════════════════════════════════════════════

    async def _audit_one(
        self,
        index: int,
        resource: dict,
        diagnosis: dict,
        downgrade_mode: bool,
        retrieved_chunks: list[dict],
    ) -> dict:
        """审核单个资源：无 KB 模式走一致性检查，否则走 KB 逐条比对。"""
        if downgrade_mode:
            return await self._audit_consistency(index, resource)

        # 1. 提取事实断言
        claims = await self._extract_claims(index, resource)

        # 2. 逐条检索 KB 原文，汇总为证据池（带权威等级）
        evidence_pool = await self._collect_evidence(claims, retrieved_chunks)

        # 3. 逐条比对（LLM 语义判断 + 代码权威裁决）
        items = await self._classify_claims(claims, evidence_pool)

        # 4. 汇总为审核报告（四态 → verdict + issues，向后兼容）
        return self._build_report(index, resource, items)

    async def _audit_consistency(self, index: int, resource: dict) -> dict:
        """无 KB 模式：内部一致性检查（不比对 KB）。"""
        content = str(resource.get("content") or "")
        issues = self._consistency_checks(content, index, resource)

        items = [
            {
                "claim": iss["detail"],
                "citation_ref": None,
                "verdict": "unverifiable",
                "is_accurate": None,
                "evidence_from_kb": None,
                "authority_level": None,
                "explanation": "无 KB 模式：无法比对原文，仅做内部一致性检查",
            }
            for iss in issues
        ]
        return self._build_report(index, resource, items, issues=issues, no_kb=True)

    # ═══════════════════════════════════════════════════════════
    # 1. 提取事实断言
    # ═══════════════════════════════════════════════════════════

    async def _extract_claims(self, index: int, resource: dict) -> list[str]:
        """提取资源中的事实断言（LLM 提取 + 规则兜底）。"""
        content = str(resource.get("content") or "")
        resource_type = str(resource.get("resource_type") or "")
        title = str(resource.get("title") or "")

        prompt = f"""## 待审核资源
- 编号：{index}
- 类型：{resource_type}
- 标题：{title}

## 内容
{content[:4000]}

## 任务
从内容中提取可验证的"事实断言"（技术名词、参数、型号、步骤、因果、配置关系等），
最多 {MAX_CLAIMS_PER_RESOURCE} 条，忽略纯过渡性/修辞性语句。

仅输出纯 JSON（不要 markdown 代码块）：
{{"claims": ["断言1", "断言2", "..."]}}"""

        try:
            result = await self.call_llm_json(prompt)
        except Exception as e:
            self.log(f"资源 {index} 断言提取 LLM 异常 ({type(e).__name__})，规则兜底")
            result = {}

        claims = result.get("claims") if isinstance(result, dict) else None
        if not isinstance(claims, list) or not claims:
            claims = self._fallback_extract_claims(content)

        # 归一化 + 去重 + 截断
        cleaned: list[str] = []
        seen: set[str] = set()
        for c in claims:
            c = str(c).strip()
            if not c or c in seen:
                continue
            seen.add(c)
            cleaned.append(c)
            if len(cleaned) >= MAX_CLAIMS_PER_RESOURCE:
                break
        return cleaned

    def _fallback_extract_claims(self, content: str) -> list[str]:
        """规则兜底：按句子边界切分，过滤过短/纯标题句。"""
        # 去掉 markdown 标题、代码块、链接、引用块
        text = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
        text = re.sub(r"^#{1,6}\s+.*$", " ", text, flags=re.MULTILINE)
        text = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", text)
        # 引用块（难度/风格/摘要/安全提示等元数据与警示标注）不是可验证事实断言，剔除
        text = re.sub(r"^[ \t]*>.*$", " ", text, flags=re.MULTILINE)

        sentences = [s.strip() for s in re.split(r"[。！？!?\n]+", text) if s.strip()]
        claims = [s for s in sentences if len(s) >= 8]
        return claims[:MAX_CLAIMS_PER_RESOURCE]

    # ═══════════════════════════════════════════════════════════
    # 2. 收集 KB 证据（逐条检索 + 复用 retrieved_chunks）
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _strip_doc_metadata(text: str) -> str:
        """剥掉 KB chunk 开头的文档元数据头（# 标题 + - **key**：value + --- + ## 正文）。

        仅当 chunk 以「# 标题」开头、且其后紧跟元数据 bullet 行时才剥离；
        正文 chunk（以 ### 小节标题或正文段落开头）原样保留，避免误删小节标题。
        这样证据（support/contradict）不再夹带文档自身的来源/日期/摘要元数据。
        """
        lines = str(text or "").split("\n")
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines) or not re.match(r"^\s*#\s+", lines[i]):
            return text  # 非文档标题开头，不动
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines) or not re.match(r"^\s*-\s*\*\*[^*]+\*\*\s*[：:]", lines[i].strip()):
            return text  # 标题后不是元数据行 → 是正文标题，不动
        while i < len(lines) and re.match(r"^\s*-\s*\*\*[^*]+\*\*\s*[：:]", lines[i].strip()):
            i += 1
        while i < len(lines):
            s = lines[i].strip()
            if not s or re.match(r"^---+\s*$", s) or re.match(r"^##\s*正文\s*$", s):
                i += 1
            else:
                break
        return "\n".join(lines[i:]).strip()

    async def _collect_evidence(
        self, claims: list[str], retrieved_chunks: list[dict]
    ) -> list[dict]:
        """对每条断言检索 KB，与 retrieved_chunks 合并去重，附加权威等级。"""
        pool: dict[tuple, dict] = {}

        def _add(chunk: dict) -> None:
            if not isinstance(chunk, dict):
                return
            content = self._strip_doc_metadata(str(chunk.get("content") or "")).strip()
            if not content:
                return
            key = (
                str(chunk.get("doc_id") or ""),
                str(chunk.get("chunk_index") or ""),
                content[:60],
            )
            if key not in pool:
                pool[key] = {
                    "doc_id": chunk.get("doc_id", ""),
                    "doc_title": chunk.get("doc_title", ""),
                    "content": content,
                    "authority": self._infer_authority(chunk),
                }

        # 复用流水线已检索的 retrieved_chunks
        if REUSE_RETRIEVED_CHUNKS:
            for chunk in retrieved_chunks:
                _add(chunk)

        # 逐条检索（并行），失败静默降级
        async def _search_one(claim: str) -> list[dict]:
            try:
                return await knowledge_base.search(claim, top_k=KB_TOP_K_PER_CLAIM)
            except Exception:
                return []

        try:
            per_claim_results = await asyncio.gather(
                *[_search_one(c) for c in claims], return_exceptions=True
            )
        except Exception:
            per_claim_results = []

        # 调试日志：逐 claim 打印本次检索命中的 KB 片段，诊断「召回失败→unverifiable」
        self._log_retrieval(claims, per_claim_results)

        for result in per_claim_results:
            if isinstance(result, list):
                for chunk in result:
                    _add(chunk)

        return list(pool.values())

    def _log_retrieval(self, claims: list[str], per_claim_results: list) -> None:
        """打印每条断言本次检索拿到的 KB 片段（doc_id/title/score/content 摘要）。"""
        for i, claim in enumerate(claims):
            results = per_claim_results[i] if i < len(per_claim_results) else None
            if not isinstance(results, list) or not results:
                self.log(f"[检索] claim[{i}]={claim[:60]!r} → 命中 0 片段")
                continue
            self.log(f"[检索] claim[{i}]={claim[:60]!r} → 命中 {len(results)} 片段")
            for r in results:
                self.log(
                    f"    [检索] {r.get('doc_id', '?')}#{r.get('chunk_index', '?')} "
                    f"score={r.get('relevance_score')} title={str(r.get('doc_title', ''))[:30]!r} "
                    f"content={str(r.get('content', ''))[:_LOG_CONTENT_CHARS]!r}"
                )

    # ═══════════════════════════════════════════════════════════
    # 3. 逐条比对（LLM 语义判断 → 代码权威裁决）
    # ═══════════════════════════════════════════════════════════

    async def _classify_claims(self, claims: list[str], evidence_pool: list[dict]) -> list[dict]:
        """逐条比对 KB：LLM 填支撑/反驳证据，代码按 A>B 裁决三态。"""
        if not claims:
            return []

        llm_items = await self._llm_classify(claims, evidence_pool)

        resolved: list[dict] = []
        for i, claim in enumerate(claims):
            # 优先取 LLM 结果，缺失/失败时规则兜底
            raw = llm_items[i] if i < len(llm_items) else None
            if not isinstance(raw, dict) or not any(
                raw.get(k) for k in ("support_a", "support_b", "contradict_a", "contradict_b")
            ):
                raw = self._fallback_classify(claim, evidence_pool)

            # 兜底修正：LLM 仅写 explanation 未填反驳槽时，规则补齐 contradict 证据
            raw = self._backfill_contradict(claim, evidence_pool, raw)

            verdict = self._resolve_verdict(claim, evidence_pool, raw)
            item = self._build_item(claim, verdict, raw)
            resolved.append(item)
            self.log(
                f"[裁决] claim[{i}]={claim[:60]!r} → {verdict} "
                f"evidence={str(item.get('evidence_from_kb') or '')[:80]!r}"
            )

        return resolved

    async def _llm_classify(self, claims: list[str], evidence_pool: list[dict]) -> list[dict]:
        """LLM 逐条比对（一次调用批量完成），返回未裁决的原始证据分类。"""
        if not evidence_pool:
            return []

        evidence_block = self._fmt_evidence(evidence_pool)
        claims_block = "\n".join(f"- [{i}] {c}" for i, c in enumerate(claims))

        prompt = f"""## 待审核断言（编号见下方）
{claims_block}

## 知识库原文（已标注权威等级）
{evidence_block}

## 任务
逐条比对：对每条断言，从知识库原文中寻找"支撑"和"反驳"证据，
分别归入 A 级（一手原文/官方）与 B 级（二手/教程）四类字段，无证据填 null。

在证据槽之外，还需对每条断言给出完整度判定：
- support_complete（bool）：支撑证据是否完整覆盖断言的每一项内容
  （核心业务事实 + 次要修饰/参数/同义转述细节均命中 → true）
- missing_detail（"core" 或 "minor"）：缺失部分属于——
  core = 核心业务事实无原文依据；minor = 仅次要修饰/参数/同义转述细节未逐字匹配
硬性底线：核心事实已被原文覆盖时，缺失的只能标 minor，禁止整体判 unverifiable；
只有核心事实无原文依据时才标 core。
注意：表述/用词未逐字一致、原文未逐字写出相同句式，都不算 core 缺失；只要核心
业务事实能在知识库原文片段中找到依据（含跨多个片段拼接），就视为 core 已覆盖。
若某条断言被知识库原文明确反驳（如"并非/不是/不支持/与...无关/错误"），必须把
反驳原文填入 contradict_a/contradict_b，严禁只写进 explanation；此时 support 槽
必须为 null，support_complete=false、missing_detail="core"。

仅输出纯 JSON（不要 markdown 代码块）：
{{"claims": [
  {{
    "index": 0,
    "claim": "断言原文",
    "support_a": "A级支撑原文（逐字摘录，无则 null）",
    "support_b": "B级支撑原文（无则 null）",
    "contradict_a": "A级反驳原文（无则 null）",
    "contradict_b": "B级反驳原文（无则 null）",
    "support_complete": true,
    "missing_detail": "core",
    "explanation": "一句话说明"
  }}
]}}

规则：
- 只摘录原文，不要改写；确实无证据的字段填 null
- 同一条 KB 原文不能同时填进支撑与反驳
- A 级证据必须来自标注 [A] 的原文，B 级同理，严禁混淆
- 无任何支撑证据时 support_complete=false 且 missing_detail="core"
- 有反驳证据时严禁只写进 explanation，必须填入 contradict 槽"""

        try:
            result = await self.call_llm_json(prompt)
        except Exception as e:
            self.log(f"逐条比对 LLM 异常 ({type(e).__name__})，规则兜底")
            return []

        items = result.get("claims") if isinstance(result, dict) else None
        if not isinstance(items, list):
            return []
        # 按 index 归位
        ordered: dict[int, dict] = {}
        for it in items:
            if isinstance(it, dict):
                idx = it.get("index")
                if isinstance(idx, int):
                    ordered[idx] = it
        return [ordered.get(i, {}) for i in range(len(claims))]

    # ── 权威裁决（纯代码规则，不调 LLM）──

    def _resolve_verdict(self, claim: str, evidence_pool: list[dict], item: dict) -> str:
        """按权威等级 A>B + 完整度两级降级裁决四态。

        对应 D3：冲突取更高权威，同权威反驳优先；有支撑证据时按
        support_complete / missing_detail 两级降级（accurate →
        partially_supported → unverifiable），核心事实缺失才触达底线。
        """
        support_a = item.get("support_a")
        support_b = item.get("support_b")
        contradict_a = item.get("contradict_a")
        contradict_b = item.get("contradict_b")

        if contradict_a:  # A 级一手原文反驳 → 最高权威，直接判幻觉
            return "hallucination"
        if support_a:  # A 级一手原文支持 → 进入完整度两级降级
            return self._resolve_support_grade(claim, evidence_pool, item)
        if contradict_b:  # B 级反驳（无 A 级覆盖）
            return "hallucination"
        if support_b:  # B 级支持 → 进入完整度两级降级
            return self._resolve_support_grade(claim, evidence_pool, item)
        return "unverifiable"  # 无任何覆盖

    def _resolve_support_grade(self, claim: str, evidence_pool: list[dict], item: dict) -> str:
        """有支撑证据时的两级降级：core 缺失 → unverifiable；minor 缺失 → partially_supported。

        硬性底线：只要核心事实被原文覆盖，最多降到 partially_supported，
        禁止一步降到 unverifiable。向后兼容：LLM 未返回 support_complete /
        missing_detail 新字段时，有支撑证据即判 accurate，保持旧行为，不误伤。

        跨 chunk 合并覆盖兜底：LLM 标 missing_detail="core"（核心缺失）时，
        不直接落 unverifiable，先用规则对全证据池做跨 chunk 合并覆盖率判定——
        若跨块合并后覆盖率达标（core 已被拼接支撑），说明是单块切散导致的漏判，
        降级为 partially_supported 而非 unverifiable。
        """
        support_complete = item.get("support_complete")
        missing_detail = str(item.get("missing_detail") or "").strip().lower()
        if support_complete is not None:
            if support_complete is True:
                return "accurate"
            # support_complete=False：按缺失级别降级，仅核心事实缺失才落 unverifiable
            if missing_detail == "core":
                # 兜底：规则跨 chunk 合并覆盖判定，缓解"片段切散→误判 core 缺失"
                if self._rule_support_level_merged(claim, evidence_pool) == "partial":
                    return "partially_supported"
                return "unverifiable"
            return "partially_supported"
        # LLM 未返回新字段 → 向后兼容：有支撑证据即 accurate
        return "accurate"

    def _rule_support_level_merged(self, claim: str, evidence_pool: list[dict]) -> str:
        """跨 chunk 合并覆盖率判定：允许跨多个证据片段拼接支撑核心事实。

        单块覆盖率可能因切片把一段事实切散而不足阈值；合并后按"关键词去重命中数 /
        关键词总数"计算整体覆盖率，缓解单块 cut 导致的 core 误判。
        """
        tokens = self._extract_tokens(claim)
        if not tokens:
            return "none"
        merged_text = self._normalize(
            " ".join(str(ev.get("content") or "") for ev in evidence_pool)
        )
        hits = sum(1 for t in tokens if t in merged_text)
        ratio = hits / len(tokens)
        if ratio >= _RULE_COMPLETE_THRESHOLD:
            return "full"
        if ratio >= _RULE_SUPPORT_THRESHOLD:
            return "partial"
        return "none"

    def _backfill_contradict(self, claim: str, evidence_pool: list[dict], item: dict) -> dict:
        """兜底修正反驳证据槽：LLM 未填 contradict 但规则判定原文反驳时补齐。

        仅当四个证据槽全空（LLM 既没填支撑也没填反驳，只在 explanation 里说明）
        时才触发；用规则在证据池里找同时含 claim 关键词与否定词的原文填进反驳槽，
        避免"明确被反驳却因证据槽未填而误判 unverifiable"的边缘 case。
        """
        out = dict(item or {})
        if any(out.get(k) for k in ("support_a", "support_b", "contradict_a", "contradict_b")):
            return out  # LLM 已填证据槽，不覆盖
        for ev in evidence_pool:
            text = str(ev.get("content") or "")
            if self._rule_contradict(claim, text):
                auth = ev.get("authority") or AUTHORITY_B
                slot = "contradict_a" if auth == AUTHORITY_A else "contradict_b"
                if not out.get(slot):
                    out[slot] = text[:300]
                    out["support_complete"] = False
                    out["missing_detail"] = "core"
                    out["explanation"] = "证据槽补齐：原文明确反驳（规则兜底）"
        return out

    def _build_item(self, claim: str, verdict: str, raw: dict) -> dict:
        """构建单条断言的比对结果。"""
        evidence = ""
        authority = None
        if verdict == "hallucination":
            evidence = str(raw.get("contradict_a") or raw.get("contradict_b") or "")
            authority = AUTHORITY_A if raw.get("contradict_a") else AUTHORITY_B
        elif verdict in ("accurate", "partially_supported"):
            # partially_supported 亦属支撑证据（核心事实成立），取 support 槽位
            evidence = str(raw.get("support_a") or raw.get("support_b") or "")
            authority = AUTHORITY_A if raw.get("support_a") else AUTHORITY_B
        if not evidence:
            authority = None

        return {
            "claim": claim,
            "citation_ref": raw.get("citation_ref"),
            "verdict": verdict,
            "is_accurate": True
            if verdict == "accurate"
            else (False if verdict == "hallucination" else None),
            "evidence_from_kb": evidence or None,
            "authority_level": authority,
            "explanation": str(raw.get("explanation") or ""),
        }

    # ═══════════════════════════════════════════════════════════
    # 规则兜底比对（演示模式 / LLM 失败）
    # ═══════════════════════════════════════════════════════════

    def _fallback_classify(self, claim: str, evidence_pool: list[dict]) -> dict:
        """规则兜底：关键词覆盖率分完整/部分/无支持三级，否定词仅作辅助弱参考。"""
        out: dict = {
            "claim": claim,
            "support_a": None,
            "support_b": None,
            "contradict_a": None,
            "contradict_b": None,
            "support_complete": False,
            "missing_detail": "minor",
            "explanation": "规则兜底比对（关键词覆盖）",
        }
        best_level = "none"
        for ev in evidence_pool:
            text = str(ev.get("content") or "")
            level = self._rule_support_level(claim, text)
            contradicts = self._rule_contradict(claim, text)
            if contradicts and level != "none":
                level = "none"  # 同 chunk 既支持又反驳 → 反驳优先
            auth = ev.get("authority") or AUTHORITY_B
            slot = None
            if level != "none":
                slot = "support_a" if auth == AUTHORITY_A else "support_b"
                if _RULE_LEVEL_RANK[level] > _RULE_LEVEL_RANK[best_level]:
                    best_level = level
            elif contradicts:
                slot = "contradict_a" if auth == AUTHORITY_A else "contradict_b"
            if slot and not out[slot]:
                out[slot] = text[:300]
        # 单块均低于支持阈值时，跨 chunk 合并覆盖兜底（缓解"片段切散→单块覆盖率不足"）
        merged_level = self._rule_support_level_merged(claim, evidence_pool)
        if best_level == "none" and merged_level == "partial":
            best_level = "partial"
            # 拼接近邻几块作为合并支撑证据（取权威最高块填充）
            merged_slot = None
            for ev in evidence_pool:
                auth = ev.get("authority") or AUTHORITY_B
                slot = "support_a" if auth == AUTHORITY_A else "support_b"
                if slot not in out or not out.get(slot):
                    out[slot] = str(ev.get("content") or "")[:300]
                    merged_slot = slot
                    break
            if merged_slot:
                out["explanation"] = "规则兜底比对（跨 chunk 合并覆盖）"

        # 按最高覆盖等级设置完整度字段，供两级降级使用
        if best_level == "full":
            out["support_complete"] = True
            out["missing_detail"] = "minor"
        elif best_level == "partial":
            out["support_complete"] = False
            # 规则兜底无法区分核心/次要缺失，按硬性底线保守标 minor
            # （核心事实被部分覆盖时禁止一步降 unverifiable，最多 partially_supported）
            out["missing_detail"] = "minor"
        else:
            out["support_complete"] = False
            out["missing_detail"] = "core"  # 无任何覆盖 → 核心事实无原文依据
        return out

    def _rule_support_level(self, claim: str, text: str) -> str:
        """规则支持等级：full(完整覆盖) / partial(部分覆盖) / none(低于支持阈值)。"""
        tokens = self._extract_tokens(claim)
        if not tokens:
            return "none"
        normalized_text = self._normalize(text)
        hits = sum(1 for t in tokens if t in normalized_text)
        ratio = hits / len(tokens)
        if ratio >= _RULE_COMPLETE_THRESHOLD:
            return "full"
        if ratio >= _RULE_SUPPORT_THRESHOLD:
            return "partial"
        return "none"

    def _rule_support(self, claim: str, text: str) -> bool:
        """规则支持判定（bool）：覆盖率 ≥ 支持阈值即认为有支撑（供反驳辅助判断）。"""
        return self._rule_support_level(claim, text) != "none"

    def _rule_contradict(self, claim: str, text: str) -> bool:
        """规则反驳判定：claim 关键词出现在原文中，且原文含否定词。"""
        if not self._rule_support(claim, text):
            return False
        return any(marker in text for marker in _NEGATION_MARKERS)

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", "", str(text).lower())

    def _extract_tokens(self, text: str) -> set[str]:
        """提取比对关键词：英文单词 + 中文双字 bigram。"""
        normalized = self._normalize(text)
        tokens: set[str] = set()
        tokens.update(re.findall(r"[a-z0-9]{2,}", normalized))
        cjk = re.sub(r"[^一-龥]", "", normalized)
        for i in range(len(cjk) - 1):
            tokens.add(cjk[i : i + 2])
        return {t for t in tokens if len(t) >= 2}

    # ═══════════════════════════════════════════════════════════
    # 无 KB 模式：内部一致性检查
    # ═══════════════════════════════════════════════════════════

    def _consistency_checks(self, content: str, index: int, resource: dict) -> list[dict]:
        """降级模式一致性检查：前后矛盾 / 术语不一致 / 步骤跳跃。"""
        issues: list[dict] = []

        # 前后矛盾：同一技术名词同时出现"必须/禁止"或数值冲突
        terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", content))
        for term in terms:
            if re.search(
                rf"{re.escape(term)}[^\n]{{0,30}}(禁止|不可|不能|不要)", content
            ) and re.search(rf"{re.escape(term)}[^\n]{{0,30}}(必须|务必|应当|需要)", content):
                issues.append(
                    {
                        "severity": "warning",
                        "detail": f"术语「{term}」前后表述可能矛盾（既要求又禁止）",
                        "kb_evidence": "",
                    }
                )

        # 步骤跳跃：出现"步骤 1 → 步骤 3"却缺步骤 2（启发式）
        step_nums = [int(m) for m in re.findall(r"步骤\s*(\d+)", content)]
        if step_nums and max(step_nums) > 1:
            missing = [n for n in range(1, max(step_nums) + 1) if n not in step_nums]
            if missing:
                issues.append(
                    {
                        "severity": "warning",
                        "detail": f"操作步骤可能跳跃，缺少步骤 {missing}",
                        "kb_evidence": "",
                    }
                )

        if not issues and content.strip():
            issues.append(
                {
                    "severity": "info",
                    "detail": "无 KB 模式：已做一致性检查，未发现明显矛盾",
                    "kb_evidence": "",
                }
            )
        return issues

    # ═══════════════════════════════════════════════════════════
    # 汇总报告（三态 → verdict + issues，向后兼容旧契约）
    # ═══════════════════════════════════════════════════════════

    def _build_report(
        self,
        index: int,
        resource: dict,
        items: list[dict],
        issues: list[dict] | None = None,
        no_kb: bool = False,
    ) -> dict:
        """由四态比对结果构建单资源审核报告。

        兼容 correction.py（读 issues + fact_check.items）与
        evaluation/metrics.py（读 fact_check.items[].verdict）。
        """
        resource_type = str(resource.get("resource_type") or "")
        title = str(resource.get("title") or "")

        if issues is None:
            issues = []
            flags = []
            for it in items:
                v = it.get("verdict")
                if v == "hallucination":
                    issues.append(
                        {
                            "severity": "error",
                            "detail": f"事实错误：{it.get('claim', '')}",
                            "kb_evidence": it.get("evidence_from_kb") or "",
                        }
                    )
                    flags.append(
                        {
                            "location": it.get("claim", "")[:80],
                            "description": it.get("explanation", "") or "与知识库原文相悖",
                            "severity": "major",
                            "suggested_correction": (it.get("evidence_from_kb") or "")[:300]
                            or None,
                        }
                    )
                elif v == "unverifiable":
                    issues.append(
                        {
                            "severity": "warning",
                            "detail": f"无权威参考：{it.get('claim', '')}",
                            "kb_evidence": "",
                        }
                    )
                elif v == "partially_supported":
                    # 核心事实成立：不产生 error 级 issue，仅 warning 提示次要细节缺失
                    issues.append(
                        {
                            "severity": "warning",
                            "detail": f"次要细节缺失：{it.get('claim', '')}",
                            "kb_evidence": it.get("evidence_from_kb") or "",
                        }
                    )
            hallucination_flags = flags
        else:
            hallucination_flags = []

        total = len(items)
        hallucination_count = sum(1 for it in items if it.get("verdict") == "hallucination")
        unverifiable_count = sum(1 for it in items if it.get("verdict") == "unverifiable")
        partially_supported_count = sum(
            1 for it in items if it.get("verdict") == "partially_supported"
        )
        accurate_count = (
            total - hallucination_count - unverifiable_count - partially_supported_count
        )
        # 幻觉率分子仅含 hallucination + unverifiable，partially_supported 不计入坏样本
        hallucination_rate = (
            round((hallucination_count + unverifiable_count) / total, 4) if total else 0.0
        )
        overall_accuracy = round(accurate_count / total, 4) if total else 1.0

        has_error = any(i.get("severity") == "error" for i in issues)
        verdict = "needs_revision" if has_error else "approved"

        return {
            "resource_index": index,
            "resource_type": resource_type,
            "title": title,
            "verdict": verdict,
            "issues": issues,
            "fact_check": {
                "overall_accuracy": overall_accuracy,
                "items": items,
                "hallucination_count": hallucination_count,
                "unverifiable_count": unverifiable_count,
                "partially_supported_count": partially_supported_count,
            },
            "hallucination_flags": hallucination_flags,
            "hallucination_rate": hallucination_rate,
            "no_kb_mode": no_kb,
        }

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    def _infer_authority(self, chunk: dict) -> str:
        """推断 KB 原文权威等级：显式 source_level > 元数据 > 标题关键词 > 默认 B（二手）。"""
        # 1. 优先读平铺的 source_level（store.py 入库时从正文「权威等级：A/B」解析透传）
        flat = str(chunk.get("source_level") or "").strip().lower()
        if flat in ("a", "official", "primary", "一手", "一级", "官方"):
            return AUTHORITY_A
        if flat in ("b", "secondary", "二手", "二级"):
            return AUTHORITY_B

        # 2. 读嵌套 metadata（旧数据 / 外部来源兼容）
        meta = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        raw = str(
            meta.get("source_level") or meta.get("authority") or meta.get("authority_level") or ""
        ).lower()
        if raw in ("official", "a", "primary", "一手", "一级", "官方"):
            return AUTHORITY_A
        if raw in ("community", "b", "secondary", "二手", "二级"):
            return AUTHORITY_B

        # 3. 标题关键词兜底
        text = (str(chunk.get("doc_title") or "") + " " + str(chunk.get("doc_id") or "")).lower()
        if any(k in text for k in _A_LEVEL_KEYWORDS):
            return AUTHORITY_A
        if any(k in text for k in _B_LEVEL_KEYWORDS):
            return AUTHORITY_B
        return AUTHORITY_UNKNOWN  # 未标注 → 视为二手（保守）

    def _fmt_evidence(self, evidence_pool: list[dict]) -> str:
        """格式化证据池，带权威等级标注，供 LLM 比对。"""
        if not evidence_pool:
            return "（无知识库原文）"
        lines = []
        for i, ev in enumerate(evidence_pool):
            auth = ev.get("authority") or AUTHORITY_UNKNOWN
            label = {"A": "A级·一手原文", "B": "B级·二手资料"}.get(auth, "B级·二手")
            title = ev.get("doc_title") or ev.get("doc_id") or "?"
            lines.append(f"[{i}] [{label}] {title}\n{ev.get('content', '')[:500]}")
        return "\n\n".join(lines)

    def _fallback_report(self, index: int, resource: dict, error: str) -> dict:
        """资源审核异常时的兜底报告（保证 audit_result 长度与资源一致）。"""
        return {
            "resource_index": index,
            "resource_type": str(resource.get("resource_type") or ""),
            "title": str(resource.get("title") or ""),
            "verdict": "needs_revision",
            "issues": [
                {
                    "severity": "error",
                    "detail": f"审核流程异常（{error}），无法完成 KB 比对，需人工复查",
                    "kb_evidence": "",
                }
            ],
            "fact_check": {
                "overall_accuracy": 0.0,
                "items": [],
                "hallucination_count": 0,
                "unverifiable_count": 0,
                "partially_supported_count": 0,
            },
            "hallucination_flags": [],
            "hallucination_rate": 0.0,
            "no_kb_mode": False,
        }

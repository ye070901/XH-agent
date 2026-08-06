"""
Agent 3 初审模块 — day4 独立版
════════════════════════════════════════════════════════════
独立 Agent3 初审项目：不移动文件夹、不并入 agent1，且不导入 agent1 的任何代码。
本模块仅依赖 Python 标准库，可单独运行、可被 unittest / pytest 测试。

职责：
  1. process(generated_resources)  — 核心审核入口
       输入: 生成资源列表（list[dict] 或带属性的对象，或包含
              "generated_resources" 的 exchange 完整输入 dict）
       输出: {"verdict": "...", "issues": [...]}
       verdict: "approved" | "needs_revision" | "uncertain"
       issues:  扁平问题列表，元素含 severity / detail，
                资源级问题另附 resource_index / resource_type
  2. 外部文件交换
       读取   C:\\Users\\CAT\\Desktop\\exchange\\diagnosis_out.json
       审核后写入 C:\\Users\\CAT\\Desktop\\exchange\\audit_out.json
  3. 命令行入口

初审策略（确定性规则 + 可选 LLM 深度核验）：
  - 结构检查：标题 / 内容 / 类型 / 难度是否齐全
  - 难度匹配：资源难度 vs 诊断推荐难度（差 ≥2 级 → error，差 1 级 → warning）
  - 盲区覆盖：critical / high 盲区是否被任一资源覆盖（批量，warning）
  - 引用溯源：citations 显式为空数组 → 疑似未约束生成（warning）
  - 可选 LLM：提供 llm_client 时做事实核验，补充 issues

用法：
  python agent3_day4.py                 # 读 exchange 输入 → 审核 → 写 audit_out.json
  python agent3_day4.py --init-sample   # 生成一份示例输入文件
  python agent3_day4.py --input X.json --output Y.json
  python agent3_day4.py --real          # 使用真实 LLM（需设置 LLM_API_KEY）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from typing import Any

# ── Windows 终端 UTF-8（stdout + stderr）──
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
# 常量与默认路径
# ═══════════════════════════════════════════════════════════

EXCHANGE_DIR = os.environ.get("AGENT3_EXCHANGE_DIR", r"C:\Users\CAT\Desktop\exchange")
DIAGNOSIS_IN_PATH = os.environ.get("AGENT3_INPUT_PATH", os.path.join(EXCHANGE_DIR, "diagnosis_out.json"))
AUDIT_OUT_PATH = os.environ.get("AGENT3_OUTPUT_PATH", os.path.join(EXCHANGE_DIR, "audit_out.json"))

_DIFFICULTY_LEVELS = {"beginner": 0, "intermediate": 1, "advanced": 2}
_CRITICAL_PRIORITY = ("critical", "high")
_SEVERITY_ZH = {"高": "high", "中": "medium", "低": "low"}
_MISSING = object()

# 主题切分：空格、连字符、斜杠、中文连接词等
_TOPIC_SPLIT = re.compile(r"[\s\-_/\\、，,.;:：()（）|与和]")


# ═══════════════════════════════════════════════════════════
# 核心审核入口：process(generated_resources)
# ═══════════════════════════════════════════════════════════


async def process(
    generated_resources: Any,
    diagnosis_result: dict | None = None,
    *,
    llm_client: Any = None,
) -> dict[str, Any]:
    """审核生成资源，返回 {"verdict": ..., "issues": [...]}。

    Args:
        generated_resources: 生成资源列表。可为 list[dict]、list[对象]，
            或包含 "generated_resources" / "diagnosis_result" 的 exchange 输入 dict。
        diagnosis_result:    Agent 1 诊断结果 dict（含 recommended_difficulty、
                             skill_gaps 等）。缺省时从 generated_resources 中提取或为空。
        llm_client:          可选深度核验客户端，需实现
                             async audit_resource(index, resource, diagnosis) -> list[dict]。

    Returns:
        dict: {"verdict": str, "issues": list[dict]}。issues 为扁平列表。
    """
    overall, _ = await _audit_all(generated_resources, diagnosis_result, llm_client)
    return overall


# ═══════════════════════════════════════════════════════════
# 外部文件交换
# ═══════════════════════════════════════════════════════════


def read_input(path: str = DIAGNOSIS_IN_PATH) -> dict[str, Any]:
    """读取外部输入文件，返回 {"generated_resources": [...], "diagnosis_result": {...}}。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 文件不是合法 JSON 或顶层结构不支持。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"输入文件不存在: {path}")
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"输入文件不是合法 JSON: {path} ({e})") from e
    return _extract_input(data)


def write_output(
    path: str,
    overall: dict[str, Any],
    audit_result: list[dict],
    *,
    meta: dict | None = None,
) -> dict[str, Any]:
    """将审核结果写入外部输出文件。

    输出结构：
        {
            "verdict": "...",
            "issues": [...],          # 扁平问题列表（process() 的核心输出）
            "audit_result": [...],    # 逐资源审核报告（供下游修正 Agent 使用）
            "meta": {...}
        }
    """
    payload: dict[str, Any] = {
        "verdict": overall.get("verdict", ""),
        "issues": overall.get("issues", []),
        "audit_result": audit_result,
        "meta": meta or {},
    }
    out_dir = os.path.dirname(str(path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


async def audit_from_exchange(
    input_path: str = DIAGNOSIS_IN_PATH,
    output_path: str = AUDIT_OUT_PATH,
    *,
    real: bool = False,
    llm_client: Any = None,
) -> dict[str, Any]:
    """端到端交换：读 diagnosis_out.json → 审核 → 写 audit_out.json。

    Returns:
        dict: 实际写入文件的完整 payload。
    """
    data = read_input(input_path)
    resources = data["generated_resources"]
    diagnosis = data["diagnosis_result"]

    if llm_client is None and (real or os.getenv("LLM_API_KEY")):
        llm_client = _LLMEnricher()

    overall, audit_result = await _audit_all(resources, diagnosis, llm_client)
    meta = {
        "source_file": str(input_path),
        "resource_count": len(resources),
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "llm" if llm_client is not None else "rule_only",
    }
    return write_output(output_path, overall, audit_result, meta=meta)


def write_sample_input(path: str = DIAGNOSIS_IN_PATH) -> str:
    """生成一份示例输入文件，便于本地跑通流程。"""
    sample = {
        "task_id": "sample-001",
        "learner_data": {"name": "测试学习者", "level": "intermediate"},
        "diagnosis_result": {
            "recommended_difficulty": "intermediate",
            "learner_level": "intermediate",
            "skill_gaps": [
                {"priority": "critical", "topic": "Python 装饰器与闭包", "category": "advanced_syntax"},
                {"priority": "high", "topic": "React Hooks 最佳实践", "category": "frontend"},
                {"priority": "medium", "topic": "Git 分支策略", "category": "tooling"},
            ],
        },
        "generated_resources": [
            {
                "resource_type": "article",
                "title": "Python 闭包详解",
                "difficulty_level": "intermediate",
                "content": (
                    "闭包（Closure）是 Python 中一个重要的概念：在外部函数中定义内部函数，"
                    "内部函数引用外部函数的变量，并且外部函数把内部函数作为返回值返回。"
                    "闭包可以让函数记住创建时的环境。示例：def outer(x): def inner(y): "
                    "return x + y; return inner。"
                ),
                "citations": [{"doc_id": "02_StateGraph详解.md", "chunk_index": 0}],
                "target_skill_gaps": ["Python 装饰器与闭包"],
            },
            {
                "resource_type": "video",
                "title": "深入理解 Python 装饰器",
                "difficulty_level": "advanced",
                "content": (
                    "本视频讲解 Python 装饰器的原理和用法：装饰器本质上是接受一个函数作为参数、"
                    "返回一个新函数的可调用对象。示例：def timer(func): def wrapper(...): ...; "
                    "return wrapper。注意 wrapper 缺少 @functools.wraps 会导致 __name__ 丢失。"
                ),
                "citations": [],
                "target_skill_gaps": ["Python 装饰器与闭包"],
            },
            {
                "resource_type": "exercise",
                "title": "React Hooks 实战练习",
                "difficulty_level": "beginner",
                "content": (
                    "练习 1：使用 useState 管理表单状态。练习 2：使用 useEffect 发起数据请求。"
                    "练习 3：尝试自定义 useLocalStorage Hook。"
                ),
                "citations": [],
                "target_skill_gaps": ["React Hooks 最佳实践"],
            },
        ],
    }
    out_dir = os.path.dirname(str(path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
    return str(path)


# ═══════════════════════════════════════════════════════════
# 内部实现
# ═══════════════════════════════════════════════════════════


async def _audit_all(
    generated_resources: Any,
    diagnosis_result: dict | None = None,
    llm_client: Any = None,
) -> tuple[dict[str, Any], list[dict]]:
    """审核全部资源，返回 (overall, audit_result)。

    - overall: {"verdict", "issues"} —— process() 的核心输出
    - audit_result: 逐资源报告（resource_index / resource_type / title /
                     verdict / issues），供输出文件与下游使用。
    """
    # 兼容：直接传入 exchange 完整输入 dict
    if isinstance(generated_resources, dict) and "generated_resources" in generated_resources:
        diagnosis_result = (
            generated_resources.get("diagnosis_result") or diagnosis_result or {}
        )
        generated_resources = generated_resources.get("generated_resources")

    diagnosis = diagnosis_result if isinstance(diagnosis_result, dict) else {}
    resources = _normalize_resources(generated_resources)

    if not resources:
        return (
            {
                "verdict": "uncertain",
                "issues": [
                    {"severity": "warning", "detail": "generated_resources 为空，无可审核资源"}
                ],
            },
            [],
        )

    issues: list[dict] = []
    audit_result: list[dict] = []

    for i, resource in enumerate(resources):
        report, res_issues = await _audit_resource(i, resource, diagnosis, llm_client)
        audit_result.append(report)
        issues.extend(res_issues)

    _append_coverage_issues(issues, resources, diagnosis)
    verdict = _decide_verdict(issues)

    return {"verdict": verdict, "issues": issues}, audit_result


async def _audit_resource(
    index: int,
    resource: dict,
    diagnosis: dict,
    llm_client: Any,
) -> tuple[dict, list[dict]]:
    """审核单个资源：确定性规则检查 + 可选 LLM 深度核验。"""
    issues = _rule_checks(index, resource, diagnosis)

    if llm_client is not None:
        try:
            extra = await llm_client.audit_resource(index, resource, diagnosis)
            if extra:
                issues.extend(_normalize_llm_issues(extra, index, resource))
        except Exception as e:  # 单条 LLM 失败不阻断整批审核
            issues.append(
                _issue(
                    "warning",
                    f"大模型深度核验失败（{type(e).__name__}），已跳过该资源的高级审核",
                    index,
                    resource,
                )
            )

    return _build_report(index, resource, issues), issues


def _rule_checks(index: int, resource: dict, diagnosis: dict) -> list[dict]:
    """确定性初审规则。"""
    issues: list[dict] = []
    title = _get(resource, "title")
    content = _get(resource, "content")
    resource_type = _get(resource, "resource_type")
    difficulty = _get(resource, "difficulty_level")

    if not title:
        issues.append(_issue("warning", "资源缺少标题（title）", index, resource))

    if not content:
        issues.append(_issue("error", "资源内容为空（content），无法审核", index, resource))
    elif len(str(content).strip()) < 30:
        issues.append(_issue("warning", "资源内容过短（<30 字），疑似占位内容", index, resource))

    if not resource_type:
        issues.append(_issue("warning", "资源缺少类型（resource_type）", index, resource))

    if difficulty:
        _check_difficulty_match(difficulty, diagnosis, index, resource, issues)
    else:
        issues.append(_issue("warning", "资源缺少难度（difficulty_level）", index, resource))

    # 引用溯源：显式声明为空数组 → 疑似未约束生成（内容类资源）
    if _has_key(resource, "citations"):
        citations = _get(resource, "citations") or []
        if not citations and _is_content_type(resource_type):
            issues.append(
                _issue("warning", "资源未附引用溯源（citations 为空），疑似未约束生成", index, resource)
            )

    # 声明覆盖盲区但内容未体现
    target_gaps = _get(resource, "target_skill_gaps") or []
    if target_gaps:
        text = f"{title or ''} {content or ''}".lower()
        for gap in target_gaps:
            gap_topic = gap.get("topic") if isinstance(gap, dict) else str(gap)
            if gap_topic and not _topic_covered(gap_topic, text):
                issues.append(
                    _issue("warning", f"声明覆盖的盲区「{gap_topic}」未在内容中体现", index, resource)
                )

    return issues


def _check_difficulty_match(
    difficulty: Any,
    diagnosis: dict,
    index: int,
    resource: dict,
    issues: list[dict],
) -> None:
    """难度匹配：与诊断推荐难度对比。"""
    recommended = diagnosis.get("recommended_difficulty") or diagnosis.get("learner_level")
    if not recommended:
        return

    res = str(difficulty).strip().lower()
    rec = str(recommended).strip().lower()

    if res in _DIFFICULTY_LEVELS and rec in _DIFFICULTY_LEVELS:
        gap = abs(_DIFFICULTY_LEVELS[res] - _DIFFICULTY_LEVELS[rec])
        if gap >= 2:
            issues.append(
                _issue("error", f"资源难度（{difficulty}）与推荐难度（{recommended}）差距过大（差 {gap} 级）", index, resource)
            )
        elif gap == 1:
            issues.append(
                _issue("warning", f"资源难度（{difficulty}）与推荐难度（{recommended}）相差一级", index, resource)
            )
    else:
        issues.append(
            _issue("warning", f"资源难度「{difficulty}」不在受控集合（beginner/intermediate/advanced）中", index, resource)
        )


def _append_coverage_issues(issues: list[dict], resources: list[dict], diagnosis: dict) -> None:
    """批量盲区覆盖检查：critical/high 盲区未被任何资源覆盖时给出 warning。"""
    critical_gaps = _collect_critical_gaps(diagnosis)
    if not critical_gaps:
        return

    all_text = " ".join(
        f"{_get(r, 'title') or ''} {_get(r, 'content') or ''} {_fmt_targets(_get(r, 'target_skill_gaps') or [])}"
        for r in resources
    ).lower()

    for prio, topic in critical_gaps:
        if not _topic_covered(topic, all_text):
            issues.append(
                {"severity": "warning", "detail": f"[{prio.upper()}] 盲区「{topic}」未被任何资源覆盖"}
            )


def _collect_critical_gaps(diagnosis: dict) -> list[tuple[str, str]]:
    """收集诊断中的 critical / high 盲区，兼容多种字段命名。"""
    gaps: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for source_key in ("skill_gaps", "knowledge_map"):
        for item in diagnosis.get(source_key, []) or []:
            if not isinstance(item, dict):
                continue
            prio = item.get("priority") or _SEVERITY_ZH.get(item.get("severity", ""), "")
            prio = str(prio).lower()
            topic = item.get("topic") or item.get("skill") or item.get("name")
            if prio not in _CRITICAL_PRIORITY or not topic:
                continue
            key = (prio, str(topic))
            if key not in seen:
                seen.add(key)
                gaps.append(key)

    return gaps


def _decide_verdict(issues: list[dict]) -> str:
    """由扁平问题列表决定整体结论。"""
    if any(i.get("severity") == "error" for i in issues):
        return "needs_revision"
    return "approved"


def _build_report(index: int, resource: dict, issues: list[dict]) -> dict:
    """构建逐资源报告（与既有 audit_result 结构兼容）。"""
    has_error = any(i.get("severity") == "error" for i in issues)
    return {
        "resource_index": index,
        "resource_type": _get(resource, "resource_type", ""),
        "title": _get(resource, "title", ""),
        "verdict": "needs_revision" if has_error else "approved",
        "issues": [
            {"severity": i.get("severity", "warning"), "detail": i.get("detail", "")}
            for i in issues
        ],
    }


def _extract_input(data: Any) -> dict[str, Any]:
    """从外部输入 JSON 中提取 generated_resources 与 diagnosis_result（容错）。"""
    if isinstance(data, list):
        return {"generated_resources": list(data), "diagnosis_result": {}}
    if not isinstance(data, dict):
        raise ValueError(f"输入 JSON 顶层必须是对象或数组，实际为 {type(data).__name__}")

    root = data.get("data") if isinstance(data.get("data"), (dict, list)) else data
    if isinstance(root, list):
        return {"generated_resources": list(root), "diagnosis_result": {}}
    if not isinstance(root, dict):
        return {"generated_resources": [], "diagnosis_result": {}}

    resources = root.get("generated_resources", root.get("resources", []))
    if resources is None:
        resources = []
    diagnosis = root.get("diagnosis_result", root.get("diagnosis", {}))
    if not isinstance(diagnosis, dict):
        diagnosis = {}

    # 整个文件本身可能就是 diagnosis_result（无资源）
    if not resources and not diagnosis:
        if any(k in root for k in ("skill_gaps", "knowledge_map", "recommended_difficulty")):
            return {"generated_resources": [], "diagnosis_result": root}

    return {"generated_resources": resources, "diagnosis_result": diagnosis}


# ═══════════════════════════════════════════════════════════
# 通用小工具
# ═══════════════════════════════════════════════════════════


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 与带属性的对象取值。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    if hasattr(obj, key):
        return getattr(obj, key, default)
    return default


def _has_key(obj: Any, key: str) -> bool:
    if isinstance(obj, dict):
        return key in obj
    return hasattr(obj, key)


def _normalize_resources(generated_resources: Any) -> list[dict]:
    """将输入统一为 list[dict]。"""
    if generated_resources is None:
        return []
    if isinstance(generated_resources, (list, tuple)):
        return [_as_dict(r) for r in generated_resources if r is not None]
    return [_as_dict(generated_resources)]


def _as_dict(resource: Any) -> dict:
    """dict 原样返回；pydantic 对象转 dict；其余取 __dict__。"""
    if isinstance(resource, dict):
        return resource
    if hasattr(resource, "model_dump"):
        try:
            return resource.model_dump()
        except Exception:
            pass
    if hasattr(resource, "dict"):
        try:
            return resource.dict()
        except Exception:
            pass
    if hasattr(resource, "__dict__"):
        return dict(resource.__dict__)
    return {}


def _is_content_type(resource_type: Any) -> bool:
    """内容类资源（需要引用溯源）；练习/测验类跳过该检查。"""
    rt = str(resource_type or "").strip().lower()
    return bool(rt) and rt not in {"quiz", "exercise", "question", "exercise_quiz"}


def _fmt_targets(target_gaps: list) -> str:
    parts: list[str] = []
    for g in target_gaps:
        if isinstance(g, dict):
            parts.append(str(g.get("topic") or g.get("name") or g.get("skill") or ""))
        else:
            parts.append(str(g))
    return " ".join(p for p in parts if p)


def _topic_covered(topic: Any, text: str) -> bool:
    """主题覆盖判断：全文匹配，或按连接词切分后的任意有效片段命中。"""
    topic = str(topic).strip().lower()
    if not topic:
        return True
    if topic in text:
        return True
    parts = [p for p in _TOPIC_SPLIT.split(topic) if len(p) >= 2]
    return any(p in text for p in parts)


def _issue(severity: str, detail: str, index: int | None = None, resource: dict | None = None) -> dict:
    """构造扁平 issue，资源级问题附带 resource_index / resource_type。"""
    issue: dict[str, Any] = {"severity": severity, "detail": detail}
    if index is not None:
        issue["resource_index"] = index
        rt = _get(resource, "resource_type") if resource is not None else ""
        if rt:
            issue["resource_type"] = rt
    return issue


def _normalize_llm_issues(raw: Any, index: int, resource: dict) -> list[dict]:
    """将 LLM 返回的原始 issue 列表规范化为扁平 issue。"""
    issues: list[dict] = []
    if not isinstance(raw, list):
        return issues
    for item in raw:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity", "warning")).lower()
        if sev not in ("error", "warning", "info"):
            sev = "warning"
        detail = str(item.get("detail", "")).strip()
        if not detail:
            continue
        issues.append(_issue(sev, detail, index, resource))
    return issues


def _parse_json(text: str) -> dict[str, Any]:
    """容错 JSON 解析：直接 → 代码块 → 花括号提取。"""
    if not isinstance(text, str):
        return {}
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ═══════════════════════════════════════════════════════════
# 可选 LLM 深度核验
# ═══════════════════════════════════════════════════════════


class _LLMEnricher:
    """可选的 LLM 深度核验层（OpenAI 兼容 API）。

    无 LLM_API_KEY 时返回 []（初审仅做规则检查）。
    有 LLM_API_KEY 时对每个资源追加事实核验，异常时安全返回 []。
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "gpt-4o")
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "2") or 2)
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120") or 120)

    @property
    def is_demo(self) -> bool:
        return not self.api_key

    async def audit_resource(self, index: int, resource: dict, diagnosis: dict) -> list[dict]:
        """深度核验单个资源，返回原始 issue 列表。"""
        if self.is_demo:
            return []

        recommended = diagnosis.get("recommended_difficulty", "")
        gaps = "\n".join(f"- [{g}] {t}" for g, t in _collect_critical_gaps(diagnosis)) or "（无）"
        content = str(_get(resource, "content") or "")[:3000]

        prompt = (
            "请审核以下学习资源，只做检查，不要修改内容。\n"
            f"资源编号: {index}\n"
            f"类型: {_get(resource, 'resource_type', '')}\n"
            f"标题: {_get(resource, 'title', '')}\n"
            f"难度: {_get(resource, 'difficulty_level', '')}\n"
            f"推荐难度: {recommended}\n"
            f"需覆盖的关键盲区:\n{gaps}\n"
            f"内容:\n{content}\n\n"
            "检查：1) 事实错误（API 名称、概念定义、代码能否运行）；"
            "2) 难度是否匹配；3) 盲区是否覆盖。\n"
            '请只输出 JSON（不要 markdown 代码块）：\n'
            '{"issues": [{"severity": "error|warning|info", "detail": "一句话问题描述"}]}'
        )

        try:
            text = await self._call(prompt)
            data = _parse_json(text)
            return data.get("issues", []) if isinstance(data, dict) else []
        except Exception:
            # 单资源 LLM 失败 → 不追加 issue，交给规则层兜底
            return []

    async def _call(self, prompt: str) -> str:
        """调用 OpenAI 兼容 /chat/completions，带重试。"""
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是一个严格的内容审核专家，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        last_error: Exception | None = None
        loop = asyncio.get_running_loop()

        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp = await loop.run_in_executor(
                    None, lambda: urllib.request.urlopen(req, timeout=self.timeout)
                )
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(1 * (attempt + 1))

        raise last_error  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════


def _arg_value(args: list[str], flag: str) -> str | None:
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            return args[i + 1]
    return None


def _print_summary(payload: dict[str, Any]) -> None:
    verdict = payload.get("verdict", "")
    issues = payload.get("issues", [])
    errors = sum(1 for i in issues if i.get("severity") == "error")
    warnings = sum(1 for i in issues if i.get("severity") == "warning")
    infos = sum(1 for i in issues if i.get("severity") == "info")

    print("=" * 60)
    print("  Agent3 初审结果")
    print(f"  结论    : {verdict}")
    print(f"  issues  : {len(issues)} 个 (error={errors}, warning={warnings}, info={infos})")
    for i in issues:
        loc = f"[资源{i['resource_index']}] " if "resource_index" in i else ""
        print(f"    - [{i.get('severity')}] {loc}{i.get('detail')}")
    print("=" * 60)


def main() -> None:
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    if "--init-sample" in args:
        path = write_sample_input()
        print(f"✅ 示例输入已写入: {path}")
        return

    input_path = _arg_value(args, "--input") or DIAGNOSIS_IN_PATH
    output_path = _arg_value(args, "--output") or AUDIT_OUT_PATH
    real = "--real" in args

    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在: {input_path}")
        print("   提示: 可先运行 python agent3_day4.py --init-sample 生成示例输入")
        sys.exit(1)

    payload = asyncio.run(audit_from_exchange(input_path, output_path, real=real))
    _print_summary(payload)
    print(f"\n📄 审核结果已写入: {output_path}")


if __name__ == "__main__":
    main()

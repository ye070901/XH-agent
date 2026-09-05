"""把 raw_samples.json + core_knowledge_map + learner_profiles 拆成提交用的「测试数据」包。

产物目录（submission_test_data/ 下）：
  01_知识库切片/kb_slice/   ← 26 篇 core 级权威文档（覆盖全部 21 个 core 知识点）
  01_知识库切片/切片对照表.md
  02_学习者画像/learner_profiles.json
  03_输入输出示例/画像{D,I,K}_*/  ← 每组 5 段 markdown：输入 → 诊断 → 协同日志 → 审核辩论 → 资源

只读不写任何 backend 数据；只做纯文本/文件复制与 JSON→Markdown 展开。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "submission_test_data"
BUILD = ROOT / "_build"
RAW_SAMPLES = BUILD / "raw_samples.json"
CORE_MAP = REPO_ROOT / "data" / "core_knowledge_map.json"
PROFILES = REPO_ROOT / "data" / "evaluation" / "learner_profiles.json"

KB_SLICE_DIR = ROOT / "01_知识库切片" / "kb_slice"
PROFILES_OUT = ROOT / "02_学习者画像" / "learner_profiles.json"
EXAMPLES_DIR = ROOT / "03_输入输出示例"
EXECUTION_DIR = ROOT / "04_测试执行记录"

CASE_META = {
    "profile-d-zero-basis": ("E2E-001", "画像D_零基础转行", "零基础学习者适配"),
    "profile-i-skilled-engineer": ("E2E-002", "画像I_熟练工程师", "熟练工程师进阶适配"),
    "profile-k-over-confident": ("E2E-003", "画像K_过度自信", "对抗画像客观证据校正"),
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as h:
        return json.load(h)


def build_kb_slice() -> dict:
    """复制 core 级权威文档到切片目录，返回 {文件数, 知识点行, 领域统计}。"""
    cmap = load_json(CORE_MAP)
    kp_meta: dict[str, dict] = {}
    kp_docs: list[tuple[str, str, str, list[str]]] = []  # (kp_id, domain, topic, docs)
    all_docs: set[str] = set()
    for dom in cmap["domains"]:
        for kp in dom["knowledge_points"]:
            kp_meta[kp["id"]] = {"topic": kp["topic"], "level": kp["level"], "domain": dom["name"]}
            if kp["level"] != "core":
                continue
            docs = kp["source_documents"]
            kp_docs.append((kp["id"], dom["name"], kp["topic"], docs))
            all_docs.update(docs)

    KB_SLICE_DIR.mkdir(parents=True, exist_ok=True)
    # 清空旧的（幂等重建）
    for old in KB_SLICE_DIR.glob("*.md"):
        old.unlink()

    copied_files: list[str] = []
    for src in sorted(all_docs):
        src_path = REPO_ROOT / src
        if not src_path.exists():
            print(f"  ! 源文档缺失，跳过: {src}")
            continue
        shutil.copyfile(src_path, KB_SLICE_DIR / src_path.name)
        copied_files.append(src_path.name)

    # 统计每领域 core 知识点数
    dom_core: dict[str, int] = {}
    for kp_id, dom, _, _ in kp_docs:
        dom_core[dom] = dom_core.get(dom, 0) + 1
    return {"kp_meta": kp_meta, "kp_docs": kp_docs, "copied_files": copied_files, "dom_core": dom_core}


def _fmt_table(rows: list[list[str]], headers: list[str]) -> str:
    def esc(s: str) -> str:
        return str(s).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _business_steps(agent_log: list[dict]) -> list[list[str]]:
    """Merge module lifecycle events and pipeline state events into one business step."""
    definitions = {
        "diagnosis": ("学情诊断", "学情诊断 Agent", "根据画像与前置测试判断难度、风格和盲区"),
        "retrieval": ("知识检索", "retrieval", "从领域知识库检索生成所需的证据"),
        "generation": ("内容生成", "知识生成 Agent", "生成讲义、实操指南和测试题"),
        "audit": ("内容审核", "审核 Agent", "核查生成内容中的事实断言"),
        "debate": ("辩论裁决", "debate", "对存在分歧的断言进行裁决"),
        "correction": ("保真修正", "保真修正 Agent", "删除、替换或补充不可靠内容"),
        "audit_recheck": ("审核复核", "审核 Agent", "对修正后的内容进行再次审核"),
    }
    aliases = {
        "学情诊断Agent": "diagnosis", "diagnosis": "diagnosis",
        "retrieval": "retrieval",
        "知识生成Agent": "generation", "generation": "generation",
        "审核Agent": "audit", "audit": "audit",
        "debate": "debate",
        "保真修正Agent": "correction", "correction": "correction",
        "audit_recheck": "audit_recheck",
    }
    observed: dict[str, str] = {}
    for entry in agent_log:
        raw_name = entry.get("agent", "")
        key = aliases.get(raw_name)
        if raw_name == "审核Agent" and "audit" in observed:
            key = "audit_recheck"
        if not key or key in observed:
            continue
        observed[key] = entry.get("status", entry.get("stage", entry.get("level", ""))) or "完成"
    return [[*definitions[key], observed[key]] for key in definitions if key in observed]


def write_slice_readme(slice_info: dict) -> None:
    kp_docs = slice_info["kp_docs"]
    copied_files = slice_info["copied_files"]
    dom_core = slice_info["dom_core"]
    n_core_points = len(kp_docs)

    rows = []
    for kp_id, dom, topic, docs in sorted(kp_docs):
        docs_str = "；".join(d.split("/")[-1] for d in docs)
        rows.append([kp_id, dom, topic, "core", docs_str])
    table = _fmt_table(rows, ["知识点ID", "所属领域", "主题", "级别", "切片文档"])

    dom_lines = "\n".join(f"| {d} | {c} |" for d, c in dom_core.items())

    lines = []
    lines.append("# 01 知识库切片 · 工业机器人编程与调试")
    lines.append("")
    lines.append("> 对应题目提交要求：**「至少 1 个垂直领域的专业知识库切片（用于检索的领域文档或实操数据）」**")
    lines.append("")
    lines.append("## 一、切片是什么")
    lines.append("")
    lines.append("本切片是「工业机器人编程与调试」领域（FANUC / KUKA / ABB 多品牌）的核心知识库子集：")
    lines.append("从全量 235 篇领域文档中，按 `data/core_knowledge_map.json` 的 **21 个 core 级核心知识点**")
    lines.append(f"逐一挑选权威源文档，共 **{len(copied_files)} 篇**，物理存放于 `kb_slice/` 目录。")
    lines.append("")
    lines.append("选取原则：")
    lines.append("- 每个 core 知识点至少 1 篇权威文档，优先选「实操 + 故障处置」类（非纯理论泛文）；")
    lines.append("- 文档即知识库检索（ChromaDB）的原始语料，切片与生产语料同源，非二次改写。")
    lines.append("")
    lines.append("## 二、切片内容范围")
    lines.append("")
    lines.append("| 领域名 | core 知识点数 |")
    lines.append("|--------|:----:|")
    lines.append(dom_lines)
    lines.append("")
    lines.append(f"## 三、core 知识点 → 切片文档对照表（{n_core_points} 个 core 知识点 / {len(copied_files)} 篇文档）")
    lines.append("")
    lines.append(table)
    lines.append("")
    lines.append("## 四、全量知识库说明（切片之外）")
    lines.append("")
    lines.append("- 完整语料共 **235 篇** md，位于仓库 `data/raw/` 下 3 个子目录（K1 基础/示教、K2 离线仿真、K3 安全故障）；")
    lines.append("- `data/core_knowledge_map.json` 定义了 **42 个 core/high 知识点**（21 core + 21 high），")
    lines.append("  其中 core 级由本切片覆盖，high 级文档同样在 `data/raw/` 内；")
    lines.append("- 生产系统通过 ChromaDB + `all-MiniLM-L6-v2` 向量化后检索（`backend/src/knowledge/store.py`）。")
    lines.append("")
    (ROOT / "01_知识库切片" / "切片对照表.md").write_text("\n".join(lines), encoding="utf-8")


def write_profile_dir() -> None:
    PROFILES_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROFILES, PROFILES_OUT)


def _md_h1(title: str, sub: str = "") -> str:
    return f"# {title}" + (f"\n\n{sub}" if sub else "") + "\n"


def build_example(sample: dict, profiles_meta: dict) -> None:
    pid = sample["profile_id"]
    label = sample["label"]
    inp = sample["input"]
    resp = sample["response"]

    safe_name = {"profile-d-zero-basis": "画像D_零基础转行",
                 "profile-i-skilled-engineer": "画像I_熟练工程师",
                 "profile-k-over-confident": "画像K_过度自信"}[pid]
    d = EXAMPLES_DIR / safe_name
    d.mkdir(parents=True, exist_ok=True)

    # ── 01 输入 ──
    pretest_rows = []
    for p in inp.get("pretest_results", []):
        topics = p.get("topic_scores", {})
        topic_str = "；".join(f"{k}={v}" for k, v in topics.items())
        pretest_rows.append([p.get("test_name", ""), f'{p.get("total_score", 0)}/{p.get("max_score", 0)}', topic_str])
    pretest_table = _fmt_table(pretest_rows, ["测试名称", "总分", "分项得分"]) if pretest_rows else "（无前置测试）"
    skills = "、".join(inp.get("skills_used", [])) or "（无）"
    positions = "、".join(inp.get("positions", [])) or "（无）"
    body = _md_h1("01 输入 · 学习者画像特征", f"画像 {label}")
    body += f"""## 基本画像

| 字段 | 值 |
|------|----|
| 姓名 | {inp.get('name', '')} |
| 学历 | {inp.get('education_level', '')} |
| 专业 | {inp.get('major', '')} |
| 院校 | {inp.get('school', '')} |
| 工作年限 | {inp.get('work_years', 0)} 年 |
| 行业 | {inp.get('industry', '')} |
| 历史岗位 | {positions} |
| 已用技能 | {skills} |

## 学习目标

> {inp.get('learning_goal', '')}

## 前置测试成绩

{pretest_table}
"""
    (d / "01_输入_画像特征.md").write_text(body, encoding="utf-8")

    # ── 02 诊断 ──
    diag = resp.get("diagnosis", {})
    km = diag.get("knowledge_map", {})
    km_rows = [[k, v.get("level", 0), v.get("confidence", 0), v.get("evidence", "")] for k, v in km.items()]
    gaps = diag.get("skill_gaps", [])
    gap_rows = [[g.get("topic", ""), g.get("current_level", 0), g.get("target_level", 0),
                 g.get("priority", ""), g.get("reason", "")] for g in gaps]
    body = _md_h1("02 中间数据 · 学情诊断（学情诊断 Agent）")
    body += f"""## 判定结果

- **推荐难度**：{diag.get('recommended_difficulty', '')}
- **学习风格**：{diag.get('learning_style', '')}
- **整体置信度**：{diag.get('overall_confidence', '')}

## 诊断摘要

> {diag.get('summary', '')}

## 知识掌握度图谱（knowledge_map）

{_fmt_table(km_rows, ['知识点', '掌握度(0-1)', '置信度', '证据'])}

## 知识盲区（skill_gaps）

{_fmt_table(gap_rows, ['主题', '当前', '目标', '优先级', '原因'])}
"""
    (d / "02_中间_学情诊断.md").write_text(body, encoding="utf-8")

    # ── 03 协同日志 ──
    log = resp.get("agent_log", [])
    log_lines = []
    for i, entry in enumerate(log, 1):
        agent = entry.get("agent", "")
        status = entry.get("status", entry.get("stage", entry.get("level", "")))
        msg = entry.get("message", "")
        extra = {k: v for k, v in entry.items() if k not in ("agent", "status", "stage", "level", "message")}
        extra_s = f" — {extra}" if extra else ""
        log_lines.append(f"{i}. **{agent}**（{status}）{msg}{extra_s}")
    body = _md_h1("03 中间数据 · 多智能体协同调度日志")
    body += "按时间顺序列出流水线各 Agent 的调度与状态（对应编排器 `orchestrator.py` 的 诊断→检索→生成→审核→辩论→修正 闭环）：\n\n"
    body += "\n".join(log_lines) + "\n"
    # debate 统计单独高亮
    for entry in log:
        if entry.get("agent") == "debate":
            body += f"\n## 博弈引擎裁决统计（debate）\n\n```json\n{json.dumps(entry.get('stats', {}), ensure_ascii=False, indent=2)}\n```\n"
        if entry.get("agent") == "correction" and entry.get("stats"):
            body += f"\n## 保真修正统计（correction）\n\n```json\n{json.dumps(entry.get('stats', {}), ensure_ascii=False, indent=2)}\n```\n"
    (d / "03_中间_协同日志.md").write_text(body, encoding="utf-8")

    # ── 04 审核与辩论 ──
    audit = resp.get("audit", [])
    body = _md_h1("04 中间数据 · 内容审核与事实核查（审核 Agent + 博弈引擎）")
    for a in audit:
        rtype = a.get("resource_type", "")
        verdict = a.get("verdict", "")
        fc = a.get("fact_check", {})
        body += f"\n## 资源「{a.get('title', '')}」（{rtype}）\n\n"
        body += f"- **审核结论**：`{verdict}`\n"
        body += f"- **整体准确率**：{fc.get('overall_accuracy', '')}\n"
        body += f"- **幻觉/不可验证计数**：hallucination={fc.get('hallucination_count', 0)}, unverifiable={fc.get('unverifiable_count', 0)}\n"
        body += f"- **幻觉率**：{a.get('hallucination_rate', '')}；no_kb_mode={a.get('no_kb_mode', '')}\n"
        items = fc.get("items", [])
        if items:
            def _ev(it):
                e = it.get("evidence_from_kb")
                return (e[:80] if isinstance(e, str) and e else "—")
            rows = [[it.get("claim", ""), it.get("verdict", ""), _ev(it)] for it in items]
            body += f"\n### 逐条断言核查（三态：accurate / hallucination / unverifiable）\n\n{_fmt_table(rows, ['断言', '判定', '知识库证据(截断)'])}\n"
    (d / "04_中间_审核与辩论.md").write_text(body, encoding="utf-8")

    # ── 05 资源 ──
    res = resp.get("resources", [])
    body = _md_h1("05 输出 · 个性化学习资源（知识生成 Agent → 保真修正 Agent）")
    body += f"共生成 **{len(res)}** 种形态资源（讲义 / 实操指南 / 分阶测试题）。\n"
    for r in res:
        body += f"\n---\n\n## {r.get('title', '')}\n\n"
        body += f"- 资源类型：`{r.get('resource_type', '')}`\n"
        body += f"- 难度定标：`{r.get('difficulty_level', '')}`；预计时长：{r.get('estimated_duration_minutes', '')} 分钟\n"
        body += f"- 目标盲区：{r.get('target_skill_gaps', [])}\n"
        cites = r.get("citations", [])
        if cites:
            body += f"- 知识溯源（citations）：\n"
            for c in cites:
                body += f"  - {c}\n"
        body += f"\n{r.get('content', '')}\n"
    (d / "05_输出_个性化资源.md").write_text(body, encoding="utf-8")

    # ── 06 预期 vs 实测（客观对照，来自 learner_profiles.json 的 expected_profile）──
    exp = profiles_meta.get(pid, {}).get("expected_profile", {})
    if exp:
        body = _md_h1("06 对照 · 画像预期 vs 系统实测")
        body += f"""本组用例在 `data/evaluation/learner_profiles.json` 中预先定义了「应得难度 / 风格」真值，用于客观评估适配准确率。

| 项 | 预期（真值） | 系统实测 |
|----|------|------|
| 难度 | {exp.get('expected_difficulty', '')} | {diag.get('recommended_difficulty', '')} |
| 学习风格 | {exp.get('expected_learning_style', '')} | {diag.get('learning_style', '')} |

**难度预期依据**：{exp.get('difficulty_rationale', '')}

**风格预期依据**：{exp.get('style_rationale', '')}
"""
        (d / "06_预期与实测对照.md").write_text(body, encoding="utf-8")


def write_execution_records(samples: list[dict], profiles_meta: dict) -> None:
    """从原始 API 响应生成可审阅的端到端测试执行记录。"""
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    for old in EXECUTION_DIR.glob("E2E-*.md"):
        old.unlink()

    captured_at = datetime.fromtimestamp(RAW_SAMPLES.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    raw_hash = _sha256(RAW_SAMPLES)
    manifest_cases = []
    summary_rows = []

    for sample in samples:
        pid = sample["profile_id"]
        case_id, safe_name, scenario = CASE_META[pid]
        response = sample.get("response", {})
        diagnosis = response.get("diagnosis", {})
        expected = profiles_meta.get(pid, {}).get("expected_profile", {})
        expected_difficulty = expected.get("expected_difficulty", "")
        expected_style = expected.get("expected_learning_style", "")
        actual_difficulty = diagnosis.get("recommended_difficulty", "")
        actual_style = diagnosis.get("learning_style", "")
        assertions = [
            ["难度", expected_difficulty, actual_difficulty, "通过" if expected_difficulty == actual_difficulty else "不通过"],
            ["学习风格", expected_style, actual_style, "通过" if expected_style == actual_style else "不通过"],
        ]
        passed = all(row[3] == "通过" for row in assertions) and sample.get("http_status") == 200

        log_rows = _business_steps(response.get("agent_log", []))

        audit_rows = []
        for audit in response.get("audit", []):
            fact_check = audit.get("fact_check", {})
            audit_rows.append([
                audit.get("resource_type", ""),
                audit.get("verdict", ""),
                fact_check.get("hallucination_count", 0),
                fact_check.get("unverifiable_count", 0),
            ])

        resource_rows = []
        for resource in response.get("resources", []):
            resource_rows.append([
                resource.get("resource_type", ""),
                resource.get("title", ""),
                resource.get("difficulty_level", ""),
            ])

        request_json = json.dumps(sample.get("request", {}), ensure_ascii=False, indent=2)
        body = _md_h1(f"{case_id} 测试执行记录", scenario)
        body += f"""## 测试身份

| 项 | 值 |
|---|---|
| 用例编号 | {case_id} |
| 测试数据 | `02_学习者画像/learner_profiles.json` 中的 `{pid}` |
| 原始响应 | `_build/raw_samples.json` 中的 `{pid}` 记录 |
| 原始响应采集时间 | {captured_at} |
| HTTP 状态 | {sample.get('http_status', '')} |
| 结论 | {'通过' if passed else '不通过'} |

## 1 测试输入与请求

测试脚本 `submission_test_data/_build/generate_samples.py` 读取画像真值，向 `POST /api/generate` 发送以下请求：

```json
{request_json}
```

## 2 系统生成过程

系统响应先产生学情诊断，再经过检索、生成、审核、辩论和修正等环节。以下业务步骤由本次响应的 `agent_log` 归并而来：同一模块的“执行完成”事件与“状态完成”事件只计为一个步骤；原始 `agent_log` 保留在 `_build/raw_samples.json`。

{_fmt_table(log_rows or [['-', '-', '-', '响应未包含 agent_log']], ['业务步骤', '执行模块', '步骤说明', '实际状态'])}

### 诊断输出

| 推荐难度 | 学习风格 | 整体置信度 |
|---|---|---|
| {actual_difficulty} | {actual_style} | {diagnosis.get('overall_confidence', '')} |

### 审核输出

{_fmt_table(audit_rows or [['-', '-', '-', '-']], ['资源类型', '审核结论', '幻觉数', '不可验证数'])}

### 生成资源

{_fmt_table(resource_rows or [['-', '-', '-']], ['资源类型', '标题', '难度'])}

## 3 断言与测试结论

{_fmt_table(assertions, ['断言项', '预期真值', '系统实测', '结果'])}

本用例{'全部断言通过' if passed else '存在未通过断言'}。完整的输入、诊断、协同日志、审核明细和资源正文见 `03_输入输出示例/{safe_name}/`。

## 4 可复现性

```bash
python submission_test_data/_build/generate_samples.py
python submission_test_data/_build/build_package.py
```

本记录的原始响应文件 SHA-256：`{raw_hash}`。
"""
        record_file = EXECUTION_DIR / f"{case_id}_{safe_name}.md"
        record_file.write_text(body, encoding="utf-8")
        manifest_cases.append({
            "case_id": case_id,
            "scenario": scenario,
            "profile_id": pid,
            "http_status": sample.get("http_status"),
            "expected": {"difficulty": expected_difficulty, "learning_style": expected_style},
            "actual": {"difficulty": actual_difficulty, "learning_style": actual_style},
            "passed": passed,
            "record": record_file.name,
        })
        summary_rows.append([case_id, scenario, pid, actual_difficulty, actual_style, "通过" if passed else "不通过"])

    manifest = {
        "source": "_build/raw_samples.json",
        "source_sha256": raw_hash,
        "source_captured_at": captured_at,
        "cases": manifest_cases,
    }
    (EXECUTION_DIR / "test_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = _md_h1("端到端测试执行汇总", "D I K 三组画像的原始 API 调用记录")
    summary += "本目录将测试数据、原始响应、系统生成过程、断言和结论放在同一条追溯链中。\n\n"
    summary += _fmt_table(summary_rows, ["用例", "场景", "数据 ID", "实测难度", "实测风格", "结论"])
    summary += "\n\n每个用例的详细过程见对应 `E2E-*.md`；机器可读清单见 `test_manifest.json`。\n"
    (EXECUTION_DIR / "测试汇总报告.md").write_text(summary, encoding="utf-8")


def main() -> int:
    print("== 1/4 构建知识库切片 ==")
    slice_info = build_kb_slice()
    write_slice_readme(slice_info)
    print(f"   core 切片文档 {len(slice_info['copied_files'])} 篇 → {KB_SLICE_DIR}")

    print("== 2/4 复制学习者画像 ==")
    write_profile_dir()

    print("== 3/4 拆分端到端样例 ==")
    samples = load_json(RAW_SAMPLES)["samples"]
    profiles = {p["id"]: p for p in load_json(PROFILES)["profiles"]}
    for s in samples:
        build_example(s, profiles)
        print(f"   {s['profile_id']} → {EXAMPLES_DIR}")
    print("== 4/4 生成测试执行记录 ==")
    write_execution_records(samples, profiles)
    print(f"   D/I/K 执行记录 → {EXECUTION_DIR}")
    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

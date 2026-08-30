"""确定性生成 data/alarm_index.json 与 data/instruction_index.json。

从 data/raw/ 的**文件名 + H1 标题 + 头部要点元数据**派生，不做任何 LLM 推断，
确保索引与源文档一一对应、可复现（新增/删除文档后重跑即可刷新）。

依据（CLAUDE.md §6 防幻觉铁律）：
- 品牌、报警代码、指令名全部从文件名/标题的**结构化命名**正则提取，不脑补。
- fault_name / symptom 从文档正文的「故障名称」表格行与「摘要」要点行**原样转录**。
- 无法确定性判别的文档直接跳过（不猜测），保证索引里每一条都能追溯到源文件。

用法：
    python scripts/build_lookup_indexes.py

输出：
    data/alarm_index.json        # 报警故障排查库索引（brand + alarm_code → doc）
    data/instruction_index.json  # 分品牌指令速查索引（brand + instruction → doc）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# ── 品牌识别：文件名/标题关键词 → 品牌名（顺序敏感，先长后短避免误配）──────────
BRAND_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("FANUC", ("fanuc", "发那科")),
    ("KUKA", ("kuka", "库卡")),
    ("ABB", ("abb",)),
    ("Yaskawa", ("yaskawa", "yrc1000", "安川")),
    ("UR", ("ur ", "_ur_", " polyscope", "ursim")),
    ("OSHA", ("osha",)),
    ("SIEMENS", ("siemens",)),
    ("NVIDIA", ("nvidia",)),
]

# 报警代码正则：FANUC SRVO-xxx / Yaskawa ALARM xxxx（含双代码 230_231 / 0020_0021）
_SRVO_RE = re.compile(r"srvo[_\-]?(\d{3})", re.IGNORECASE)
_SRVO_DUAL_RE = re.compile(r"srvo[_\-]?(\d{3})[_\-](\d{3})", re.IGNORECASE)
_ALARM_RE = re.compile(r"alarm[_\-]?(\d{4})", re.IGNORECASE)
_ALARM_DUAL_RE = re.compile(r"alarm[_\-]?(\d{4})[_\-](\d{4})", re.IGNORECASE)

# ABB SafeMove / IRC5 故障 slug（无数字代码，用命名 slug 作 code）
_SF_RE = re.compile(r"sf[_\-](\w+)", re.IGNORECASE)
_IRC5_RE = re.compile(r"irc5[_\-](\w+)", re.IGNORECASE)

# 指令名：标题「ABB RAPID <指令>」「UR <节点>」中的紧邻词
_RAPID_INSTRUCTION_RE = re.compile(r"\b(?:ABB\s*)?RAPID\s+([A-Za-z][A-Za-z0-9]*)", re.IGNORECASE)
_UR_INSTRUCTION_RE = re.compile(r"\bUR\s+([A-Za-z][A-Za-z0-9]*)", re.IGNORECASE)

# 头部元数据：故障名称表格行 / 摘要要点行
_FAULT_NAME_RE = re.compile(r"\|\s*故障名称\s*\|\s*([^|\n]+?)\s*\|")
_SUMMARY_RE = re.compile(r"[-*]\s*(?:\*\*)?摘要(?:\*\*)?\s*[：:]\s*(.+)")


def _stem_and_title(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# ") and not s.startswith("## "):
            title = s[2:].strip()
            break
    return path.stem, title, text


def _detect_brand(stem: str, title: str) -> str:
    hay = f"{stem} {title}".lower()
    for brand, markers in BRAND_MARKERS:
        if any(m in hay for m in markers):
            return brand
    return ""


def _alarm_code(brand: str, stem: str) -> str:
    """从文件名提取报警代码；无确定性代码返回空串。"""
    if brand == "FANUC":
        m = _SRVO_DUAL_RE.search(stem)
        if m:
            return f"SRVO-{m.group(1)}/{m.group(2)}"
        m = _SRVO_RE.search(stem)
        if m:
            return f"SRVO-{int(m.group(1)):03d}"
    if brand == "Yaskawa":
        m = _ALARM_DUAL_RE.search(stem)
        if m:
            return f"ALARM {m.group(1)}/{m.group(2)}"
        m = _ALARM_RE.search(stem)
        if m:
            return f"ALARM {m.group(1)}"
    if brand == "ABB":
        m = _SF_RE.search(stem)
        if m:
            return f"SF {m.group(1).upper()}"
        m = _IRC5_RE.search(stem)
        if m:
            return f"IRC5 {m.group(1).upper()}"
    return ""


def _instruction_name(brand: str, title: str) -> str:
    """从标题提取单个指令/节点名；非「一指令一篇」文档返回空串。"""
    if brand == "ABB":
        m = _RAPID_INSTRUCTION_RE.search(title)
        return m.group(1) if m else ""
    if brand == "UR":
        m = _UR_INSTRUCTION_RE.search(title)
        return m.group(1) if m else ""
    return ""


def build_alarm_index() -> list[dict]:
    entries: list[dict] = []
    k3 = RAW / "K3_safety_fault"
    if not k3.exists():
        return entries
    for md in sorted(k3.glob("*.md")):
        doc_id, title, text = _stem_and_title(md)
        brand = _detect_brand(doc_id, title)
        code = _alarm_code(brand, doc_id)
        if not code:
            # 无确定性报警代码的文档（OSHA/PLC/纯安全指南）不入报警索引
            continue
        fault_name = ""
        m = _FAULT_NAME_RE.search(text)
        if m:
            fault_name = m.group(1).strip()
        symptom = ""
        m = _SUMMARY_RE.search(text)
        if m:
            symptom = m.group(1).strip()
        entries.append(
            {
                "brand": brand,
                "alarm_code": code,
                "fault_name": fault_name,
                "symptom": symptom,
                "doc_id": doc_id,
                "doc_title": title,
                # source 回指 data/raw 源文档，证明本条目确定性转录、非模型杜撰（铁律 2）
                "source": f"data/raw/K3_safety_fault/{doc_id}.md",
            }
        )
    return entries


def build_instruction_index() -> list[dict]:
    entries: list[dict] = []
    for subdir in ("K1_robot_base", "K2_robot_simulation"):
        d = RAW / subdir
        if not d.exists():
            continue
        for md in sorted(d.glob("*.md")):
            doc_id, title, _ = _stem_and_title(md)
            brand = _detect_brand(doc_id, title)
            instruction = _instruction_name(brand, title)
            if not instruction:
                continue
            entries.append(
                {
                    "brand": brand,
                    "instruction": instruction,
                    "doc_id": doc_id,
                    "doc_title": title,
                    # source 回指 data/raw 源文档，证明本条目确定性转录、非模型杜撰（铁律 2）
                    "source": f"data/raw/{subdir}/{doc_id}.md",
                }
            )
    return entries


def main() -> None:
    alarms = build_alarm_index()
    instructions = build_instruction_index()

    # 稳定排序：品牌 + 代码/指令
    alarms.sort(key=lambda e: (e["brand"], e["alarm_code"]))
    instructions.sort(key=lambda e: (e["brand"], e["instruction"]))

    (ROOT / "data" / "alarm_index.json").write_text(
        json.dumps(alarms, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "data" / "instruction_index.json").write_text(
        json.dumps(instructions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"alarm_index.json: {len(alarms)} 条")
    print(f"instruction_index.json: {len(instructions)} 条")


if __name__ == "__main__":
    main()

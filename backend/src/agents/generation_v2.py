"""
Agent 2: 领域知识生成 Agent（融合版）
══════════════════════════════════
负责: 角色5 实现

MVP 版本: 直接用 LLM 自身知识生成内容（不依赖外部知识库）
Phase 2 版本: 接入 RAG 知识库，约束生成 + 溯源

输入: state["diagnosis_result"] + state["resource_types"]
输出: state["generated_resources"] (list of GeneratedResource)

融合改进点:
  - Untitled-1.py: 资源数量上限、结构化内容模板、更清晰的 _fmt_gaps
  - 原 generation.py: prompt 代码块转义、项目代码风格
  - 新增: 循环容错（部分成功）、float() 类型保护、OPTIONAL_STATE_KEYS 补全
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from .base import BaseAgent


def _reason_text(value: object) -> str:
    """把错误原因（字符串或字符串列表）归一成一句中文，供 detail/raw_error 展示。"""
    if isinstance(value, (list, tuple)):
        return "；".join(str(v) for v in value if str(v).strip())
    return str(value or "").strip()


# (难度, 学习风格) → 画像标签 的主映射（与 data/evaluation/learner_profiles.json 的 7 画像对齐）
_PROFILE_TAG_BY_DIFF_STYLE: dict[tuple[str, str], str] = {
    ("beginner", "visual"): "zero_basis",  # D 纯零基础·行业外转行
    ("beginner", "theory_first"): "heard_only",  # E 有背景·仅听过机器人
    ("intermediate", "practice_first"): "hands_on_operator",  # G 实操型·会操作不懂原理
    ("advanced", "practice_first"): "skilled_engineer",  # I 熟练工程师·日常使用
    ("advanced", "project_based"): "authority_expert",  # J 权威型·技术大能
}


def derive_profile_tag(learner_data: dict, difficulty: str, style: str) -> str:
    """按 (难度, 风格) + 背景纯规则推导画像标签（7 画像之一，无 LLM 脑补）。

    intermediate + theory_first 需细分：
      - F 理论型（0 工作年限 / 实习生）→ theory_student
      - H 均衡初级（有工作年限）        → balanced_junior
    其余 (难度, 风格) 组合若未命中 7 画像，返回中性兜底 "custom"。

    供生成 / 修正 Agent 共享，避免画像规则散落多处（CLAUDE.md §6.4 多文件归并）。
    """
    tag = _PROFILE_TAG_BY_DIFF_STYLE.get((difficulty, style))
    if tag:
        return tag
    if (difficulty, style) == ("intermediate", "theory_first"):
        try:
            work_years = float(learner_data.get("work_years") or 0)
        except (ValueError, TypeError):
            work_years = 0.0
        positions = " ".join(learner_data.get("positions") or [])
        if work_years <= 0 or "实习" in positions:
            return "theory_student"
        return "balanced_junior"
    return "custom"


SYSTEM_PROMPT = """你是一个垂直领域的知识专家和教育内容创作者。你的任务是：
1. 根据学习者的知识盲区（skill_gaps）和推荐难度，用你的专业知识生成个性化学习资源
2. 生成的内容必须准确、实用，代码示例可以直接运行
3. 个性化体现在：解释深度、示例复杂度、学习路径建议

生成资源类型：
- lecture（定制讲义）：系统性理论讲解，含代码示例
- guide（实操指南）：分步操作手册，含真实命令行和完整代码
- quiz（分阶测试题）：选择题/填空题/实操题，分基础/进阶/挑战三级
- project（工业场景项目实战）：真实工业工作站全流程项目方案 + 调试步骤 + 阶段验收标准
- pitfall_guide（新手避坑指南）：整理常见操作误区、错误后果与规避方法

## 难度矩阵（唯一有效标准，禁止使用其他旧标准）
- beginner：零基础入门。多用生活类比与比喻，术语首次出现必须给白话解释，每行代码加注释。
- intermediate：有基础进阶。专业术语可直接使用，仅对关键步骤加注释，引入进阶概念。
- advanced：熟练/专家级。直接用行业术语，精简解释，聚焦架构权衡与高质量代码。

## 学习风格（4 种，唯一有效标准）
- theory_first：先讲清原理（为什么），再给代码/操作。
- practice_first：先给可执行步骤/代码，再解释原理。
- visual：偏好图片、示意图、动画演示，少大段文字，多用步骤拆解，适合零基础入门。
- project_based：以真实案例、项目任务驱动讲解，结合实际场景做练习，适合有基础的学习者。

重要规则：
- 学情盲区标注了 critical 的知识点 → 这是本次生成必须覆盖的核心内容
- 严格遵循系统传入的结构化画像参数（difficulty / learning_style / profile_tag）
- **禁止自行脑补或改写难度与学习风格**：输出 difficulty_level 必须与传入 difficulty 完全一致，
  表达方式必须与传入 learning_style 一致，不得混用其他风格

输出必须为严格的 JSON 格式。

## 主题锁定铁律（最高优先级，不可违反）
- 必须严格忠实于学习者输入的学习目标与课题主题，严禁篡改、替换、偷换课题主题。
- 知识库检索召回的参考资料若与当前学习课题无关，直接丢弃该批片段，
  禁止复用历史其他课题的课件模板与结构。
- 禁止把任务漂移到工业机器人、库卡（KUKA）、机器视觉、FANUC、ABB 示教器等与当前课题无关的领域。
- 生成的资源标题、核心知识点、代码示例、测试题必须全部围绕当前学习课题展开。

## 工业机器人领域质量约束（仅当课题属于工业机器人领域时生效）
- 品牌锚定：涉及具体操作/指令时声明适用品牌（FANUC / KUKA / ABB）；
  未明确品牌版本时标注「通用原理，具体以对应品牌官方手册为准」。
- 安全红线：实操类内容前置独立「安全」章节；运动/示教步骤附带安全提示，
  严禁描述违反安全规程的操作。
- guide 强制结构（缺一不可）：① 独立「安全」标题章节 ② 「安全操作确认清单」章节
  ③ 每个运动操作步骤前输出独立引用块「> ⚠️ 安全提示」 ④ 「常见异常与排错」对照模块。
- 版本适配：区分控制器代际差异（KUKA C4/C5、FANUC 30iB/Plus）；
  未指定版本时避免生成特定版本专属指令，标注「以官方手册为准」。
- 难度层级：入门级严禁引入视觉集成、离线编程、外部轴等高级主题。
- AI 融合边界：AI 相关内容符合工业落地实际，明确适用场景、技术依赖与局限性，
  不脱离工业总线/通信协议夸大自动化程度。"""


# 工业机器人领域强标记（主题漂移检测 / 无关片段过滤用）。
# 只收录机器人领域高特异词汇，避免误伤数控机床等相邻领域——
# 例如「坐标系」「伺服」「G代码」在 CNC 中同样常见，故不收录。
_ROBOT_DRIFT_MARKERS: tuple[str, ...] = (
    "机器人",
    "工业机器人",
    "库卡",
    "KUKA",
    "示教器",
    "机器视觉",
    "机械臂",
    "六轴",
    "码垛",
    "焊接机器人",
    "搬运机器人",
)

# 无知识库素材自生成时的免责声明（代码层面硬拼接，禁止 LLM 改写润色）。
# 主题仍被主题锁定铁律 + _topic_drift_failure 兜底约束，仅声明「非权威、不保证真实」。
NO_KB_DISCLAIMER = (
    "【提示：以下内容由模型基于通用知识生成，未依据本地知识库，"
    "系统不保证其真实性与工业实操准确性，仅供学习参考】"
)

# ── 工业机器人领域质量约束（B档生成硬约束 + A档确定性结构后置校验）──
# 词表均从 data/raw 语料溯源（FANUC/KUKA/ABB/RAPID/KRL/IRC5/R-30iB 等真实出现），
# 仅用于结构性/存在性判定，不做内容正确性审查（正确性交下游 Agent3，见 CLAUDE.md §6.1）。

#: 品牌声明标记：讲义/指南须命中其一，或命中 _GENERIC_BRAND_MARKERS（通用原理）
_ROBOT_BRAND_MARKERS: tuple[str, ...] = (
    "FANUC",
    "发那科",
    "KUKA",
    "库卡",
    "ABB",
    "RAPID",
    "KRL",
    "KRC4",
    "IRC5",
    "R-30iB",
    "30iB",
)

#: 未明确品牌版本时的「通用原理」类声明标记
_GENERIC_BRAND_MARKERS: tuple[str, ...] = (
    "通用原理",
    "品牌通用",
    "行业通用",
    "通用流程",
    "以官方手册为准",
)

#: 品牌「名称」声明标记（仅品牌名/中文别名，不含专属术语）：用于品牌混淆判定时
#: 区分「显式声明了哪个品牌」与「用了哪个品牌的术语」两个概念。
#: 注意：与 _ROBOT_BRAND_MARKERS（含 RAPID/KRL/IRC5 等术语作声明）职责不同，勿混用。
_BRAND_NAME_MARKERS: dict[str, tuple[str, ...]] = {
    "FANUC": ("FANUC", "发那科"),
    "KUKA": ("KUKA", "库卡"),
    "ABB": ("ABB",),
}

#: 指令级品牌专属术语（补充 brand-lexicon.json 未覆盖的指令/按键概念，仅用于
#: quiz 用户指定品牌时的强校验；不参与 lecture/guide 既有品牌混淆判定）。
#: - 中文语境词（SHIFT键/TP语言/J·L指令）用大小写不敏感子串匹配（含中文语境，无误伤）；
#: - 纯 ASCII 指令词（PTP/LIN/CIRC）必须大小写敏感 + 词边界，避免误伤 linear/link/circle。
#: ABB 专属指令术语（RAPID/FlexPendant）已由 brand-lexicon.json 覆盖，此处不重复。
_INSTRUCTION_BRAND_CN_TERMS: dict[str, tuple[str, ...]] = {
    "FANUC": (
        "SHIFT键",
        "SHIFT 键",
        "TP语言",
        "TP 语言",
        "TP程序",
        "TP 程序",
    ),
    "KUKA": (),
    "ABB": (),
}

_INSTRUCTION_BRAND_ASCII_TERMS: dict[str, tuple[str, ...]] = {
    "FANUC": (),
    "KUKA": ("PTP", "LIN", "CIRC"),
    "ABB": (),
}


def _build_ascii_instruction_re():
    """由 _INSTRUCTION_BRAND_ASCII_TERMS 生成大小写敏感 + 词边界正则，避免词表与正则失同步。"""
    terms = sorted({t for ts in _INSTRUCTION_BRAND_ASCII_TERMS.values() for t in ts})
    if not terms:
        return re.compile(r"(?!)")  # 永不匹配
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b")


_ASCII_INSTRUCTION_TERMS_RE = _build_ascii_instruction_re()

#: FANUC 的 J/L 运动指令（中文语境「J 指令 / L 指令」）。单字母指令名，必须词边界
#: 匹配，避免误伤 ABB 的 MoveJ/MoveL 等以 J/L 结尾的指令名（MoveJ 无词边界）。
_FANUC_JL_INSTRUCTION_RE = re.compile(r"\b[JL]\s*指令")

#: 品牌强约束 prompt 文案（用户指定品牌时注入，与校验词表语义一致）
_BRAND_CONSTRAINT_TEXT: dict[str, str] = {
    "KUKA": (
        "所有内容必须围绕 KUKA（库卡）机器人：使用 KRL 语言、smartPAD 示教器、"
        "PTP/LIN/CIRC 指令、KRC4/KRC5 控制器。禁止出现 FANUC 的 SHIFT 键、TP 语言、"
        "J/L 指令，禁止出现 ABB 的 RAPID 语言、FlexPendant 示教器。"
    ),
    "FANUC": (
        "所有内容必须围绕 FANUC（发那科）机器人：使用 TP 语言、SHIFT 键、"
        "J/L 运动指令、R-30iB 控制器。禁止出现 KUKA 的 KRL 语言、smartPAD、"
        "PTP/LIN/CIRC 指令，禁止出现 ABB 的 RAPID 语言、FlexPendant 示教器。"
    ),
    "ABB": (
        "所有内容必须围绕 ABB 机器人：使用 RAPID 语言、FlexPendant 示教器、"
        "MoveJ/MoveL 指令、IRC5/OmniCore 控制器。禁止出现 KUKA 的 KRL 语言、smartPAD、"
        "PTP/LIN/CIRC 指令，禁止出现 FANUC 的 TP 语言、SHIFT 键、J/L 指令。"
    ),
}

#: 品牌专属术语词表路径（data/brand-lexicon.json，由盘点脚本/人工维护，只读）
_BRAND_LEXICON_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "brand-lexicon.json"
)

#: 词表惰性缓存：文件缺失或解析失败时缓存空 dict，不阻断主流程
_brand_lexicon_cache: dict[str, list[str]] | None = None


def _load_brand_lexicon() -> dict[str, list[str]]:
    """读取 data/brand-lexicon.json 的品牌专属术语词表（确定性、只读、容错）。

    返回 {品牌: [专属术语]}；文件缺失/解析失败返回空 dict（本项校验降级为不拦截），
    绝不因词表问题阻断生成主流程。
    """
    global _brand_lexicon_cache
    if _brand_lexicon_cache is None:
        _brand_lexicon_cache = {}
        try:
            data = json.loads(_BRAND_LEXICON_PATH.read_text(encoding="utf-8"))
            brands = data.get("brands", {})
            _brand_lexicon_cache = {
                str(brand): [str(t) for t in terms]
                for brand, terms in brands.items()
                if isinstance(terms, list)
            }
        except Exception:
            _brand_lexicon_cache = {}
    return _brand_lexicon_cache


# ── 二期-2 速查链接接线（指令速查手册 + 报警排查库，确定性，不调 LLM）──
# 索引由 scripts/build_lookup_indexes.py 生成、main.py::_load_index 已消费；
# 此处复用同一批 JSON，仅做「生成内容识别 + 跳转链接字段」接线，不重复造索引。

#: 三品牌白名单：与二期-1 _BRAND_NAME_MARKERS 边界一致，排除索引里的 UR/Yaskawa
_THREE_BRANDS: frozenset[str] = frozenset({"FANUC", "KUKA", "ABB"})

#: 分品牌指令速查索引路径（data/instruction_index.json，只读）
_INSTRUCTION_INDEX_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "instruction_index.json"
)

#: 高频报警排查索引路径（data/alarm_index.json，只读）
_ALARM_INDEX_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "alarm_index.json"
)

#: 索引惰性缓存：文件缺失/解析失败缓存空列表，不阻断主流程
_instruction_index_cache: list[dict] | None = None
_alarm_index_cache: list[dict] | None = None


def _load_lookup_index(path: Path) -> list[dict]:
    """读取单个速查索引 JSON 并按三品牌过滤（供下方两个 loader 复用）。

    文件缺失/解析失败/非列表结构返回空列表；仅保留 brand ∈ {FANUC, KUKA, ABB}
    的条目，排除索引里混入的 UR/Yaskawa 等第 4/5 品牌。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [
        {str(k): v for k, v in entry.items()}
        for entry in data
        if isinstance(entry, dict) and entry.get("brand") in _THREE_BRANDS
    ]


def _load_instruction_index() -> list[dict]:
    """读取 instruction_index.json 的三品牌指令条目（惰性缓存、fail-open）。"""
    global _instruction_index_cache
    if _instruction_index_cache is None:
        _instruction_index_cache = _load_lookup_index(_INSTRUCTION_INDEX_PATH)
    return _instruction_index_cache


def _load_alarm_index() -> list[dict]:
    """读取 alarm_index.json 的三品牌报警条目（惰性缓存、fail-open）。"""
    global _alarm_index_cache
    if _alarm_index_cache is None:
        _alarm_index_cache = _load_lookup_index(_ALARM_INDEX_PATH)
    return _alarm_index_cache


#: 入门级超纲标记：beginner 内容命中即可能超纲（视觉/离线/外部轴等高级主题）。
#: 判定分级：出现 >= _BEGINNER_ADVANCED_EXPANSION_THRESHOLD 次视为「大段展开讲解」→ 判超纲；
#: 出现 1~阈值-1 次视为「轻度提及」→ 允许保留，仅日志标记（不整篇丢弃）。
_BEGINNER_ADVANCED_MARKERS: tuple[str, ...] = (
    "视觉集成",
    "视觉引导",
    "机器视觉",
    "离线编程",
    "离线仿真",
    "数字孪生",
    "外部轴",
    "轨迹规划",
    "深度学习",
    "强化学习",
)

#: 入门级超纲「大段展开」判定阈值：marker 出现次数 >= 该值即判大段展开（丢弃）；
#: 低于该值视为轻度提及，保留资源仅日志标记。
_BEGINNER_ADVANCED_EXPANSION_THRESHOLD = 3

#: 结构「缺章节/缺安全提示」类可恢复失败标记：命中这些关键词的校验失败为「缺结构」，
#: 重试仍缺失时降级保留并标记「结构不完整」（guide 交下游修正 Agent 补全，project 等直接标记）；
#: 品牌锚定/品牌混淆/入门超纲等致命失败仍判丢弃。
_RECOVERABLE_STRUCTURE_FAILURE_MARKERS: tuple[str, ...] = (
    "安全操作确认清单",
    "运动步骤安全提示",
    "独立「安全」标题章节",
    "常见异常与排错",
)

#: quiz 安全规范类题目标记：用于安全题占比 ≥20% 统计
_QUIZ_SAFETY_MARKERS: tuple[str, ...] = (
    "安全",
    "急停",
    "使能",
    "限速",
    "安全门",
    "Deadman",
    "E-Stop",
    "光栅",
)

#: pitfall_guide「常见误区」标记：避坑指南正文须命中其一（误区/错误做法/易错等）。
#: 注意：不含「避坑」——「避坑指南」是资源类型名，正文标题几乎必含该词，会导致校验恒真。
_PITFALL_MARKERS: tuple[str, ...] = (
    "误区",
    "常见错误",
    "错误做法",
    "易错",
    "踩坑",
)

#: pitfall_guide「原因/成因」标记：避坑指南正文须命中其一（讲清误区背后的机理）
_CAUSE_MARKERS: tuple[str, ...] = (
    "原因",
    "成因",
    "根因",
)

#: pitfall_guide「规避/正确做法」标记：避坑指南正文须命中其一，与 _PITFALL_MARKERS 成对校验
_AVOIDANCE_MARKERS: tuple[str, ...] = (
    "规避",
    "避免",
    "正确做法",
    "改进",
    "预防",
    "建议",
)

#: guide 结构存在性正则：独立「安全」标题章节 / 「异常与排错」对照模块
_GUIDE_SAFETY_HEADING_RE = re.compile(r"^\s*#{1,6}\s*[^\n]*安全[^\n]*$", re.MULTILINE)
_GUIDE_TROUBLESHOOT_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*[^\n]*(故障|异常|排错|报警)[^\n]*$", re.MULTILINE
)

# ── 工业实操安全分级（确定性，不调 LLM；危险 ≠ 难度）──
# 运动类/软件类标记从用户安全规范与 data/raw 语料溯源，仅做存在性判定。

#: 运动类高危操作标记：命中即判 high_risk（示教/点动/运行/IO调试等带动机械臂的操作）
_HIGH_RISK_MOTION_MARKERS: tuple[str, ...] = (
    "示教",
    "点动",
    "运行程序",
    "程序运行",
    "自动运行",
    "手动运行",
    "连续运行",
    "单步运行",
    "单步执行",
    "试运行",
    "轨迹运行",
    "使能",
    "手动模式",
    "手动移动",
    "移动机器人",
    "移动机械臂",
    "IO调试",
    "I/O调试",
    "信号调试",
    "倍率",
    "校准",
    "标定",
    "回零",
    "搬运",
    "码垛",
    "焊接",
)

#: 软件类低危操作标记：仅在未命中运动类标记时判 low_risk
_LOW_RISK_SOFTWARE_MARKERS: tuple[str, ...] = (
    "参数查看",
    "查看参数",
    "参数设置",
    "程序编辑",
    "编辑程序",
    "离线编程",
    "离线仿真",
    "仿真",
    "备份",
    "还原",
    "变量",
    "监控",
)

#: 逐步安全提示引用块：`> ⚠️ 安全提示：…`（容忍有无 ⚠️）
_SAFETY_WARNING_RE = re.compile(r"^\s*>\s*(?:⚠️\s*)?安全提示[:：]\s*(?P<text>.+)$", re.MULTILINE)

#: high_risk 实操须含的「安全操作确认清单」标题
_CHECKLIST_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*[^\n]*(安全操作确认清单|安全确认清单)[^\n]*$", re.MULTILINE
)

#: 品牌/控制器/机型 token → 展示名（纯子串匹配；token 未出现即永不命中，不杜撰）。
#: 词表溯源自 data/raw 文件名真实出现的 token（fanuc/kuka/abb/yaskawa/yrc1000/irc5/
#: profisafe/crx），另附常见控制器代际，仅在正文/标题真实出现时命中。
_BRAND_TOKEN_MAP: tuple[tuple[str, str], ...] = (
    ("fanuc", "FANUC"),
    ("发那科", "FANUC"),
    ("kuka", "KUKA"),
    ("库卡", "KUKA"),
    ("abb", "ABB"),
    ("yaskawa", "Yaskawa"),
    ("安川", "Yaskawa"),
)
_CONTROLLER_TOKEN_MAP: tuple[tuple[str, str], ...] = (
    ("yrc1000", "YRC1000"),
    ("irc5", "IRC5"),
    ("profisafe", "PROFIsafe"),
    ("r-30ib", "R-30iB"),
    ("krc4", "KRC4"),
    ("krc5", "KRC5"),
    ("s4c", "S4C"),
    ("dx200", "DX200"),
)
_MODEL_TOKEN_MAP: tuple[tuple[str, str], ...] = (("crx", "CRX"),)


class GenerationAgent(BaseAgent):
    """领域知识生成 Agent — 角色5 在此实现

    根据学情诊断结果（diagnosis_result），为每种请求的资源类型
    （lecture / guide / quiz / project / pitfall_guide）生成一份个性化学习资源。

    资源数量上限为 5，防止单次请求过度消耗 token。
    单个资源生成失败不影响其他资源（部分成功）。
    """

    REQUIRED_STATE_KEYS = {"diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "learner_data",
        "resource_types",
        "retrieved_chunks",  # Phase 2 RAG 知识库检索结果，MVP 阶段可选
        "task_id",
        "agent_log",
        "status",
        "diagnosis_completed",
    }

    # 资源数量上限（对齐前端 5 种资源类型），防止 token 过度消耗
    MAX_RESOURCES = 5

    # 主题漂移时的最大重试次数（不含首次生成）
    MAX_TOPIC_RETRIES = 2

    # 品牌混用（用户指定品牌时 quiz 强校验）的最大重试次数（不含首次生成）
    MAX_BRAND_RETRIES = 2

    # 结构校验失败时的最大重试次数（不含首次生成）
    MAX_STRUCTURE_RETRIES = 2

    def __init__(self):
        super().__init__(
            name="知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    @staticmethod
    def _build_generation_error(
        rtype: str,
        error: str,
        detail: object = None,
        stage: str = "",
        raw_error: object = None,
    ) -> dict:
        """构造统一的生成失败错误对象（前端展示 + 溯源）。

        - error: 保留机器可读错误码（程序判断用，不变）
        - detail: 用户可读中文原因；list 会拼成「；」分隔的一句话
        - stage: 失败阶段（llm_generate / topic_check / structure_check / quiz_check / generation）
        - timestamp: ISO 8601 UTC 时间，前端展示失败时间
        - raw_error: 原始异常 / 技术信息，供排查（前端折叠展示）
        """
        item: dict = {
            "resource_type": rtype,
            "error": error,
            "stage": stage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        detail_text = _reason_text(detail)
        if detail_text:
            item["detail"] = detail_text
        if raw_error is not None:
            item["raw_error"] = _reason_text(raw_error)
        return item

    async def process(self, state: dict) -> dict:
        """生成个性化学习资源。

        对每种请求的资源类型分别调用 LLM 生成一份资源。
        单个资源生成失败时记录错误但不阻断其他资源的生成（部分成功）。
        """
        diagnosis = state.get("diagnosis_result", {})
        learner_data = state.get("learner_data", {})
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])
        retrieved_chunks = state.get("retrieved_chunks", [])
        # 用户指定的目标机器人品牌（FANUC/KUKA/ABB），空/未提供 → 不强约束
        brand = self._normalize_brand(learner_data.get("brand"))

        # ── 主题对齐：丢弃与原始学习课题无关的检索片段（如非机器人课题丢弃机器人素材）──
        original_topic = str(learner_data.get("learning_goal", "") or "").strip()
        retrieved_chunks = self._filter_relevant_chunks(retrieved_chunks, original_topic)

        # ── 有效素材判定：无有效 KB chunk 时进入「无素材自生成」降级模式 ──
        # 主题锁定铁律 + _topic_drift_failure 兜底在两种模式下都生效，杜绝漂移到无关领域；
        # 无素材时允许模型凭通用知识生成，但必须打免责标记（系统不保证真实有效）。
        valid_chunks = [
            c for c in retrieved_chunks if isinstance(c, dict) and str(c.get("content", "")).strip()
        ]
        no_kb_mode = len(valid_chunks) == 0
        if no_kb_mode:
            self.log("⚠️ 无有效知识库素材，进入无素材自生成降级模式（主题锁定 + 免责标记）")

        # 安全上限：防止请求过多类型导致 token 爆炸
        resource_types = resource_types[: self.MAX_RESOURCES]

        resources = []
        errors = []
        learner_id = state.get("learner_id", "")
        # 本次生成覆盖的盲区知识点（与 schemas.GeneratedResource.target_skill_gaps 对齐）
        target_skill_gaps = [
            g.get("topic", "") for g in diagnosis.get("skill_gaps", []) if g.get("topic")
        ]
        for rtype in resource_types:
            try:
                result = await self._generate_one(diagnosis, rtype, retrieved_chunks, learner_data)
                # 解析失败（_parse_error）或空内容同样按失败处理，不当作资源
                if not result or result.get("_parse_error"):
                    self.log(f"⚠️ {rtype} 类型资源生成解析失败，跳过")
                    errors.append(
                        self._build_generation_error(
                            rtype,
                            "json_parse_failed",
                            detail=(
                                "生成结果解析失败：LLM 返回内容无法解析"
                                "为有效的结构化 JSON，已跳过该资源。"
                            ),
                            stage="llm_generate",
                            raw_error=(
                                result.get("_parse_error")
                                if isinstance(result, dict)
                                else "LLM 返回空内容"
                            ),
                        )
                    )
                    continue
                # 主题漂移自检兜底：重试仍无法对齐原始课题 → 丢弃，绝不把跑偏内容返回前端
                drift_error = result.get("_topic_drift_error")
                if drift_error:
                    self.log(f"⚠️ {rtype} 类型资源主题漂移，丢弃: {drift_error}")
                    errors.append(
                        self._build_generation_error(
                            rtype,
                            "topic_drift",
                            detail=drift_error,
                            stage="topic_check",
                            raw_error=drift_error,
                        )
                    )
                    continue
                # A档结构后置校验兜底：机器人领域资源未通过确定性结构校验 → 丢弃
                structure_error = result.get("_structure_validation_error")
                if structure_error:
                    self.log(f"⚠️ {rtype} 类型资源结构校验未通过，丢弃: {structure_error}")
                    structure_reason = _reason_text(structure_error)
                    errors.append(
                        self._build_generation_error(
                            rtype,
                            "structure_validation",
                            detail=f"结构校验未通过：{structure_reason}",
                            stage="structure_check",
                            raw_error=structure_reason,
                        )
                    )
                    continue
                # 品牌混用兜底：用户指定品牌但 quiz 混入其他品牌专属术语，重试仍失败 → 丢弃
                brand_mix_error = result.get("_brand_mix_error")
                if brand_mix_error:
                    self.log(f"⚠️ {rtype} 类型资源品牌混用，丢弃: {brand_mix_error}")
                    mix_reason = _reason_text(brand_mix_error)
                    errors.append(
                        self._build_generation_error(
                            rtype,
                            "brand_mix",
                            detail=f"测试题品牌混用：{mix_reason}",
                            stage="brand_check",
                            raw_error=mix_reason,
                        )
                    )
                    continue
                # 与 schemas.GeneratedResource 对齐：resource_id / learner_id /
                # resource_type 由本层补全，target_skill_gaps 从诊断结果推导
                quiz_validation_error = result.pop("_quiz_validation_error", None)
                if quiz_validation_error:
                    self.log(
                        "Quiz generation requires review before it can be automatically scored."
                    )
                    errors.append(
                        self._build_generation_error(
                            rtype,
                            "invalid_quiz_contract",
                            detail=quiz_validation_error,
                            stage="quiz_check",
                            raw_error=quiz_validation_error,
                        )
                    )
                    result["quiz_validation_status"] = "needs_review"
                    result["quiz_validation_error"] = quiz_validation_error
                result["resource_type"] = rtype
                result["resource_id"] = str(uuid.uuid4())
                result["learner_id"] = learner_id
                result.setdefault("target_skill_gaps", target_skill_gaps)
                # ── 工业实操安全打标（确定性，不调 LLM）──
                # 风险分级 + 逐步安全提示抽取对所有资源生效；品牌/控制器/机型元数据
                # 仅机器人领域实操类资源派生（从知识库 chunk 溯源，非 LLM 杜撰）。
                result["risk_level"] = self._classify_risk_level(
                    rtype, str(result.get("content", "") or "")
                )
                result["safety_warnings"] = self._extract_safety_warnings(
                    str(result.get("content", "") or "")
                )
                if self._contains_any(original_topic, _ROBOT_DRIFT_MARKERS) and rtype in (
                    "lecture",
                    "guide",
                    "project",
                ):
                    result["robot_metadata"] = self._derive_robot_metadata(retrieved_chunks)
                    # 用户指定品牌时覆盖元数据（KB 溯源品牌让位于用户显式目标品牌）
                    if brand:
                        result["robot_metadata"]["brand"] = brand
                # ── 二期-2 速查链接注入（确定性，不调 LLM）──
                # 仅机器人领域讲义/指南识别正文指令名、报警编号，注入跳转链接字段；
                # quiz 无指令速查价值，project 不在二期-2 范围。
                if self._contains_any(original_topic, _ROBOT_DRIFT_MARKERS) and rtype in (
                    "lecture",
                    "guide",
                ):
                    result["instruction_links"] = self._extract_instruction_links(
                        str(result.get("content", "") or "")
                    )
                    result["alarm_links"] = self._extract_alarm_links(
                        str(result.get("content", "") or "")
                    )
                resources.append(result)
                # 结构缺失章节：保留资源的同时，把缺失项写入 generation_errors 供前端/下游感知；
                # structure_incomplete 标记 = 重试后仍缺章节的降级保留（部分内容未经完整审核）。
                missing_sections = result.get("structure_missing_sections")
                if missing_sections:
                    missing_reason = _reason_text(missing_sections)
                    incomplete = bool(result.get("structure_incomplete"))
                    detail = (
                        f"结构不完整（部分内容未经完整审核，仅供参考）：{missing_reason}"
                        if incomplete
                        else f"缺少安全相关章节：{missing_reason}"
                    )
                    errors.append(
                        self._build_generation_error(
                            rtype,
                            "structure_sections_missing",
                            detail=detail,
                            stage="structure_check",
                            raw_error=missing_reason,
                        )
                    )
            except Exception as e:
                # 单个资源生成失败不阻断其他资源
                self.log(f"⚠️ {rtype} 类型资源生成失败: {e}")
                errors.append(
                    self._build_generation_error(
                        rtype,
                        str(e),
                        detail=f"生成异常：{type(e).__name__}：{e}",
                        stage="generation",
                        raw_error=str(e),
                    )
                )

        # ── 无素材自生成后处理：打免责标记（citations 置空 + 内容头部声明非权威）──
        if no_kb_mode:
            for r in resources:
                r["citations"] = []
                r["content"] = NO_KB_DISCLAIMER + "\n\n" + str(r.get("content", ""))
            self.log(f"⚠️ 无素材自生成 {len(resources)} 个资源，已打免责标记（系统不保证真实有效）")

        self.log(
            f"生成完成: {len(resources)}/{len(resource_types)} 个资源"
            + (f"，{len(errors)} 个失败" if errors else "")
        )
        return {
            "generated_resources": resources,
            **({"generation_errors": errors} if errors else {}),
            **({"downgrade_mode": True} if no_kb_mode else {}),
        }

    async def _generate_one(
        self,
        diagnosis: dict,
        rtype: str,
        retrieved_chunks: list | None = None,
        learner_data: dict | None = None,
    ) -> dict:
        """为单一资源类型生成内容。

        Args:
            diagnosis:        诊断结果 dict，含 skill_gaps / recommended_difficulty
                              / learning_style / summary / profile_tag(可选)
            rtype:            资源类型字符串（lecture / guide / quiz）
            retrieved_chunks: RAG 知识库检索结果列表
            learner_data:     学习者原始画像（用于纯规则推导 profile_tag，可选；
                              其中 brand 字段为用户指定的目标机器人品牌）

        Returns:
            LLM 返回的 dict；LLM 解析失败时返回 {}（由调用方过滤）。
        """
        gaps = diagnosis.get("skill_gaps", [])
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        learning_style = diagnosis.get("learning_style", "unknown")
        learning_goal = diagnosis.get("summary", "")
        # 原始学习课题（权威主题锚点）：优先取用户原始输入，诊断总结作为兜底
        original_topic = str((learner_data or {}).get("learning_goal", "") or "").strip()
        if not original_topic:
            original_topic = learning_goal
        # 课题是否属于机器人领域：决定是否注入机器人领域质量约束 + 结构后置校验
        is_robot_topic = self._contains_any(original_topic, _ROBOT_DRIFT_MARKERS)
        # 用户指定的目标机器人品牌（FANUC/KUKA/ABB），空=不强约束
        brand = self._normalize_brand((learner_data or {}).get("brand"))
        # 前端「重新生成」传入的上次失败反馈（resource_type/error/detail），空=首次生成
        failure_feedback = (learner_data or {}).get("failure_feedback")
        # 画像标签：优先取诊断显式字段，否则按 (难度, 风格, 背景) 纯规则推导
        profile_tag = diagnosis.get("profile_tag") or derive_profile_tag(
            learner_data or {}, difficulty, learning_style
        )

        # ── 结构化画像参数（权威，模型不可改写）──
        profile_params = {
            "difficulty": difficulty,
            "learning_style": learning_style,
            "profile_tag": profile_tag,
        }

        # ── 丢弃与课题无关的检索片段，再构建知识库上下文（RAG 约束生成）──
        relevant_chunks = self._filter_relevant_chunks(retrieved_chunks or [], original_topic)
        no_kb = not relevant_chunks
        kb_context = self._fmt_knowledge_base(relevant_chunks)

        # 有 KB 素材 → 权威生成（严禁引入幻觉）；无 KB 素材 → 通用知识自生成（免责标记）
        if no_kb:
            kb_section = (
                "## 知识库素材状态\n"
                "（知识库暂无与当前课题匹配的权威素材，本次生成依赖模型的通用知识，"
                "对不确定的具体参数、型号、菜单路径、报警代码、操作顺序须明确标注，"
                "严禁编造精确数值、菜单路径、报警代码、操作顺序或官方原文）"
            )
            task_instruction = "知识库暂无该课题的权威素材，请基于你的通用专业知识生成一份"
            req2 = (
                "2. **无权威素材，可用通用知识生成**：不确定的具体参数、型号、步骤、"
                "菜单路径、报警代码、操作顺序须标注「不确定」，"
                "严禁编造精确数值、菜单路径、报警代码、操作顺序或官方原文"
            )
            req8 = "8. citations 留空数组（本次无知识库溯源，内容已标注为非权威）"
        else:
            kb_section = kb_context
            task_instruction = "请**严格基于上述知识库参考资料**，生成一份"
            req2 = (
                "2. **内容必须基于上方知识库参考资料**，不得编造知识库中没有的技术细节；"
                "菜单路径、报警代码、参数值、操作顺序必须与资料一致，不确定处标注「以官方手册为准」"
            )
            req8 = "8. citations 中至少引用 2 条知识库原文片段"

        # ── 机器人领域硬约束块：仅当课题属于机器人领域时注入（非机器人课题如数控机床不注入）──
        robot_req_block = ""
        if is_robot_topic:
            robot_req_block = """

## 工业机器人领域硬约束（本课题属于机器人领域，必须遵守）
1. **品牌锚定**：涉及具体操作/指令时必须声明适用品牌（FANUC / KUKA / ABB），
   未明确品牌版本时标注「通用原理，具体以对应品牌官方手册为准」。
2. **安全红线**：实操类内容必须前置独立「安全」章节；运动/示教步骤附带安全提示，
   严禁描述违反安全规程的操作。
3. **版本适配**：涉及控制器代际差异（KUKA C4/C5、FANUC 30iB/Plus）须区分说明；
   未指定版本时不得生成特定版本专属指令，标注「以官方手册为准」。
4. **难度层级**：入门级严禁引入视觉集成、离线编程、外部轴、数字孪生等高级主题。
5. **AI 融合边界**：涉及 AI 的内容须符合工业落地实际，明确适用场景、技术依赖与局限性，
   不脱离工业总线/通信协议夸大自动化程度。
6. **结构要求**（后置校验会确定性检查；guide 缺章节将被标记由下游补全，其余不满足将被丢弃）：
   - guide 必须完整包含四部分（缺一不可）：① 独立「安全」标题章节 ② 「安全操作确认清单」
     ③ 每个运动操作步骤前独立引用块「> ⚠️ 安全提示」 ④ 「常见异常与排错」对照模块；
   - lecture/guide/project/pitfall_guide 必须声明品牌（FANUC/KUKA/ABB）或标注「通用原理」；
   - quiz 安全规范类题目占比不低于 20%；
   - pitfall_guide 必须含「常见误区」与「规避/正确做法」两类内容。
7. **高危实操安全清单**：涉及示教/点动/运行程序/IO调试等运动操作的 guide/project，
   正文开头须生成「安全操作确认清单」章节（含：安全门状态确认 / 急停按钮位置确认 /
   使能键使用规范 / 工作区间无人员确认 / 减速模式开启要求）；
   每个运动类操作步骤前，须输出独立引用块 `> ⚠️ 安全提示：…`，不得与普通步骤文本合并。
8. **事实准确（铁律）**：严禁编造菜单路径、报警代码、参数值、操作顺序；
   报警编号/指令名必须来自知识库或速查索引，无法确认时标注「以官方手册为准」，不得杜撰。"""

        # ── 目标品牌强约束块：用户指定品牌时注入（所有资源类型生效）──
        brand_req_block = self._brand_constraint(brand)
        # ── 上次失败反馈修正块：前端「重新生成」时按失败原因注入（只补结构不编内容）──
        feedback_block = self._failure_feedback_instruction(failure_feedback, rtype)

        prompt = f"""## 结构化画像参数（权威，禁止改写）
{json.dumps(profile_params, ensure_ascii=False)}

## 学习者画像
- 学习目标总结：{learning_goal}
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}

## 原始学习课题（主题锁定·最高优先级，严禁偏离）
{original_topic}

{kb_section}
{robot_req_block}{brand_req_block}{feedback_block}

## 生成任务
{task_instruction} {rtype} 类型的个性化学习资源。

## 输出 JSON
{{
    "title": "资源标题（要具体、有吸引力）",
    "content": "Markdown 格式的完整内容（含代码示例和命令行时用 `````` 标注语言类型）",
    "citations": [
        {{"ref_index": 1, "original_text": "引用的原文片段", "usage": "在内容中的用途说明"}}
    ],
    "difficulty_level": "{difficulty}",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["学完你能掌握什么1", "学完你能掌握什么2", "学完你能掌握什么3"]
}}

## 硬性要求
1. 内容必须准确——这是教育场景，教错了比不教更糟
{req2}
3. 代码示例完整可运行，命令行标注操作系统（Windows/Linux/Mac）
4. **难度锁定**：difficulty_level 必须严格等于结构化画像参数中的 difficulty（{difficulty}），
   禁止自行调整难度档位
5. **风格锁定**：内容表达方式必须与结构化画像参数中的 learning_style（{learning_style}）
   一致，禁止混用其他风格或自行脑补新风格
6. 五种资源固定内容结构：
   - lecture: 引言 → 3~4小节（概念+可运行代码）→ 总结
   - guide: 概述 → 前置准备 → 分步操作（命令+代码+预期输出）→ 常见问题
   - quiz: 基础选择题2道（含选项/标准答案/解析）→ 进阶题1道 → 挑战实操题1道
   - project: 项目背景与目标 → 工作站拆解 → 全流程方案 → 分步调试步骤 → 验收标准与风险点
   - pitfall_guide: 常见误区（错误做法）→ 原因 → 后果 → 规避方法（正确做法/改进建议）
7. 优先覆盖 critical 和 high 优先级的知识盲区
{req8}
9. **主题忠实**：全部内容（标题/知识点/示例/题目）必须围绕「原始学习课题」展开，
   严禁漂移到工业机器人、库卡（KUKA）、机器视觉、示教器等与课题无关的领域；
   与课题无关的知识库片段必须丢弃，禁止复用其他课题的课件模板"""

        if rtype == "quiz":
            prompt += """

## STRICT QUIZ CONTRACT
Create at least 5 distinct questions. Each question must have a unique, clear
stem and must be numbered in order as `\u7b2c1\u9898\uff1a` through `\u7b2c5\u9898\uff1a`.
The five-question minimum overrides any older resource-template instruction
that mentions a smaller quiz. Do not return fewer than five questions.
Every stem must be a self-contained question: state the operating condition or
task and ask the learner to make a decision. A section title or topic label is
not a question and must never be used as a question stem.
Write all learner-facing content in Simplified Chinese. Keep English only for
unavoidable product names, alarm codes, or technical abbreviations.
Use a mix of multiple-choice questions and one or two short-answer questions.
For a multiple-choice question, include exactly four options labelled A-D,
then include `\u7b54\u6848\uff1a<letter>` and `\u89e3\u6790\uff1a<reason>` immediately after
that question. A short-answer question has no A-D options, but must still have
one `\u7b54\u6848\uff1a<expected answer>` and one `\u89e3\u6790\uff1a<reason>` line.
Never place more than one A-D option group under one question heading. Include a
mix of recall, scenario, and application questions that is
relevant to the learner profile and the retrieved knowledge.
"""

        # ── 生成 + 主题自检：明显跑偏则重试，重试仍跑偏则丢弃（不返回前端）──
        result = await self.call_llm_json(prompt)
        drift_reason = self._topic_drift_failure(result, original_topic)
        attempt = 0
        while drift_reason is not None and attempt < self.MAX_TOPIC_RETRIES:
            attempt += 1
            self.log(f"⚠️ {rtype} 主题漂移，触发重新生成（第 {attempt} 次）: {drift_reason}")
            result = await self.call_llm_json(
                prompt + self._topic_reinforcement(original_topic, drift_reason)
            )
            drift_reason = self._topic_drift_failure(result, original_topic)
        if drift_reason is not None:
            self.log(f"❌ {rtype} 主题漂移无法纠正，丢弃结果: {drift_reason}")
            return {"_topic_drift_error": drift_reason}

        # ── quiz 品牌强校验（用户指定品牌时）：混入其他品牌专属术语 → 重生成 → 仍失败则丢弃 ──
        if rtype == "quiz" and brand:
            mix_failures = self._quiz_brand_mix_failure(str(result.get("content", "") or ""), brand)
            attempt = 0
            while mix_failures and attempt < self.MAX_BRAND_RETRIES:
                attempt += 1
                self.log(f"⚠️ {rtype} 品牌混用，触发重新生成（第 {attempt} 次）: {mix_failures}")
                result = await self.call_llm_json(
                    prompt + self._brand_reinforcement(brand, mix_failures)
                )
                mix_failures = self._quiz_brand_mix_failure(
                    str(result.get("content", "") or ""), brand
                )
            if mix_failures:
                self.log(f"❌ {rtype} 品牌混用无法纠正，丢弃: {mix_failures}")
                return {"_brand_mix_error": mix_failures}

        failure = self._quiz_contract_failure(result)
        if rtype == "quiz" and failure is not None:
            # A quiz without an answer key cannot be submitted, reviewed, or exported
            # as a self-study resource. Ask once more before it reaches the UI.
            # Keep valid question blocks intact. Only malformed questions are
            # regenerated, so a single bad item does not invalidate the whole quiz.
            repaired = await self._repair_quiz_questions(result, kb_context)
            failure = self._quiz_contract_failure(repaired)
            if failure is None:
                result = repaired
            elif isinstance(repaired, dict):
                result = {**repaired, "_quiz_validation_error": failure}
            else:
                result = {
                    "title": "Quiz requiring review",
                    "content": str(repaired or ""),
                    "_quiz_validation_error": failure or "题目结构无法解析",
                }

        # ── A档结构后置校验（确定性，不调 LLM）：仅机器人领域课题生效 ──
        # 只做结构性/存在性判定（品牌声明、安全章节、排错模块、入门超纲、quiz 安全占比），
        # 正确性审查交下游 Agent3，不在此新增 LLM 二次校验（CLAUDE.md §6.1）。
        # 结构失败先带原因重试（只补结构不编内容），重试仍失败再决定丢弃/降级保留。
        if is_robot_topic and "_quiz_validation_error" not in result:
            structure_failures = self._structure_validation_failure(result, rtype, difficulty)
            attempt = 0
            while structure_failures and attempt < self.MAX_STRUCTURE_RETRIES:
                attempt += 1
                self.log(f"⚠️ {rtype} 结构校验未通过，重新生成第 {attempt} 次: {structure_failures}")
                result = await self.call_llm_json(
                    prompt + self._structure_reinforcement(structure_failures)
                )
                structure_failures = self._structure_validation_failure(result, rtype, difficulty)

            if structure_failures:
                # 重试仍失败：缺章节/缺安全提示类失败（安全标题/安全清单/安全提示/排错）不整篇丢弃，
                # 降级保留并标记「结构不完整」；品牌锚定/品牌混淆/入门超纲等致命失败仍丢弃。
                recoverable = [
                    f for f in structure_failures if self._is_recoverable_structure_failure(f)
                ]
                fatal = [f for f in structure_failures if f not in recoverable]
                if fatal:
                    self.log(f"❌ {rtype} 结构校验未通过，丢弃: {fatal}")
                    return {"_structure_validation_error": fatal}
                self.log(
                    f"⚠️ {rtype} 结构缺失章节，重试后仍缺失，降级保留并标记结构不完整: {recoverable}"
                )
                if rtype == "guide":
                    # guide 缺章节交下游修正 Agent 补全（既有 _fill_structure_sections 路径）
                    result["structure_missing_sections"] = recoverable
                else:
                    # project 等：下游不补全，直接标记「结构不完整」供前端警示
                    result["structure_incomplete"] = True
                    result["structure_missing_sections"] = recoverable

        return result

    @staticmethod
    def _quiz_question_blocks(content: str) -> list[str]:
        """Split quiz content into independently repairable question blocks."""
        pattern = re.compile(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898|\d+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?\s*(?P<stem>.+)$"
        )
        matches = list(pattern.finditer(content))
        return [
            content[
                match.start() : (
                    matches[index + 1].start() if index + 1 < len(matches) else len(content)
                )
            ].strip()
            for index, match in enumerate(matches)
        ]

    @staticmethod
    def _quiz_block_stem(block: str) -> str:
        match = re.search(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898|\d+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?\s*(?P<stem>.+)$",
            block,
        )
        return match.group("stem").strip() if match else ""

    @staticmethod
    def _is_clear_quiz_stem(stem: str) -> bool:
        """Require an independently answerable question instead of a topic label."""
        normalized_stem = re.sub(r"\s+", "", stem).lower()
        if len(normalized_stem) < 4:
            return False

        heading_pattern = re.compile(
            r"(?i)^(?:(?:safety\s+operation\s+topic|topic|overview|introduction|basics|practice)\s*\d*|"
            r"(?:\u5b89\u5168\u64cd\u4f5c|\u6545\u969c\u8bca\u65ad|\u57fa\u7840\u539f\u7406|\u5750\u6807\u7cfb|\u64cd\u4f5c\u6d41\u7a0b))$"
        )
        question_type_label = re.compile(
            r"^[^?\uff1f]{1,80}[\(\uff08](?:\u57fa\u7840|\u8fdb\u9636|\u573a\u666f|\u5b9e\u64cd|\u6311\u6218)?"
            r"(?:\u9009\u62e9\u9898|\u7b80\u7b54\u9898|\u586b\u7a7a\u9898|\u5e94\u7528\u9898)?[\)\uff09]$"
        )
        task_signal = re.compile(
            r"[?\uff1f]|\b(?:which|what|how|why|when|where|should|can|does|describe|select|identify|choose|explain|state|list)\b|"
            r"(?:\u4ee5\u4e0b|\u54ea(?:\u4e2a|\u9879|\u79cd)|\u4ec0\u4e48|\u5982\u4f55|\u4e3a\u4ec0\u4e48|\u662f\u5426|\u8bf7(?:\u9009\u62e9|\u5224\u65ad|\u8bf4\u660e|\u5199\u51fa|\u5217\u51fa|\u56de\u7b54)|\u5e94(?:\u8be5|\u5f53)|\u6b63\u786e|\u9519\u8bef|\u6b65\u9aa4|\u539f\u56e0|\u64cd\u4f5c|\u5904\u7406|\u5224\u65ad)",
            re.IGNORECASE,
        )
        return (
            not heading_pattern.fullmatch(stem)
            and not question_type_label.fullmatch(stem)
            and bool(task_signal.search(stem))
        )

    @staticmethod
    def _quiz_block_failure(block: str) -> str | None:
        """Return the automatic-scoring failure for one question block."""
        stem = GenerationAgent._quiz_block_stem(block)
        if not stem:
            return "missing a numbered question stem"

        if not GenerationAgent._is_clear_quiz_stem(stem):
            return "the question stem is not a clear learner task"

        option_pattern = re.compile(
            r"(?im)^\s*(?:[-*]\s*)?(?:[\(\uFF08]\s*)?([A-D])\s*(?:[\)\uFF09]\s*|[.\uFF0E\u3001:\uFF1A\]]\s*)\S.+$"
        )
        answer_pattern = re.compile(
            r"(?im)^\s*(?:answer|\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u6b63\u786e\u7b54\u6848|\u7b54\u6848(?!\u89e3\u6790))\s*(?:is|\u662f|\u4e3a|\u9009)?\s*[:\uFF1A=]?\s*(\S(?:.*\S)?)\s*$"
        )
        explanation_pattern = re.compile(
            r"(?im)^\s*(?:explanation|\u7b54\u6848\u89e3\u6790|\u89e3\u6790)\s*[:\uFF1A=]?\s*(.+\S)\s*$"
        )
        answers = answer_pattern.findall(block)
        explanations = explanation_pattern.findall(block)
        if len(answers) != 1:
            return "the question must contain exactly one answer line"
        if len(explanations) != 1:
            return "the question must contain exactly one explanation line"

        option_ids = option_pattern.findall(block)
        if option_ids:
            if option_ids != ["A", "B", "C", "D"]:
                return "multiple-choice options must be exactly A through D"
            if answers[0].strip().upper() not in {"A", "B", "C", "D"}:
                return "the answer must match one of the A-D options"
        return None

    async def _repair_quiz_question(
        self,
        question_number: int,
        source_block: str,
        reason: str,
        kb_context: str,
        retained_stems: list[str],
    ) -> str | None:
        """Regenerate one invalid question while preserving all valid questions."""
        prompt = f"""Return JSON with a single `content` field containing one replacement
quiz question only. All learner-facing text must be Simplified Chinese, except
for unavoidable product names, alarm codes, or technical abbreviations.
The stem must state a concrete condition or task and clearly ask what the
learner should decide or do. Never use a topic label such as
`\u62a5\u8b66\u4ee3\u7801\u8bc6\u522b\uff08\u57fa\u7840\u9009\u62e9\u9898\uff09` as a stem.
Preserve the original question type when possible. If the original used A-D
options, use this multiple-choice format:

\u7b2c {question_number} \u9898\uff1a<complete standalone question>
A. <option>
B. <option>
C. <option>
D. <option>
\u7b54\u6848\uff1a<A, B, C, or D>
\u89e3\u6790\uff1a<why the answer is correct>

If the original is a short-answer question, use this format instead and do not
include A-D options:

\u7b2c {question_number} \u9898\uff1a<complete standalone question>
\u7b54\u6848\uff1a<expected short answer>
\u89e3\u6790\uff1a<why the answer is correct>

Ground the replacement in this knowledge context. Do not repeat any retained
question stems: {retained_stems}

Original invalid question:
{source_block or "<missing question>"}

Automatic validation failure: {reason}

Knowledge context:
{kb_context[:6000]}
"""
        repaired = await self.call_llm_json(prompt)
        if not isinstance(repaired, dict):
            return None
        for candidate in self._quiz_question_blocks(str(repaired.get("content", ""))):
            if self._quiz_block_failure(candidate) is None:
                return candidate
        return None

    async def _repair_quiz_questions(self, result: dict, kb_context: str) -> dict:
        """Repair failed quiz items independently without rewriting valid ones."""
        candidate = dict(result) if isinstance(result, dict) else {"content": ""}
        blocks = self._quiz_question_blocks(str(candidate.get("content", "")))

        # Bound retries when the model is unavailable, but retry every failed
        # item before the explicit review fallback is returned to the UI.
        for _ in range(5):
            target_count = max(5, len(blocks))
            repaired_blocks: list[str] = []
            retained_stems: list[str] = []
            retained_keys: set[str] = set()

            for index in range(target_count):
                source_block = blocks[index] if index < len(blocks) else ""
                stem = self._quiz_block_stem(source_block)
                stem_key = re.sub(r"\s+", "", stem).lower()
                failure = self._quiz_block_failure(source_block)
                if failure is None and stem_key in retained_keys:
                    failure = "the question stem duplicates a retained question"

                if failure is None:
                    repaired_blocks.append(source_block)
                    retained_stems.append(stem)
                    retained_keys.add(stem_key)
                    continue

                replacement = await self._repair_quiz_question(
                    index + 1,
                    source_block,
                    failure or "missing question",
                    kb_context,
                    retained_stems,
                )
                replacement_stem = self._quiz_block_stem(replacement or "")
                replacement_key = re.sub(r"\s+", "", replacement_stem).lower()
                if replacement and replacement_key and replacement_key not in retained_keys:
                    repaired_blocks.append(replacement)
                    retained_stems.append(replacement_stem)
                    retained_keys.add(replacement_key)
                # Do not put a failed item back into the quiz. The next pass
                # will create a fresh replacement while retaining valid items.

            candidate["content"] = "\n\n".join(repaired_blocks)
            if self._quiz_contract_failure(candidate) is None:
                return candidate
            blocks = self._quiz_question_blocks(str(candidate.get("content", "")))

        return candidate

    @staticmethod
    def _has_legacy_quiz_key(result: dict | None) -> bool:
        """Return whether every recognizable quiz question includes its key."""
        if not isinstance(result, dict):
            return False
        content = str(result.get("content", ""))
        question_count = len(
            re.findall(
                r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*题)",
                content,
            )
        )
        answer_count = len(
            re.findall(r"(?im)^\s*(?:answer|标准答案|参考答案|正确答案|答案)\s*[:：]", content)
        )
        explanation_count = len(
            re.findall(r"(?im)^\s*(?:explanation|答案解析|解析)\s*[:：]", content)
        )
        return (
            question_count >= 5
            and answer_count >= question_count
            and explanation_count >= question_count
        )

    @staticmethod
    def _has_complete_quiz_key(result: dict | None) -> bool:
        """Require each generated quiz block to be a usable, self-contained item."""
        return GenerationAgent._quiz_contract_failure(result) is None

    @staticmethod
    def _quiz_contract_failure(result: dict | None) -> str | None:
        """Return a user-facing reason when a quiz cannot be safely scored."""
        if not isinstance(result, dict):
            return "生成结果不是有效的结构化内容"

        content = str(result.get("content", ""))
        if not content.strip():
            return "\u9898\u76ee\u5185\u5bb9\u4e3a\u7a7a"
        question_pattern = re.compile(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:question\s*\d+|q\s*\d+|\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898|\d+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?\s*(?P<stem>.+)$"
        )
        matches = list(question_pattern.finditer(content))
        if len(matches) < 5:
            return f"题目数量不足：仅生成 {len(matches)} 题"

        option_pattern = re.compile(
            r"(?im)^\s*(?:[-*]\s*)?(?:[\(\uFF08]\s*)?([A-D])\s*(?:[\)\uFF09]\s*|[.\uFF0E\u3001:\uFF1A\]]\s*)\S.+$"
        )
        answer_pattern = re.compile(
            r"(?im)^\s*(?:answer|\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u6b63\u786e\u7b54\u6848|\u7b54\u6848(?!\u89e3\u6790))\s*(?:is|\u662f|\u4e3a|\u9009)?\s*[:\uFF1A=]?\s*(\S(?:.*\S)?)\s*$"
        )
        explanation_pattern = re.compile(
            r"(?im)^\s*(?:explanation|\u7b54\u6848\u89e3\u6790|\u89e3\u6790)\s*[:\uFF1A=]?\s*(.+\S)\s*$"
        )

        seen_stems: set[str] = set()
        for index, match in enumerate(matches):
            question_number = index + 1
            block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[match.start() : block_end]
            stem = match.group("stem").strip()
            normalized_stem = re.sub(r"\s+", "", stem).lower()
            if not GenerationAgent._is_clear_quiz_stem(stem):
                return f"第 {question_number} 题题干更像标题，无法确认作答任务"
            if normalized_stem in seen_stems:
                return f"\u7b2c {question_number} \u9898\u4e0e\u524d\u9762\u9898\u76ee\u91cd\u590d"
            seen_stems.add(normalized_stem)

            answers = answer_pattern.findall(block)
            explanations = explanation_pattern.findall(block)
            if not answers:
                return f"\u7b2c {question_number} \u9898\u7f3a\u5c11\u6807\u51c6\u7b54\u6848"
            if len(answers) > 1:
                return f"第 {question_number} 题包含多个标准答案"
            if not explanations:
                return f"\u7b2c {question_number} \u9898\u7f3a\u5c11\u89e3\u6790"
            if len(explanations) > 1:
                return f"\u7b2c {question_number} \u9898\u5305\u542b\u591a\u4e2a\u89e3\u6790"

            option_ids = option_pattern.findall(block)
            if option_ids:
                if option_ids != ["A", "B", "C", "D"]:
                    return f"第 {question_number} 题的选项必须完整标为 A-D"
                if answers[0].strip().upper() not in {"A", "B", "C", "D"}:
                    return f"第 {question_number} 题的标准答案未匹配选项"

        return None

    def _fmt_gaps(self, gaps: list) -> str:
        """格式化知识盲区列表为可读文本，最多展示前 5 条。

        对数值字段做 float() 保护，防止 LLM 返回字符串类型
        导致 .1f 格式化报 TypeError。
        """
        if not gaps:
            return "学习者未提供具体知识盲区，请根据学习目标生成通用的入门内容"

        lines = []
        for g in gaps[:5]:
            priority = g.get("priority", "?")
            topic = g.get("topic", "未知")
            reason = g.get("reason", "")

            # float() 类型保护：LLM JSON 中的数值可能是 int/float/str
            try:
                curr_lv = float(g.get("current_level", 0.0))
            except (ValueError, TypeError):
                curr_lv = 0.0
            try:
                target_lv = float(g.get("target_level", 1.0))
            except (ValueError, TypeError):
                target_lv = 1.0

            lines.append(
                f"- [{priority}] {topic} (当前 {curr_lv:.1f} → 目标 {target_lv:.1f}): {reason}"
            )

        return "\n".join(lines)

    @staticmethod
    def _fmt_knowledge_base(chunks: list) -> str:
        """将 RAG 检索到的知识库 chunks 格式化为 LLM prompt 中的参考资料。

        取前 6 条最相关的 chunk，去重（按 doc_title），
        每条截取前 500 字符防止 prompt 过长。
        """
        if not chunks:
            return "## 知识库参考资料\n（无可用知识库素材——禁止凭空生成内容）"

        seen_titles: set[str] = set()
        unique_chunks: list[dict] = []
        for c in chunks:
            title = c.get("doc_title", "")
            if title not in seen_titles:
                seen_titles.add(title)
                unique_chunks.append(c)
            if len(unique_chunks) >= 6:
                break

        parts = ["## 知识库参考资料（以下是系统检索到的权威文档，请严格基于这些资料生成内容）"]
        for i, c in enumerate(unique_chunks, 1):
            title = c.get("doc_title", "未知文档")
            content = c.get("content", "")
            # 截取关键部分，防止 prompt 过长
            excerpt = content[:500] + ("…" if len(content) > 500 else "")
            parts.append(f"\n### 资料 {i}：{title}\n{excerpt}")

        return "\n".join(parts)

    @staticmethod
    def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
        """大小写不敏感地判断 text 是否命中任一标记。"""
        lowered = str(text or "").lower()
        return any(str(m).lower() in lowered for m in markers)

    @staticmethod
    def _count_occurrences(text: str, marker: str) -> int:
        """大小写不敏感地统计 marker 在 text 中的非重叠出现次数。"""
        return str(text or "").lower().count(str(marker).lower())

    @staticmethod
    def _classify_risk_level(rtype: str, content: str) -> str:
        """确定性风险分级（不调 LLM；危险 ≠ 难度）。

        lecture/quiz/pitfall_guide 属理论/警示类内容恒为 theory；guide/project 按正文
        命中运动类/软件类标记分级：运动类 → high_risk，软件类 → low_risk，否则 theory。
        """
        if rtype in ("lecture", "quiz", "pitfall_guide"):
            return "theory"
        text = str(content or "")
        if GenerationAgent._contains_any(text, _HIGH_RISK_MOTION_MARKERS):
            return "high_risk"
        if GenerationAgent._contains_any(text, _LOW_RISK_SOFTWARE_MARKERS):
            return "low_risk"
        return "theory"

    @staticmethod
    def _extract_safety_warnings(content: str) -> list[str]:
        """从正文确定性提取 `> ⚠️ 安全提示：…` 引用块文本（不调 LLM）。

        保持 content 扁平字符串不变，仅在生成后按固定格式抽取为结构化字段，
        供前端渲染独立警示块；与普通步骤文本天然分离。
        """
        return [
            m.group("text").strip()
            for m in _SAFETY_WARNING_RE.finditer(str(content or ""))
            if m.group("text")
        ]

    @staticmethod
    def _strip_code_blocks(content: str) -> str:
        """剔除 ``` 围栏代码块，返回可做关键词匹配的正文（不调 LLM）。

        行内反引号 `code` 是讲解速查点（如 `MoveJ`），不剔除；仅整体剥离多行代码块，
        避免把代码示例里的指令名/报警编号误判为「正文提到该速查点」。
        """
        return re.sub(r"```.*?```", "", str(content or ""), flags=re.DOTALL)

    @staticmethod
    def _extract_instruction_links(content: str) -> list[dict]:
        """识别正文里的指令名，注入对应速查跳转链接（确定性，不调 LLM；二期-2）。

        消费 instruction_index.json（仅三品牌），对每条指令名做「词边界 + 大小写敏感」
        匹配（re.escape 防正则注入），跳过代码块；命中产 {brand,name,doc_id,doc_title}。
        按 (brand, name) 去重保留首个 doc，避免同名多篇刷屏。
        """
        text = GenerationAgent._strip_code_blocks(content)
        links: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for entry in _load_instruction_index():
            name = str(entry.get("instruction", "") or "")
            brand = str(entry.get("brand", "") or "")
            if not name or (brand, name) in seen:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text):
                seen.add((brand, name))
                links.append(
                    {
                        "brand": brand,
                        "name": name,
                        "doc_id": str(entry.get("doc_id", "") or ""),
                        "doc_title": str(entry.get("doc_title", "") or ""),
                    }
                )
        return links

    @staticmethod
    def _extract_alarm_links(content: str) -> list[dict]:
        """识别正文里的报警编号，注入对应排查跳转链接（确定性，不调 LLM；二期-2）。

        消费 alarm_index.json（仅三品牌），对每条 alarm_code 做词边界匹配，跳过代码块；
        命中产 {brand,code,doc_id,doc_title,fault_name}。按 (brand, code) 去重。
        """
        text = GenerationAgent._strip_code_blocks(content)
        links: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for entry in _load_alarm_index():
            code = str(entry.get("alarm_code", "") or "")
            brand = str(entry.get("brand", "") or "")
            if not code or (brand, code) in seen:
                continue
            if re.search(rf"\b{re.escape(code)}\b", text):
                seen.add((brand, code))
                links.append(
                    {
                        "brand": brand,
                        "code": code,
                        "doc_id": str(entry.get("doc_id", "") or ""),
                        "doc_title": str(entry.get("doc_title", "") or ""),
                        "fault_name": str(entry.get("fault_name", "") or ""),
                    }
                )
        return links

    @staticmethod
    def _derive_robot_metadata(chunks: list) -> dict:
        """从 retrieved_chunks 的 doc_id/doc_title 确定性派生品牌/控制器/机型元数据。

        纯子串匹配，词表只收录 KB 真实出现过的 token；任一取不到 → 「未标注」，
        绝不靠 LLM 杜撰具体型号（CLAUDE.md §6 防幻觉铁律）。
        """
        haystack = " ".join(
            f"{str(c.get('doc_id', '') or '')} {str(c.get('doc_title', '') or '')}"
            for c in (chunks or [])
            if isinstance(c, dict)
        ).lower()

        def _pick(token_map: tuple[tuple[str, str], ...]) -> str:
            for token, display in token_map:
                if token.lower() in haystack:
                    return display
            return "未标注"

        return {
            "brand": _pick(_BRAND_TOKEN_MAP),
            "controller_version": _pick(_CONTROLLER_TOKEN_MAP),
            "applicable_model": _pick(_MODEL_TOKEN_MAP),
        }

    @staticmethod
    def _filter_relevant_chunks(chunks: list, original_topic: str) -> list:
        """丢弃与当前学习课题无关的检索片段（确定性规则）。

        当前知识库语料以工业机器人（K1~K4）为主：若用户课题不属于机器人领域，
        命中机器人强标记的片段一律视为无关素材直接丢弃，避免把任务漂移到无关领域；
        课题本身属于机器人领域时不做过滤（保留全部片段）。
        """
        if not original_topic:
            return list(chunks or [])
        if GenerationAgent._contains_any(original_topic, _ROBOT_DRIFT_MARKERS):
            return list(chunks or [])
        kept: list[dict] = []
        for c in chunks or []:
            if not isinstance(c, dict):
                continue
            title = str(c.get("doc_title", "") or "")
            content = str(c.get("content", "") or "")
            if GenerationAgent._contains_any(f"{title} {content}", _ROBOT_DRIFT_MARKERS):
                continue
            kept.append(c)
        return kept

    @staticmethod
    def _topic_drift_failure(result: dict, original_topic: str) -> str | None:
        """生成后自检：输出大标题 / 核心知识点是否与原始学习课题对齐。

        仅当可确定性地证明「明显跑偏」才返回原因——课题不属于机器人领域，
        而输出标题 / 知识点却命中机器人强标记；其余情况返回 None（不做臆断），
        交由下游审核 Agent 处理内容层面的问题。
        """
        if not isinstance(result, dict) or not str(original_topic or "").strip():
            return None
        # 课题本身就在机器人领域 → 输出含机器人词汇不构成漂移
        if GenerationAgent._contains_any(original_topic, _ROBOT_DRIFT_MARKERS):
            return None
        title = str(result.get("title", "") or "")
        takeaways = " ".join(str(t) for t in result.get("key_takeaways", []) or [] if t)
        head = f"{title} {takeaways}"
        for marker in _ROBOT_DRIFT_MARKERS:
            if str(marker).lower() in head.lower():
                return (
                    f"生成内容漂移到工业机器人领域（标题/知识点含「{marker}」，"
                    f"与原课题「{original_topic[:40]}」不符）"
                )
        return None

    @staticmethod
    def _topic_reinforcement(original_topic: str, drift_reason: str) -> str:
        """主题漂移重试时追加的强约束文本。"""
        return f"""

## 主题锁定纠正（上次生成被判定跑偏，必须重做）
上次生成被判定为主题漂移：{drift_reason}
请严格围绕原始学习课题「{original_topic}」重新生成，标题与核心知识点中严禁出现
机器人、库卡（KUKA）、机器视觉、示教器等与课题无关的领域词汇。
若上方知识库参考资料与课题无关，宁可输出空内容也不得复用其他课题的模板。"""

    @staticmethod
    def _brand_confusion_failures(head: str) -> list[str]:
        """品牌术语双向词表校验（确定性，不调 LLM；二期-1）。

        规则：当内容显式声明了「恰好一个」品牌（FANUC/KUKA/ABB 名称），却命中
        其他品牌的专属术语（来自 data/brand-lexicon.json）→ 判定品牌混淆，触发重生成。
        - 多品牌（对比类内容，len(declared) > 1）或零品牌（由品牌锚定校验兜底）不判定混淆；
        - 「通用原理」豁免由调用方（_structure_validation_failure）处理，本函数不感知。
        每个「其他品牌」最多报一条，避免刷屏。
        """
        declared = {
            brand
            for brand, names in _BRAND_NAME_MARKERS.items()
            if GenerationAgent._contains_any(head, names)
        }
        if len(declared) != 1:
            return []
        declared_brand = next(iter(declared))
        failures: list[str] = []
        for brand, terms in _load_brand_lexicon().items():
            if brand == declared_brand:
                continue
            for term in terms:
                if GenerationAgent._contains_any(head, (term,)):
                    failures.append(
                        f"品牌混淆：声明「{declared_brand}」但出现「{brand}」专属术语「{term}」"
                    )
                    break
        return failures

    @staticmethod
    def _normalize_brand(brand: object) -> str:
        """归一化用户指定品牌为 {FANUC, KUKA, ABB} 之一；非三品牌 → 空串（不约束）。"""
        value = str(brand or "").strip().upper()
        if value in _THREE_BRANDS:
            return value
        # 兼容中文别名（发那科 / 库卡）
        for canonical, names in _BRAND_NAME_MARKERS.items():
            if value and value in names:
                return canonical
        return ""

    @staticmethod
    def _brand_constraint(brand: str) -> str:
        """品牌强约束 prompt 块（brand 指定时注入，所有资源类型生效）。"""
        text = _BRAND_CONSTRAINT_TEXT.get(brand, "")
        if not text:
            return ""
        return f"\n\n## 目标品牌强约束（用户指定 {brand}，必须遵守）\n{text}"

    @staticmethod
    def _brand_reinforcement(brand: str, reasons: list[str]) -> str:
        """品牌混用重试时追加的强约束文本。"""
        reason_text = _reason_text(reasons)
        return (
            "\n\n## 品牌锁定纠正（上次生成被判定品牌混用，必须重做）\n"
            f"上次生成被判定品牌混用：{reason_text}\n"
            f"请严格围绕 {brand} 品牌重新生成，题目与解析中严禁出现其他品牌"
            f"（FANUC/KUKA/ABB 中除 {brand} 外）的专属指令、按键、控制器、示教器术语。"
        )

    @staticmethod
    def _structure_reinforcement(failures: list[str]) -> str:
        """结构校验失败重试时追加的结构修正指令（只补结构/格式，不指定具体内容）。

        失败项本身即命名了缺失的章节（如「high_risk 实操缺少运动步骤安全提示」），
        这里只要求「补这些章节」，并强调补全内容必须基于知识库、无依据处标注
        「以官方手册为准」，严禁编造具体安全操作步骤或参数。
        """
        reason_text = _reason_text(failures)
        return (
            "\n\n## 结构修正要求（上次生成被结构校验拒绝，必须补全，只补结构不编内容）\n"
            f"上次生成因以下结构问题被拒绝：{reason_text}\n"
            "请针对上述每一项缺失补全对应的章节/格式要求。补全内容必须严格基于上方知识库参考资料；"
            "知识库未覆盖的具体操作参数、菜单路径、报警代码、安全规范数值，须标注「以官方手册为准」，"
            "严禁编造。\n"
            "尤其注意：安全提示章节只补「章节框架与确认项清单」，"
            "若知识库没有对应的安全规范原文，不得凭空杜撰具体安全操作步骤或参数。"
        )

    @staticmethod
    def _failure_feedback_instruction(feedback: object, rtype: str) -> str:
        """前端「重新生成」传入的上次失败反馈 → 修正指令（只补结构/格式，不指定内容）。

        仅当 feedback 的 resource_type 与当前 rtype 匹配时注入；其余类型不受影响。
        反馈的 detail 已含具体失败原因（如「结构校验未通过：high_risk 实操缺少运动步骤安全提示」），
        这里把它作为「上次被拒绝的原因」原样回传，要求按结构修正重做，而非让 LLM 自由补内容。
        """
        if not isinstance(feedback, dict):
            return ""
        fb_rtype = str(feedback.get("resource_type", "") or "").strip()
        if fb_rtype and fb_rtype != rtype:
            return ""
        detail = _reason_text(feedback.get("detail"))
        error = str(feedback.get("error", "") or "").strip()
        reason = detail or error
        if not reason:
            return ""
        return (
            "\n\n## 上次失败修正要求（上次生成被拒绝，必须按结构修正后重做，只补结构不编内容）\n"
            f"上次生成被拒绝的原因：{reason}\n"
            "请针对上述原因补全对应的章节/格式要求，不要自由发挥改写主题。补全内容必须严格基于"
            "上方知识库参考资料；知识库未覆盖的具体操作参数、菜单路径、报警代码、安全规范数值，"
            "须标注「以官方手册为准」，严禁编造。"
        )

    @staticmethod
    def _quiz_brand_mix_failure(content: str, brand: str) -> list[str]:
        """quiz 品牌强校验（用户指定品牌时）：检测是否混入其他品牌专属术语。

        判定源 = 现有 brand-lexicon.json 专属词（大小写不敏感）+ 独立指令级词表
        _INSTRUCTION_BRAND_CN_TERMS（中文语境，大小写不敏感）与
        _INSTRUCTION_BRAND_ASCII_TERMS（纯 ASCII，大小写敏感 + 词边界）。
        返回「指定 X 但出现 Y 专属术语 Z」列表；空列表表示通过。
        """
        canonical = GenerationAgent._normalize_brand(brand)
        if not canonical:
            return []
        text = str(content or "")
        failures: list[str] = []
        lexicon = _load_brand_lexicon()
        for other in sorted(_THREE_BRANDS - {canonical}):
            # 1) 现有 lexicon 专属词（大小写不敏感）
            for term in lexicon.get(other, []):
                if GenerationAgent._contains_any(text, (term,)):
                    failures.append(f"指定 {canonical} 但出现 {other} 专属术语「{term}」")
                    break
            # 2) 指令级中文语境词（大小写不敏感）
            for term in _INSTRUCTION_BRAND_CN_TERMS.get(other, ()):
                if GenerationAgent._contains_any(text, (term,)):
                    failures.append(f"指定 {canonical} 但出现 {other} 专属指令概念「{term}」")
                    break
        # 3) 指令级纯 ASCII 词（大小写敏感 + 词边界）
        for term in _ASCII_INSTRUCTION_TERMS_RE.findall(text):
            for other in sorted(_THREE_BRANDS - {canonical}):
                if term in _INSTRUCTION_BRAND_ASCII_TERMS.get(other, ()):
                    failures.append(f"指定 {canonical} 但出现 {other} 专属指令「{term}」")
                    break
        # 4) FANUC 的 J/L 运动指令（词边界 + 中文「指令」后缀，排除 MoveJ/MoveL）
        if canonical != "FANUC":
            jl_match = _FANUC_JL_INSTRUCTION_RE.search(text)
            if jl_match:
                failures.append(
                    f"指定 {canonical} 但出现 FANUC 专属 J/L 指令「{jl_match.group(0).strip()}」"
                )
        return failures

    @staticmethod
    def _is_recoverable_structure_failure(failure: str) -> bool:
        """结构「缺章节/缺安全提示」类失败判定（重试仍缺失时降级保留，不判整篇丢弃）。

        与品牌锚定/品牌混淆/入门超纲等致命失败区分：仅命中
        ``_RECOVERABLE_STRUCTURE_FAILURE_MARKERS`` 之一的失败视为可恢复。
        """
        return any(m in str(failure) for m in _RECOVERABLE_STRUCTURE_FAILURE_MARKERS)

    @staticmethod
    def _structure_validation_failure(result: dict, rtype: str, difficulty: str) -> list[str]:
        """A档确定性结构后置校验（仅机器人领域课题调用，不调 LLM）。

        只做结构性/存在性判定（品牌声明、安全章节、排错模块、入门超纲、
        quiz 安全占比），不做内容正确性审查（正确性交下游 Agent3）。
        返回失败原因列表；空列表表示通过。
        """
        failures: list[str] = []
        if not isinstance(result, dict):
            return ["生成结果不是结构化 dict"]
        content = str(result.get("content", "") or "")
        title = str(result.get("title", "") or "")
        head = f"{title}\n{content}"

        # 品牌锚定：讲义/指南/项目实战/避坑指南必须声明品牌（FANUC/KUKA/ABB）或标注「通用原理」
        if rtype in ("lecture", "guide", "project", "pitfall_guide"):
            has_brand = GenerationAgent._contains_any(head, _ROBOT_BRAND_MARKERS)
            has_generic = GenerationAgent._contains_any(head, _GENERIC_BRAND_MARKERS)
            if not (has_brand or has_generic):
                failures.append("未声明品牌（FANUC/KUKA/ABB）或未标注「通用原理」")
            # 品牌混淆：单一品牌声明 + 其他品牌专属术语 → 触发重生成（「通用原理」豁免）
            if not has_generic:
                failures.extend(GenerationAgent._brand_confusion_failures(head))

        # 高危实操安全校验：high_risk 的 guide/project 须含「安全操作确认清单」+ 运动步骤安全提示
        if GenerationAgent._classify_risk_level(rtype, content) == "high_risk" and rtype in (
            "guide",
            "project",
        ):
            if not _CHECKLIST_HEADING_RE.search(content):
                failures.append("high_risk 实操缺少「安全操作确认清单」章节")
            if not _SAFETY_WARNING_RE.search(content):
                failures.append("high_risk 实操缺少运动步骤安全提示（> ⚠️ 安全提示）")

        # 安全红线：guide 必须前置独立「安全」标题章节
        if rtype == "guide" and not _GUIDE_SAFETY_HEADING_RE.search(content):
            failures.append("guide 缺少独立「安全」标题章节")

        # 实操真实性：guide 必须含「常见异常与排错」对照模块
        if rtype == "guide" and not _GUIDE_TROUBLESHOOT_HEADING_RE.search(content):
            failures.append("guide 缺少「常见异常与排错」对照模块")

        # 难度层级：入门级允许轻度提及高级主题（仅日志标记），禁止大段展开讲解（判超纲丢弃）
        if difficulty == "beginner":
            for marker in _BEGINNER_ADVANCED_MARKERS:
                count = GenerationAgent._count_occurrences(head, marker)
                if count >= _BEGINNER_ADVANCED_EXPANSION_THRESHOLD:
                    failures.append(f"入门级内容大段展开超纲主题「{marker}」（出现 {count} 处）")
                    break
                if count > 0:
                    logger.warning(
                        f"入门级内容轻度提及超纲主题「{marker}」（{count} 处），允许保留仅标记"
                    )

        # quiz 安全规范类题目占比 ≥20%
        if rtype == "quiz":
            ratio_failure = GenerationAgent._quiz_safety_ratio_failure(content)
            if ratio_failure:
                failures.append(ratio_failure)

        # 避坑指南必备要素：须含「常见误区」+「原因」+「规避/正确做法」三类内容
        if rtype == "pitfall_guide":
            if not GenerationAgent._contains_any(content, _PITFALL_MARKERS):
                failures.append("pitfall_guide 缺少「常见误区」内容")
            if not GenerationAgent._contains_any(content, _CAUSE_MARKERS):
                failures.append("pitfall_guide 缺少「原因」内容")
            if not GenerationAgent._contains_any(content, _AVOIDANCE_MARKERS):
                failures.append("pitfall_guide 缺少「规避/正确做法」内容")

        return failures

    @staticmethod
    def _quiz_safety_ratio_failure(content: str) -> str | None:
        """quiz 安全规范类题目占比 ≥20% 的确定性校验（不调 LLM）。

        题目数量不足由 _quiz_contract_failure 负责，此处只统计安全题占比。
        """
        blocks = GenerationAgent._quiz_question_blocks(content)
        if len(blocks) < 5:
            return None
        safety_count = sum(
            1 for b in blocks if GenerationAgent._contains_any(b, _QUIZ_SAFETY_MARKERS)
        )
        if safety_count / len(blocks) < 0.20:
            return f"安全规范类题目占比不足：{safety_count}/{len(blocks)} < 20%"
        return None

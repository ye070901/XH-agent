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
from pathlib import Path

from .base import BaseAgent

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

## 严格对齐知识库（最高优先级，凌驾于以上所有生成规则）
- 你只能使用提示中给出的"知识库参考资料"原文作答，禁止调用自身通用常识、行业经验
  或外部知识进行补充、解释、延伸、润色、联想。
- 生成模式为**原文摘抄式整合**：关键知识点必须以知识库原文句子为素材，允许合并、调整
  语序、做必要的衔接过渡，但不得新增原文中不存在的事实、定义、参数、型号、步骤、报警码。
- 若"知识库参考资料"未覆盖某个知识点（无对应原文），该位置必须直接回复"暂无相关内容"，
  严禁编造、推测，严禁用"一般地""通常""可能""建议"等措辞兜底。
- 代码示例、命令行、参数编号、报警码、复位步骤等硬性事实必须逐字来源于知识库原文。

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


#: 入门级超纲标记：beginner 内容命中即判超纲（视觉/离线/外部轴等高级主题）
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
    （lecture / guide / quiz）生成一份个性化学习资源。

    资源数量上限为 3，防止单次请求过度消耗 token。
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
    }

    # 资源数量上限，防止 token 过度消耗
    MAX_RESOURCES = 3

    # 主题漂移时的最大重试次数（不含首次生成）
    MAX_TOPIC_RETRIES = 2

    def __init__(self):
        super().__init__(
            name="知识生成Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
        )

    async def process(self, state: dict) -> dict:
        """生成个性化学习资源。

        对每种请求的资源类型分别调用 LLM 生成一份资源。
        单个资源生成失败时记录错误但不阻断其他资源的生成（部分成功）。
        """
        diagnosis = state.get("diagnosis_result", {})
        learner_data = state.get("learner_data", {})
        resource_types = state.get("resource_types", ["lecture", "guide", "quiz"])
        retrieved_chunks = state.get("retrieved_chunks", [])

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
                    errors.append({"resource_type": rtype, "error": "json_parse_failed"})
                    continue
                # 主题漂移自检兜底：重试仍无法对齐原始课题 → 丢弃，绝不把跑偏内容返回前端
                drift_error = result.get("_topic_drift_error")
                if drift_error:
                    self.log(f"⚠️ {rtype} 类型资源主题漂移，丢弃: {drift_error}")
                    errors.append(
                        {"resource_type": rtype, "error": "topic_drift", "detail": drift_error}
                    )
                    continue
                # A档结构后置校验兜底：机器人领域资源未通过确定性结构校验 → 丢弃
                structure_error = result.get("_structure_validation_error")
                if structure_error:
                    self.log(f"⚠️ {rtype} 类型资源结构校验未通过，丢弃: {structure_error}")
                    errors.append(
                        {
                            "resource_type": rtype,
                            "error": "structure_validation",
                            "detail": structure_error,
                        }
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
                        {
                            "resource_type": rtype,
                            "error": "invalid_quiz_contract",
                            "detail": quiz_validation_error,
                        }
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
            except Exception as e:
                # 单个资源生成失败不阻断其他资源
                self.log(f"⚠️ {rtype} 类型资源生成失败: {e}")
                errors.append({"resource_type": rtype, "error": str(e)})

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
            learner_data:     学习者原始画像（用于纯规则推导 profile_tag，可选）

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
6. **结构要求**（后置校验会确定性检查，不满足将被丢弃）：
   - guide 必须含独立「安全」章节 + 「常见异常与排错」对照模块；
   - lecture/guide/project/pitfall_guide 必须声明品牌（FANUC/KUKA/ABB）或标注「通用原理」；
   - quiz 安全规范类题目占比不低于 20%；
   - pitfall_guide 必须含「常见误区」与「规避/正确做法」两类内容。
7. **高危实操安全清单**：涉及示教/点动/运行程序/IO调试等运动操作的 guide/project，
   正文开头须生成「安全操作确认清单」章节（含：安全门状态确认 / 急停按钮位置确认 /
   使能键使用规范 / 工作区间无人员确认 / 减速模式开启要求）；
   每个运动类操作步骤前，须输出独立引用块 `> ⚠️ 安全提示：…`，不得与普通步骤文本合并。
8. **事实准确（铁律）**：严禁编造菜单路径、报警代码、参数值、操作顺序；
   报警编号/指令名必须来自知识库或速查索引，无法确认时标注「以官方手册为准」，不得杜撰。"""

        prompt = f"""## 结构化画像参数（权威，禁止改写）
{json.dumps(profile_params, ensure_ascii=False)}

## 学习者画像
- 学习目标总结：{learning_goal}
- 知识盲区（按优先级）：{self._fmt_gaps(gaps)}

## 原始学习课题（主题锁定·最高优先级，严禁偏离）
{original_topic}

{kb_section}
{robot_req_block}

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

        # ── ④ 输出前句子级溯源校验（严格对齐知识库）──
        # 生成链路末尾逐句与检索到的知识库原文比对，复用覆盖率阈值 0.5
        # （多 chunk 合并证据，与 audit.py _RULE_SUPPORT_THRESHOLD 对齐）。
        # 无原文支撑的句子自动剔除；剔除过甚时触发一次重生成（携带剔除反馈）。
        if isinstance(result, dict) and result.get("content"):
            content = str(result.get("content", ""))
            cleaned, removed, kept_ratio = self._sentence_level_trace_check(
                content, relevant_chunks or []
            )
            trace = {
                "sentences_total": self._count_sentences(content),
                "sentences_removed": len(removed),
                "kept_ratio": round(kept_ratio, 4),
                "removed_sentences": removed,
            }
            if removed:
                self.log(
                    f"句子级溯源: 剔除 {len(removed)} 个无原文支撑句子 (保留率 {kept_ratio:.2f})"
                )
                # 剔除过甚（内容大量塌缩）→ 触发一次重生成，携带被剔除句子反馈
                if kept_ratio < 0.6 and rtype != "quiz":
                    regen = await self._regenerate_with_trace_feedback(prompt, removed, rtype)
                    if isinstance(regen, dict) and regen.get("content"):
                        cleaned2, removed2, kept_ratio2 = self._sentence_level_trace_check(
                            str(regen.get("content", "")), relevant_chunks or []
                        )
                        if kept_ratio2 >= kept_ratio and len(removed2) <= len(removed):
                            result = regen
                            trace.update(
                                {
                                    "regenerated": True,
                                    "sentences_removed_after_regen": len(removed2),
                                    "kept_ratio_after_regen": round(kept_ratio2, 4),
                                    "removed_sentences": removed2,
                                }
                            )
                            cleaned, removed, kept_ratio = cleaned2, removed2, kept_ratio2
                result["content"] = cleaned or content
                result["_trace"] = trace
                if not cleaned.strip():
                    # 全部句子被剔除：保留空内容，交由下游审核拒绝
                    self.log("句子级溯源: 内容全部被剔除，置空交由审核拦截")
        elif isinstance(result, dict):
            result["_trace"] = {"sentences_total": 0, "sentences_removed": 0, "kept_ratio": 1.0}

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
        if is_robot_topic and "_quiz_validation_error" not in result:
            structure_failures = self._structure_validation_failure(result, rtype, difficulty)
            if structure_failures:
                self.log(f"❌ {rtype} 结构校验未通过，丢弃: {structure_failures}")
                return {"_structure_validation_error": structure_failures}

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

        # 难度层级：入门级不得出现高级主题
        if difficulty == "beginner":
            for marker in _BEGINNER_ADVANCED_MARKERS:
                if GenerationAgent._contains_any(head, (marker,)):
                    failures.append(f"入门级内容出现超纲主题「{marker}」")
                    break

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

    # ═══════════════════════════════════════════════════════════
    # 句子级溯源校验（严格对齐知识库 · 改造④）
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_tokens(text: str) -> set[str]:
        """提取比对关键词：英文单词 + 中文双字 bigram（与 audit.py 对齐）。"""
        normalized = re.sub(r"\s+", "", str(text).lower())
        tokens: set[str] = set()
        tokens.update(re.findall(r"[a-z0-9]{2,}", normalized))
        cjk = re.sub(r"[^一-龥]", "", normalized)
        for i in range(len(cjk) - 1):
            tokens.add(cjk[i : i + 2])
        return {t for t in tokens if len(t) >= 2}

    @staticmethod
    def _is_structure_line(line: str) -> bool:
        """判断是否为 Markdown 结构行 / quiz 结构行（直接保留，不参与句子溯源）。"""
        s = line.strip()
        if not s:
            return True
        # Markdown 标题 / 列表 / 引用 / 表格 / 代码围栏 / 分割线
        if s.startswith(("#", "-", "*", ">", "|", "```", "~~~", "---", "===")):
            return True
        # 有序列表项
        if re.match(r"^\d+\s*[.、)]\s", s):
            return True
        # quiz 选项行（A-D）
        if re.match(r"^[\(\uff08]?[A-D][\)\uff09]\s*", s):
            return True
        # quiz 答案 / 解析 / 题号行
        if re.match(
            r"^(?:\u7b54\u6848|\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u89e3\u6790"
            r"|answer|explanation)\s*[:\uff1a=]?\s*\S",
            s,
            re.IGNORECASE,
        ):
            return True
        if re.match(r"^\u7b2c\s*[0-9\u4e00-\u5341]+\s*\u9898", s):
            return True
        return False

    def _sentence_level_trace_check(self, content: str, chunks: list) -> tuple[str, list, float]:
        """句子级原文匹配：逐句与检索到的知识库原文合并比对。

        覆盖率判定与 audit.py 完全对齐：
          - 关键词提取：英文单词 + 中文双字 bigram
          - 覆盖率阈值 0.5（多 chunk 合并证据）
        无原文支撑（覆盖率 < 0.5）的正文句子剔除；Markdown / quiz 结构行保留。

        Returns:
            (清洗后 content, 被剔除句子列表, 保留率)
        """
        if not content or not chunks:
            return content, [], 1.0
        merged_norm = re.sub(
            r"\s+", "", "\n".join(str(c.get("content", "")) for c in chunks)
        ).lower()
        if not merged_norm:
            return content, [], 1.0

        kept: list[str] = []
        removed: list[str] = []
        for raw_line in content.split("\n"):
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                kept.append(line)
                continue
            if self._is_structure_line(line):
                kept.append(line)
                continue
            # 长段落按句号等标点拆成句子逐句判定
            sentences = re.split(r"(?<=[\u3002\uff01\uff1f!?;；])", stripped)
            for sentence in sentences:
                s = sentence.strip()
                if not s:
                    continue
                tokens = self._extract_tokens(s)
                if not tokens:
                    kept.append(s)
                    continue
                hits = sum(1 for t in tokens if t in merged_norm)
                ratio = hits / len(tokens)
                if ratio >= 0.5:
                    kept.append(s)
                else:
                    removed.append(s)
        cleaned = "\n".join(kept).strip()
        total_checked = len(removed) + sum(
            1
            for raw_line in content.split("\n")
            if raw_line.strip() and not self._is_structure_line(raw_line)
        )
        kept_ratio = (total_checked - len(removed)) / total_checked if total_checked else 1.0
        return cleaned, removed, kept_ratio

    @staticmethod
    def _count_sentences(content: str) -> int:
        if not content:
            return 0
        return len(
            [
                s
                for raw_line in content.split("\n")
                for s in re.split(r"(?<=[\u3002\uff01\uff1f!?;；])", raw_line)
                if s.strip()
            ]
        )

    async def _regenerate_with_trace_feedback(
        self, original_prompt: str, removed: list[str], rtype: str
    ) -> dict:
        """溯源剔除过甚时触发重生成：携带被剔除句子作为约束反馈。"""
        feedback = "\n".join(f"- {s}" for s in removed[:10])
        tail = f"""

## 溯源修正要求（上轮生成被拦截）
上轮生成内容中有 {len(removed)} 个句子在知识库原文中找不到支撑，已被系统剔除：
{feedback}
请仅使用知识库参考资料原文内容重写，删除所有无原文支撑的句子；
无法覆盖的知识点位置直接回复"暂无相关内容"，不得用常识补充。
"""
        if rtype == "quiz":
            tail += "保持题号、A-D选项、答案、解析结构完整（每题题干与答案必须基于知识库原文）。\n"
        return await self.call_llm_json(original_prompt + tail)

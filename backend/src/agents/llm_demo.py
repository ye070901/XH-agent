"""本地演示 LLM — 独立工作目录运行时的兜底实现。

仅用于本地演示与单元测试，**不发起任何真实网络请求**。
按 system_prompt / user_message 关键词返回 schema 完备的模拟数据，
行为对齐 backend/src/llm/client.py 的演示模式（LLM_API_KEY 为空时降级）。

对外接口与真实 LLM 保持一致，供 BaseAgent.call_llm / call_llm_json 调用：
  - ``await llm.call(system_prompt, user_message, ...) -> str``
  - ``await llm.call_json(system_prompt, user_message, ...) -> dict``

领域已对齐工业机器人故障诊断（FANUC/KUKA/ABB），不再出现旧标准
（LangGraph / Google / LangChain / LLM 应用开发）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger


def _parse_learner(user_message: str) -> dict:
    """从学情诊断 prompt 中解析学习者字段（规则，与 client.py 演示模式一致）。"""

    def grab(pattern: str, default: str = "") -> str:
        m = re.search(pattern, user_message)
        return m.group(1).strip() if m else default

    total, max_score = 0, 0
    m = re.search(r"(\d+)\s*/\s*(\d+)", user_message)
    if m:
        total, max_score = int(m.group(1)), int(m.group(2))

    try:
        work_years = float(grab(r"年限[：:][ \t]*([\d.]+)", "0"))
    except ValueError:
        work_years = 0.0

    return {
        "education_level": grab(r"学历[：:][ \t]*(.+)"),
        "major": grab(r"专业[：:][ \t]*(.+)"),
        "work_years": work_years,
        "positions": grab(r"岗位[：:][ \t]*(.+)"),
        "skills_used": grab(r"使用技能[：:][ \t]*(.+)"),
        "learning_goal": grab(r"学习目标[ \t]*\n[ \t]*(.+)"),
        "total_score": total,
        "max_score": max_score,
    }


def _infer_difficulty(info: dict) -> str:
    """按前置测试得分率映射难度（对齐 learner_profiles.json 10 画像真值）。"""
    total, max_score = info["total_score"], info["max_score"]
    if max_score > 0:
        ratio = total / max_score
        if ratio >= 0.7:
            return "advanced"
        if ratio >= 0.25:
            return "intermediate"
        return "beginner"
    if info["work_years"] >= 8:
        return "advanced"
    if info["work_years"] >= 2:
        return "intermediate"
    return "beginner"


def _infer_style(info: dict, difficulty: str) -> str:
    """按背景信号映射学习风格（规则，与 client.py 演示模式一致）。"""
    skills = info["skills_used"]
    positions = info["positions"]
    if not skills:
        return "visual"
    if difficulty == "advanced" and any(k in positions for k in ("专家", "负责人", "方案", "总监")):
        return "project_based"
    if any(k in positions for k in ("操作工", "调试", "示教", "上下料")):
        return "practice_first"
    return "theory_first"


def _demo_diagnosis(user_message: str) -> dict[str, Any]:
    """学情诊断模拟输出（机器人领域，解析学习者画像推导难度/风格）。"""
    info = _parse_learner(user_message)
    difficulty = _infer_difficulty(info)
    learning_style = _infer_style(info, difficulty)

    mastery = {"beginner": 0.25, "intermediate": 0.55, "advanced": 0.85}[difficulty]
    km_topics = [
        "工业机器人基础概念",
        "机器人坐标系与姿态",
        "示教器操作与基础编程",
        "运动指令（PTP/LIN/CIRC）",
        "离线仿真（RobotStudio/ROS2）",
        "安全回路与急停链路",
        "故障代码诊断（SRVO-068等）",
    ]
    knowledge_map = {
        topic: {
            "level": round(max(0.05, min(0.95, mastery + 0.06 * (i % 3) - 0.06)), 2),
            "confidence": 0.8,
            "evidence": f"结合「{info['major'] or '工业机器人'}」背景与前置测试综合评估",
        }
        for i, topic in enumerate(km_topics)
    }

    gaps_by_difficulty = {
        "beginner": [
            ("机器人坐标系与姿态", "critical", "零基础，坐标系是示教编程与轨迹控制的前提"),
            ("示教器基础操作", "critical", "安全操作与编程的起点"),
            ("安全回路与急停链路", "high", "工业现场安全第一，需先建立风险意识"),
            ("运动指令入门（PTP/LIN）", "high", "实现基础轨迹控制"),
            ("离线仿真入门", "medium", "用 RobotStudio/ROS2 降低试错成本"),
        ],
        "intermediate": [
            ("离线仿真与程序调试", "critical", "有基础但缺仿真与现场调试经验"),
            ("故障代码诊断方法", "high", "从会操作到能定位故障的关键一步"),
            ("多品牌坐标与运动指令差异", "high", "跨 FANUC/KUKA/ABB 的迁移能力"),
            ("安全回路系统理解", "medium", "从执行安全步骤到理解安全链路原理"),
            ("程序结构与优化", "medium", "从会写简单程序到结构化管理"),
        ],
        "advanced": [
            ("跨品牌离线仿真与方案设计", "critical", "多品牌场景下的产线方案设计能力"),
            ("疑难故障系统化定位", "critical", "复杂故障的方法论沉淀"),
            ("安全合规与风险评估", "high", "产线级安全方案与风险评估"),
            ("程序架构与团队协作规范", "medium", "大规模程序的架构与维护"),
            ("行业最佳实践", "medium", "沉淀可复用的方法论"),
        ],
    }
    skill_gaps = [
        {
            "topic": topic,
            "current_level": round(max(0.05, mastery - 0.3), 2),
            "target_level": 0.8 if priority == "critical" else 0.7,
            "priority": priority,
            "reason": reason,
        }
        for topic, priority, reason in gaps_by_difficulty[difficulty]
    ]

    style_desc = {
        "visual": "偏好图像与示意图演示，适合零基础建立直观认识",
        "theory_first": "先建立概念框架再进入实操",
        "practice_first": "以实操场景反向补齐原理",
        "project_based": "以真实项目与方案任务驱动，沉淀方法论",
    }[learning_style]

    summary = (
        f"该学习者「{info['major'] or '无相关专业'}」背景、{info['work_years']:g}年工作经历，"
        f"前置测试 {info['total_score']}/{info['max_score']}。"
        f"诊断难度 {difficulty}，学习风格 {learning_style}（{style_desc}）。"
        f"学习目标：{info['learning_goal'] or '掌握工业机器人故障诊断'}。"
    )

    return {
        "knowledge_map": knowledge_map,
        "skill_gaps": skill_gaps,
        "learning_style": learning_style,
        "recommended_difficulty": difficulty,
        "summary": summary,
    }


def _grab_profile_param(user_message: str, key: str, default: str) -> str:
    """从「结构化画像参数」JSON 块解析单个字段（difficulty / learning_style / profile_tag）。"""
    m = re.search(r'"' + key + r'"\s*:\s*"([^"]+)"', user_message)
    return m.group(1).strip() if m else default


def _demo_generation(user_message: str) -> str:
    """知识生成模拟输出（机器人领域，读结构化画像参数，difficulty 透传）。"""
    difficulty = _grab_profile_param(user_message, "difficulty", "beginner")
    if difficulty not in ("beginner", "intermediate", "advanced"):
        difficulty = "beginner"
    style = _grab_profile_param(user_message, "learning_style", "theory_first")
    if style not in ("visual", "theory_first", "practice_first", "project_based"):
        style = "theory_first"
    profile_tag = _grab_profile_param(user_message, "profile_tag", "custom")

    topic_m = re.search(r"\]\s*([^(\n]+)", user_message)
    focus = topic_m.group(1).strip() if topic_m else "工业机器人示教编程"

    dlabel, duration = {
        "beginner": ("入门", 20),
        "intermediate": ("进阶", 30),
        "advanced": ("高级", 45),
    }[difficulty]

    content = (
        f"# {dlabel}讲义：{focus}\n\n"
        f"> 难度：{difficulty} · 风格：{style} · 画像：{profile_tag}\n\n"
        f"## 1. 认识 {focus}\n\n工业机器人故障诊断中 {focus} 的核心概念与现场意义。\n\n"
        f"## 2. FANUC / KUKA / ABB 现场对比\n\n"
        f"- FANUC：示教器 TP 界面与坐标系设定\n"
        f"- KUKA：KRL 程序结构与 BASE/TOOL 标定\n"
        f"- ABB：RAPID 语言与 RobotStudio 仿真\n\n"
        f"## 3. 总结\n\n掌握 {focus} 的关键点与下一步实践建议。"
    )

    return json.dumps(
        {
            "title": f"{dlabel}·{focus}",
            "content": content,
            "citations": [
                {
                    "ref_index": 1,
                    "original_text": f"{focus} 相关技术规范（FANUC/KUKA/ABB）",
                    "usage": "第1节概念",
                },
                {
                    "ref_index": 2,
                    "original_text": "工业机器人安全操作规程",
                    "usage": "安全提示",
                },
            ],
            "difficulty_level": difficulty,
            "estimated_duration_minutes": duration,
            "key_takeaways": [
                f"理解 {focus} 的核心概念",
                f"掌握 {focus} 的现场操作要点",
                "了解 FANUC / KUKA / ABB 三品牌的差异",
            ],
        },
        ensure_ascii=False,
    )


def _demo_audit() -> str:
    """内容审核模拟输出：默认 approved，附 info 提示为模拟审核。"""
    return json.dumps(
        {
            "verdict": "approved",
            "issues": [
                {
                    "severity": "info",
                    "detail": "演示模式审核 — 未进行真实事实核查。设置 LLM_API_KEY 以启用完整审核流程。",  # noqa: E501
                },
            ],
        },
        ensure_ascii=False,
    )


def _demo_correction(user_message: str) -> str:
    """保真修正模拟输出（机器人领域，读结构化画像参数 + 模拟重试/兜底）。"""
    expected_diff = _grab_profile_param(user_message, "difficulty", "beginner")
    if expected_diff not in ("beginner", "intermediate", "advanced"):
        expected_diff = "beginner"
    profile_tag = _grab_profile_param(user_message, "profile_tag", "custom")

    is_retry = "## 重写任务" in user_message or "待对齐" in user_message
    orig_m = re.search(r"(?:难度标注|当前难度标注)[：:]\s*(\w+)", user_message)
    original_diff = orig_m.group(1).strip() if orig_m else expected_diff

    if is_retry:
        out_diff = expected_diff
    elif original_diff and original_diff != expected_diff:
        out_diff = original_diff
    else:
        out_diff = expected_diff

    if is_retry:
        content_match = re.search(r"- 内容：\s*\n(.+?)(?=\n## 输出 JSON)", user_message, re.DOTALL)
    else:
        content_match = re.search(
            r"### 原始内容\s*\n(.+?)(?=\n## (?:审核发现|知识库|修正任务))",
            user_message,
            re.DOTALL,
        )
    original_content = content_match.group(1).strip() if content_match else ""

    corrected_content = original_content or (
        "# 演示模式修正示例\n\n工业机器人故障诊断资源（示例）。\n\n"
        "请设置 LLM_API_KEY 环境变量以启用真实的保真修正。"
    )

    return json.dumps(
        {
            "title": "学习资源（已修正）",
            "content": corrected_content,
            "difficulty_level": out_diff,
            "citations": [
                {
                    "doc_id": "demo_robot_fault_kb.md",
                    "chunk_index": 1,
                    "original_text": "SRVO-068 为数据传输故障，需检查示教器与主机间的通信链路。",
                    "relevance_score": 0.95,
                },
            ],
            "key_takeaways": [
                f"理解 {profile_tag} 画像对应的 {expected_diff} 内容要点",
                "掌握工业机器人故障代码的定位思路",
                "了解 FANUC / KUKA / ABB 三品牌的现场差异",
            ],
            "correction_summary": "演示模式占位修正",
            "_infos_applied": 0,
        },
        ensure_ascii=False,
    )


class DemoLLM:
    """离线演示 LLM 单例。"""

    is_demo: bool = True

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """返回模拟文本（JSON 字符串）。"""
        logger.info("[LLM Demo] 模拟调用 (temperature={})", temperature)
        prompt_lower = (system_prompt or "").lower()

        if any(k in prompt_lower for k in ("学情诊断", "diagnosis")):
            return json.dumps(_demo_diagnosis(user_message), ensure_ascii=False)

        if any(k in prompt_lower for k in ("垂直领域", "内容创作", "generation")):
            return _demo_generation(user_message)

        if any(k in prompt_lower for k in ("审核", "audit")):
            return _demo_audit()

        if any(k in prompt_lower for k in ("修正", "correction")):
            return _demo_correction(user_message)

        # ── 兜底：无法匹配场景，返回占位 JSON 不抛异常 ──
        logger.warning("[LLM Demo] 未匹配到场景，system_prompt 前 80 字符: {}", system_prompt[:80])
        return json.dumps(
            {"message": "演示模式 — 无 LLM API Key", "hint": "设置 LLM_API_KEY 以启用真实调用"},
            ensure_ascii=False,
        )

    async def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 call() 并解析为 dict。解析失败返回 {}（不抛异常）。"""
        text = await self.call(system_prompt, user_message, temperature=temperature, **kwargs)
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            logger.exception("[LLM Demo] JSON 解析失败")
            return {}


# ── 全局单例（唯一入口）──
llm = DemoLLM()

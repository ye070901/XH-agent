"""Mock 诊断结果 —— 模拟 Agent1（学情诊断）输出，供 Opt-3 EventBus 测试使用。

3 条假诊断数据覆盖初级/中级两个难度，薄弱环节覆盖工业机器人核心技能领域。

Usage:
    from tests.mock_responses import MOCK_DIAGNOSIS_1, MOCK_DIAGNOSIS_2, MOCK_DIAGNOSIS_3
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════
# Mock 1：初级用户 — 坐标系概念 + 示教器操作
# ═══════════════════════════════════════════════════════════

MOCK_DIAGNOSIS_1: dict = {
    "diagnosis_result": {
        "summary": "学员为工业机器人初级操作者，缺乏坐标系基础概念，示教器操作不熟练。",
        "skill_gaps": [
            {
                "topic": "机器人坐标系（工具/用户/世界）",
                "current_level": 0.1,
                "target_level": 0.6,
                "priority": "critical",
                "reason": "测前问卷中坐标系相关题目全部答错，无法区分工具坐标系与用户坐标系",
            },
            {
                "topic": "FANUC 示教器基本操作",
                "current_level": 0.3,
                "target_level": 0.7,
                "priority": "high",
                "reason": "能完成开机/关机/点动，但对程序 Step 编辑不熟悉",
            },
            {
                "topic": "工业机器人安全操作规范",
                "current_level": 0.2,
                "target_level": 0.5,
                "priority": "medium",
                "reason": "不了解急停恢复流程和安全门锁机制",
            },
        ],
        "knowledge_map": {
            "机器人坐标系": {
                "topic": "机器人坐标系",
                "level": 0.1,
                "confidence": 0.85,
                "evidence": "测前问卷第1-3题（坐标系选择题）全部错误",
            },
            "示教器操作": {
                "topic": "示教器操作",
                "level": 0.3,
                "confidence": 0.80,
                "evidence": "自述有2周工厂实习经验，仅操作过点动和简单程序选择",
            },
            "安全规范": {
                "topic": "安全规范",
                "level": 0.2,
                "confidence": 0.75,
                "evidence": "测前问卷安全题正确率 2/5",
            },
        },
        "learning_style": "practice_first",
        "recommended_difficulty": "beginner",
        "additional_notes": "建议从实物示教器操作入手，配合仿真软件巩固坐标系概念。",
    },
    "diagnosis_completed": True,
    "status": "diagnosis_done",
}

# ═══════════════════════════════════════════════════════════
# Mock 2：中级用户 — 离线编程仿真 + I/O 通信配置
# ═══════════════════════════════════════════════════════════

MOCK_DIAGNOSIS_2: dict = {
    "diagnosis_result": {
        "summary": "学员具备基础示教编程能力，但离线仿真和 I/O 通信配置经验不足。",
        "skill_gaps": [
            {
                "topic": "RobotStudio 离线编程与仿真",
                "current_level": 0.3,
                "target_level": 0.8,
                "priority": "critical",
                "reason": "未使用过离线编程软件，所有程序均在实机上编辑，效率低且风险高",
            },
            {
                "topic": "工业机器人 I/O 通信配置",
                "current_level": 0.4,
                "target_level": 0.7,
                "priority": "high",
                "reason": "了解基本 I/O 概念但未实际配置过 PLC 与机器人之间的信号映射",
            },
            {
                "topic": "KUKA KRL 高级编程",
                "current_level": 0.5,
                "target_level": 0.75,
                "priority": "medium",
                "reason": "能用基本运动指令，但对中断程序、循环逻辑和子程序调用不熟练",
            },
        ],
        "knowledge_map": {
            "离线编程仿真": {
                "topic": "离线编程仿真",
                "level": 0.3,
                "confidence": 0.80,
                "evidence": "自述未接触过 RobotStudio 或 KUKA.Sim",
            },
            "IO通信": {
                "topic": "IO通信",
                "level": 0.4,
                "confidence": 0.75,
                "evidence": "能说出常见现场总线名称，但无法描述 DeviceNet 配置步骤",
            },
            "KRL编程": {
                "topic": "KRL编程",
                "level": 0.5,
                "confidence": 0.70,
                "evidence": "1年 KUKA 操作经验，能编写简单点到点程序",
            },
        },
        "learning_style": "project_based",
        "recommended_difficulty": "intermediate",
        "additional_notes": (
            "建议通过 RobotStudio 虚拟工作站练习离线编程，再逐步引入 PLC 信号联调。"
        ),
    },
    "diagnosis_completed": True,
    "status": "diagnosis_done",
}

# ═══════════════════════════════════════════════════════════
# Mock 3：初级用户 — 程序 Step 编辑 + 工具坐标系设定
# ═══════════════════════════════════════════════════════════

MOCK_DIAGNOSIS_3: dict = {
    "diagnosis_result": {
        "summary": (
            "学员有机械加工背景但刚转入工业机器人领域，需从 FANUC 基础编程和工具坐标系起步。"
        ),
        "skill_gaps": [
            {
                "topic": "FANUC TP 程序的 Step 编辑与运动指令",
                "current_level": 0.15,
                "target_level": 0.65,
                "priority": "critical",
                "reason": "不了解 J/L/C 运动指令的区别，不知道如何在程序中插入/删除 Step",
            },
            {
                "topic": "工具坐标系（TCP）设定与校验",
                "current_level": 0.1,
                "target_level": 0.6,
                "priority": "critical",
                "reason": "完全不理解 TCP 概念，无法完成三点法/六点法标定",
            },
            {
                "topic": "机器人程序调试与单步执行",
                "current_level": 0.2,
                "target_level": 0.55,
                "priority": "high",
                "reason": "只能用自动模式跑完整程序，不会使用单步模式和断点调试",
            },
        ],
        "knowledge_map": {
            "TP程序Step编辑": {
                "topic": "TP程序Step编辑",
                "level": 0.15,
                "confidence": 0.85,
                "evidence": "测前问卷编程题正确率 0/3",
            },
            "工具坐标系设定": {
                "topic": "工具坐标系设定",
                "level": 0.1,
                "confidence": 0.90,
                "evidence": "面试时无法说明 TCP 的含义",
            },
            "程序调试": {
                "topic": "程序调试",
                "level": 0.2,
                "confidence": 0.75,
                "evidence": "自述仅操作过已编好的生产程序",
            },
        },
        "learning_style": "visual",
        "recommended_difficulty": "beginner",
        "additional_notes": "推荐先从视频教程理解运动类型差异，再上仿真环境练习 Step 编辑。",
    },
    "diagnosis_completed": True,
    "status": "diagnosis_done",
}

# ═══════════════════════════════════════════════════════════
# 批量导出
# ═══════════════════════════════════════════════════════════

ALL_MOCK_DIAGNOSES: list[dict] = [
    MOCK_DIAGNOSIS_1,
    MOCK_DIAGNOSIS_2,
    MOCK_DIAGNOSIS_3,
]

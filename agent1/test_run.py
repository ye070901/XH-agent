"""学情诊断 Agent 测试用例

运行方式:
    python test_run.py

包含 3 组测试用例，模拟不同层次学习者的学情诊断。
"""

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents import DiagnosisAgent


def pretty_print(title: str, data: dict):
    """格式化打印诊断结果"""
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  {title}")
    print(f"{sep}")

    result = data.get("diagnosis_result", {})

    if "error" in result:
        print(f"\n⚠️  错误: {result['error']}")
        if "raw_output" in result:
            print(f"\n原始输出片段:\n{result['raw_output'][:500]}")
        return

    # 综合评估
    print(f"\n📋 综合评估: {result.get('overall_assessment', '')}\n")

    # 知识图谱
    print("📊 知识图谱:")
    print("-" * 60)
    for kp in result.get("knowledge_map", []):
        level = kp.get("level", "未知")
        mastery = kp.get("mastery", 0)
        bar = "█" * int(mastery * 20) + "░" * (20 - int(mastery * 20))
        print(f"  {kp['name']}")
        print(f"    掌握度: {mastery:.0%} {bar} [{level}]")
        for ev in kp.get("evidence", []):
            print(f"    证据: {ev}")
        print()

    # 技能短板
    gaps = result.get("skill_gaps", [])
    if gaps:
        print("🔴 技能短板:")
        print("-" * 60)
        for gap in gaps:
            severity_tag = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(
                gap.get("severity", ""), "⚪"
            )
            print(f"  {severity_tag} [{gap.get('severity', '?')}] {gap['skill']}")
            print(f"    说明: {gap.get('description', '')}")
            prereqs = gap.get("prerequisite_for", [])
            if prereqs:
                print(f"    阻塞: {', '.join(prereqs)}")
            print()
    else:
        print("✅ 未发现明显技能短板\n")

    # 建议
    print("💡 学习建议:")
    print("-" * 60)
    for i, rec in enumerate(result.get("recommendations", []), 1):
        print(f"  {i}. {rec}")

    print(f"{sep}\n")


def test_case_1():
    """用例1：高中生学习 Python"""
    print("\n" + "🔥" * 35)
    print("🔥  用例 1：高中生学习 Python")
    print("🔥" * 35)

    learner_data = {
        "name": "张三",
        "age": 17,
        "education": "高中三年级",
        "background": "理科生，数学成绩中等偏上，未接触过任何编程",
        "learning_goal": "掌握Python基础，能独立完成简单的数据处理脚本",
        "current_course": "Python入门",
        "learning_history": [
            {"topic": "变量与数据类型", "status": "已完成", "score": 85},
            {"topic": "条件判断", "status": "已完成", "score": 72},
            {"topic": "循环语句", "status": "学习中", "score": 55},
            {"topic": "函数定义", "status": "未开始", "score": 0},
            {"topic": "列表与字典操作", "status": "未开始", "score": 0},
        ],
        "quiz_results": [
            {"name": "基础语法测验", "score": 68, "total": 100},
            {"name": "逻辑推理测验", "score": 75, "total": 100},
        ],
        "study_time": {
            "total_hours": 18,
            "weeks": 3,
            "avg_hours_per_week": 6,
        },
        "struggles": [
            "多层嵌套的条件判断容易混淆",
            "循环中的 break/continue 理解不深",
            "变量作用域概念模糊",
        ],
    }

    agent = DiagnosisAgent()
    state = {"learner_data": learner_data}
    state = agent.run(state)
    pretty_print("用例 1：高中生学习 Python", state)


def test_case_2():
    """用例2：本科计算机专业学习 LangGraph"""
    print("\n" + "🔥" * 35)
    print("🔥  用例 2：本科计算机专业学习 LangGraph")
    print("🔥" * 35)

    learner_data = {
        "name": "李四",
        "age": 21,
        "education": "本科计算机科学与技术 三年级",
        "background": "已完成数据结构、操作系统、计算机网络等核心课程，GPA 3.6/4.0",
        "learning_goal": "掌握 LangGraph 框架，能构建复杂的多Agent工作流系统",
        "current_course": "LangGraph 进阶实战",
        "learning_history": [
            {"topic": "Python高级特性", "status": "已完成", "score": 92},
            {"topic": "函数式编程基础", "status": "已完成", "score": 85},
            {"topic": "LLM API调用", "status": "已完成", "score": 78},
            {"topic": "LangChain基础", "status": "已完成", "score": 70},
            {"topic": "StateGraph构建", "status": "学习中", "score": 60},
            {"topic": "多Agent编排", "status": "未开始", "score": 0},
            {"topic": "记忆与持久化", "status": "未开始", "score": 0},
            {"topic": "条件路由与分支", "status": "未开始", "score": 0},
        ],
        "quiz_results": [
            {"name": "LangChain核心概念", "score": 72, "total": 100},
            {"name": "Graph状态管理", "score": 55, "total": 100},
        ],
        "project_experience": [
            {
                "name": "基于LLM的问答机器人",
                "role": "主要开发者",
                "description": "使用LangChain构建RAG问答系统",
            },
            {
                "name": "数据爬取与分析工具",
                "role": "独立完成",
                "description": "Scrapy + Pandas 数据流水线",
            },
        ],
        "study_time": {
            "total_hours": 45,
            "weeks": 6,
            "avg_hours_per_week": 7.5,
        },
        "struggles": [
            "State 的图结构状态传递逻辑不够清晰",
            "Reducer 自定义逻辑容易出错",
            "多个节点间的条件路由理解不够深入",
            "对 Pregel 执行模型的底层机制不熟悉",
        ],
    }

    agent = DiagnosisAgent()
    state = {"learner_data": learner_data}
    state = agent.run(state)
    pretty_print("用例 2：本科计算机专业学习 LangGraph", state)


def test_case_3():
    """用例3：博士学习多Agent系统"""
    print("\n" + "🔥" * 35)
    print("🔥  用例 3：博士学习多Agent系统")
    print("🔥" * 35)

    learner_data = {
        "name": "王五",
        "age": 28,
        "education": "计算机科学博士 二年级",
        "research_direction": "多Agent协作与分布式智能系统",
        "background": "本科及硕士均为CS专业，发表过 3 篇 NLP 相关论文，熟悉 Transformers、RLHF",
        "learning_goal": "深入理解多Agent协作机制，设计可扩展的多Agent协作框架",
        "current_course": "多Agent系统理论与设计",
        "learning_history": [
            {"topic": "单Agent架构设计", "status": "已完成", "score": 95},
            {"topic": "Agent通信协议", "status": "已完成", "score": 88},
            {"topic": "任务分解与分配", "status": "已完成", "score": 82},
            {"topic": "多Agent协商机制", "status": "学习中", "score": 65},
            {"topic": "分布式Agent协调", "status": "学习中", "score": 58},
            {"topic": "Agent安全与对齐", "status": "未开始", "score": 0},
            {"topic": "可扩展Agent框架设计", "status": "未开始", "score": 0},
        ],
        "quiz_results": [
            {"name": "Agent架构设计", "score": 92, "total": 100},
            {"name": "通信与协调机制", "score": 68, "total": 100},
        ],
        "publications": [
            "基于Prompt Engineering的少样本文本分类",
            "RLHF在多轮对话中的偏好对齐研究",
            "面向特定领域的LLM微调策略比较",
        ],
        "research_notes": "正在设计一个基于市场机制的Agent资源分配协议，希望将经济学模型引入多Agent协调",
        "study_time": {
            "total_hours": 120,
            "weeks": 10,
            "avg_hours_per_week": 12,
        },
        "struggles": [
            "分布式场景下Agent间的一致性问题",
            "动态Agent数量时的任务重分配策略",
            "多Agent系统中的信用分配问题",
            "将理论模型工程化落地的实践困难",
        ],
    }

    agent = DiagnosisAgent()
    state = {"learner_data": learner_data}
    state = agent.run(state)
    pretty_print("用例 3：博士学习多Agent系统", state)


def main():
    print("=" * 70)
    print("  学情诊断 Agent — 测试运行")
    print("  注意：请先配置 backend/config.py 中的 DEEPSEEK_API_KEY")
    print("=" * 70)

    test_case_1()
    test_case_2()
    test_case_3()

    print("\n✅ 所有测试用例执行完毕!")


if __name__ == "__main__":
    main()

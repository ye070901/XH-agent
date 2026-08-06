"""Agent1 Day4 学情诊断单元测试

校验 diagnosis.process 输出的 5 个字段，符合 DiagnosisGate 输出格式。
本测试为 Agent1 独立实现，不引用任何外部（Agent3）代码。

运行方式:
    python tests/test_agent1_day4.py
    或
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import json
import os
import sys
import tempfile
import unittest

# 将项目根目录加入 sys.path，便于从 tests/ 下导入 agents/backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.diagnosis import (
    DEFAULT_EXCHANGE_OUT,
    DiagnosisAgent,
    _demo_diagnosis,
    export_diagnosis,
    validate_diagnosis_result,
)

EXPECTED_FIELDS = {
    "knowledge_map",
    "skill_gaps",
    "learning_style",
    "recommended_difficulty",
    "summary",
}
VALID_PRIORITY = {"critical", "high", "medium", "low"}
VALID_LEVEL = {"未掌握", "初步了解", "基本掌握", "熟练应用", "融会贯通"}
VALID_SEVERITY = {"高", "中", "低"}
VALID_DIFFICULTY = {"低", "中低", "中等", "中高", "高"}


def sample_learner() -> dict:
    """构造一个最小可诊断的学习者画像（离线，不依赖网络）。"""
    return {
        "name": "单元测试学员",
        "age": 17,
        "education": "高中三年级",
        "background": "理科生，数学成绩中等偏上，未接触过任何编程",
        "learning_goal": "掌握Python基础，能独立完成简单的数据处理脚本",
        "current_course": "Python入门",
        "learning_history": [
            {"topic": "Python - 变量与数据类型", "status": "已完成", "score": 85},
            {"topic": "Python - 条件判断", "status": "已完成", "score": 72},
            {"topic": "Python - 循环语句", "status": "学习中", "score": 55},
            {"topic": "Python - 函数定义", "status": "未开始", "score": 0},
            {"topic": "Python - 列表与字典", "status": "未开始", "score": 0},
        ],
        "quiz_results": [{"name": "基础语法测验", "score": 68, "total": 100}],
        "struggles": ["多层嵌套的条件判断容易混淆", "循环中的 break/continue 理解不深"],
    }


class TestDemoDiagnosis(unittest.TestCase):
    """确定性演示诊断：5 字段完整性与 DiagnosisGate 格式"""

    def test_demo_returns_exactly_five_fields(self):
        result = _demo_diagnosis(sample_learner())
        self.assertEqual(set(result.keys()), EXPECTED_FIELDS)

    def test_demo_passes_gate_validation(self):
        result = _demo_diagnosis(sample_learner())
        self.assertEqual(validate_diagnosis_result(result), [])

    def test_knowledge_map_gate(self):
        result = _demo_diagnosis(sample_learner())
        km = result["knowledge_map"]
        self.assertGreaterEqual(len(km), 5)
        for kp in km:
            self.assertIn("name", kp)
            self.assertIn(kp["priority"], VALID_PRIORITY)
            self.assertIn(kp["level"], VALID_LEVEL)
            self.assertTrue(0.0 <= kp["mastery"] <= 1.0)
            self.assertTrue(0.0 <= kp["confidence"] <= 1.0)
            self.assertGreaterEqual(len(kp["evidence"]), 1)

    def test_skill_gaps_format(self):
        result = _demo_diagnosis(sample_learner())
        for gap in result["skill_gaps"]:
            self.assertIn("skill", gap)
            self.assertIn(gap["severity"], VALID_SEVERITY)
            self.assertIn("description", gap)
            self.assertIn("prerequisite_for", gap)

    def test_learning_style_format(self):
        ls = _demo_diagnosis(sample_learner())["learning_style"]
        self.assertIsInstance(ls, dict)
        self.assertIn("style", ls)
        self.assertIn(ls["style"], {"视觉型", "听觉型", "读写型", "动手型", "混合型"})

    def test_recommended_difficulty_format(self):
        rd = _demo_diagnosis(sample_learner())["recommended_difficulty"]
        self.assertIsInstance(rd, dict)
        self.assertIn("level", rd)
        self.assertIn(rd["level"], VALID_DIFFICULTY)

    def test_summary_is_nonempty_text(self):
        summary = _demo_diagnosis(sample_learner())["summary"]
        self.assertIsInstance(summary, str)
        self.assertTrue(summary.strip())

    def test_empty_learner_still_valid(self):
        result = _demo_diagnosis({})
        self.assertEqual(set(result.keys()), EXPECTED_FIELDS)
        self.assertEqual(validate_diagnosis_result(result), [])


class TestProcess(unittest.TestCase):
    """process()：演示模式 / LLM 回退 / 合法 LLM 输出"""

    def test_process_demo_mode_five_fields(self):
        result = DiagnosisAgent().process(sample_learner(), use_demo=True)
        self.assertEqual(set(result.keys()), EXPECTED_FIELDS)
        self.assertEqual(validate_diagnosis_result(result), [])

    def test_process_falls_back_when_llm_raises(self):
        agent = DiagnosisAgent()

        def boom(messages, **kwargs):
            raise RuntimeError("模拟网络/API 故障")

        agent.call_llm = boom
        result = agent.process(sample_learner())
        self.assertEqual(set(result.keys()), EXPECTED_FIELDS)
        self.assertEqual(validate_diagnosis_result(result), [])

    def test_process_falls_back_on_garbage_output(self):
        agent = DiagnosisAgent()
        agent.call_llm = lambda messages, **kwargs: "这不是 JSON"
        result = agent.process(sample_learner())
        self.assertEqual(set(result.keys()), EXPECTED_FIELDS)
        self.assertEqual(validate_diagnosis_result(result), [])

    def test_process_accepts_valid_llm_json(self):
        agent = DiagnosisAgent()
        valid = _demo_diagnosis(sample_learner())
        agent.call_llm = lambda messages, **kwargs: json.dumps(
            valid, ensure_ascii=False
        )
        result = agent.process(sample_learner())
        self.assertEqual(set(result.keys()), EXPECTED_FIELDS)
        self.assertEqual(validate_diagnosis_result(result), [])

    def test_run_keeps_state_backward_compat(self):
        agent = DiagnosisAgent()

        def boom(messages, **kwargs):
            raise RuntimeError("模拟网络/API 故障")

        agent.call_llm = boom  # 离线运行，回退到确定性演示结果
        state = {"learner_data": sample_learner()}
        state = agent.run(state)
        self.assertEqual(set(state["diagnosis_result"].keys()), EXPECTED_FIELDS)


class TestExport(unittest.TestCase):
    """导出函数：写入桌面公共交换文件路径"""

    def test_export_writes_file_and_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "diagnosis_out.json")
            written = export_diagnosis(sample_learner(), out_path=out, use_demo=True)
            self.assertTrue(os.path.exists(written))
            with open(written, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(set(data.keys()), EXPECTED_FIELDS)
            self.assertEqual(validate_diagnosis_result(data), [])

    def test_export_default_target_is_exchange(self):
        self.assertEqual(
            DEFAULT_EXCHANGE_OUT, r"C:\Users\CAT\Desktop\exchange\diagnosis_out.json"
        )


class TestValidate(unittest.TestCase):
    """validate_diagnosis_result 对非法结果的拦截"""

    def test_rejects_missing_fields(self):
        self.assertTrue(validate_diagnosis_result({"knowledge_map": []}))

    def test_rejects_too_few_knowledge_points(self):
        result = _demo_diagnosis(sample_learner())
        result["knowledge_map"] = result["knowledge_map"][:2]
        self.assertTrue(validate_diagnosis_result(result))

    def test_rejects_bad_priority(self):
        result = _demo_diagnosis(sample_learner())
        result["knowledge_map"][0]["priority"] = "urgent"
        self.assertTrue(validate_diagnosis_result(result))

    def test_rejects_bad_difficulty(self):
        result = _demo_diagnosis(sample_learner())
        result["recommended_difficulty"]["level"] = "超高"
        self.assertTrue(validate_diagnosis_result(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)

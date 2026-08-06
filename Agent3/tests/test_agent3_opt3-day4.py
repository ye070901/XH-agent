"""
Agent3 day4 初审模块测试 — 全部使用 mock 输入，不导入 agent1 任何代码。

运行方式：
    python tests/test_agent3_day4.py
    pytest  tests/test_agent3_day4.py

说明：
    - 只 import Agent3 项目自己的 agent3_day4 模块（stdlib 之外无第三方依赖）。
    - 文件读写测试使用 tempfile 临时目录，不触碰真实 exchange 目录。
    - LLM 测试使用注入的 Fake 客户端，不发生任何真实网络请求。
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

# 将项目根目录（Agent3）加入 sys.path，以便导入本项目的 agent3_day4
# （此处仅指向 Agent3 自身，与 agent1 无关）
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent3_day4 import (
    audit_from_exchange,
    process,
    read_input,
    write_output,
    _collect_critical_gaps,
    _extract_input,
    _topic_covered,
)


def _clean_resource(title: str = "闭包详解", difficulty: str = "intermediate") -> dict:
    """构造一个通过全部规则检查的干净资源。"""
    return {
        "resource_type": "article",
        "title": title,
        "difficulty_level": difficulty,
        "content": (
            "闭包（Closure）是 Python 中一个重要的概念：在外部函数中定义内部函数，"
            "内部函数引用外部函数的变量，并且外部函数把内部函数作为返回值返回，"
            "闭包可以让函数记住创建时的环境，这是理解 Python 高级语法的关键一步。"
        ),
        "citations": [{"doc_id": "01_LangGraph概述.md", "chunk_index": 0}],
        "target_skill_gaps": ["闭包"],
    }


class ProcessContractTests(unittest.TestCase):
    """process(generated_resources) 输出契约测试。"""

    def test_output_shape(self):
        """输出必须是 {"verdict": str, "issues": list}。"""
        result = asyncio.run(process([], diagnosis_result={}))
        self.assertEqual(set(result.keys()), {"verdict", "issues"})
        self.assertIsInstance(result["verdict"], str)
        self.assertIsInstance(result["issues"], list)

    def test_empty_resources_is_uncertain(self):
        result = asyncio.run(process([], diagnosis_result={}))
        self.assertEqual(result["verdict"], "uncertain")
        self.assertTrue(result["issues"])

    def test_none_resources_is_uncertain(self):
        result = asyncio.run(process(None, diagnosis_result={}))
        self.assertEqual(result["verdict"], "uncertain")

    def test_clean_resource_approved(self):
        diagnosis = {"recommended_difficulty": "intermediate", "skill_gaps": []}
        result = asyncio.run(process([_clean_resource()], diagnosis_result=diagnosis))
        self.assertEqual(result["verdict"], "approved")
        self.assertEqual(result["issues"], [])

    def test_missing_content_is_error(self):
        resource = _clean_resource()
        resource["content"] = ""
        result = asyncio.run(process([resource], diagnosis_result={}))
        self.assertEqual(result["verdict"], "needs_revision")
        self.assertTrue(any(i["severity"] == "error" for i in result["issues"]))

    def test_difficulty_gap_two_is_error(self):
        resource = _clean_resource(difficulty="advanced")
        diagnosis = {"recommended_difficulty": "beginner", "skill_gaps": []}
        result = asyncio.run(process([resource], diagnosis_result=diagnosis))
        self.assertEqual(result["verdict"], "needs_revision")
        self.assertTrue(any(i["severity"] == "error" for i in result["issues"]))

    def test_difficulty_gap_one_is_warning_approved(self):
        resource = _clean_resource(difficulty="advanced")
        diagnosis = {"recommended_difficulty": "intermediate", "skill_gaps": []}
        result = asyncio.run(process([resource], diagnosis_result=diagnosis))
        # 仅 warning → 结论仍为 approved，但 issues 要列出
        self.assertEqual(result["verdict"], "approved")
        self.assertTrue(any(i["severity"] == "warning" for i in result["issues"]))

    def test_accepts_object_like_resource(self):
        class FakeResource:
            def __init__(self):
                self.resource_type = "guide"
                self.title = "对象形式资源"
                self.difficulty_level = "beginner"
                self.content = "对象形式资源的一段足够长的完整内容，用于验证对象输入被正确转换。"
                self.citations = [{"doc_id": "x", "chunk_index": 0}]
                self.target_skill_gaps = []

        result = asyncio.run(process([FakeResource()], diagnosis_result={}))
        self.assertEqual(result["verdict"], "approved")

    def test_accepts_exchange_bundle_dict(self):
        """process 可直接接收含 generated_resources / diagnosis_result 的完整输入。"""
        bundle = {
            "diagnosis_result": {"recommended_difficulty": "intermediate", "skill_gaps": []},
            "generated_resources": [_clean_resource()],
        }
        result = asyncio.run(process(bundle))
        self.assertEqual(result["verdict"], "approved")


class CoverageTests(unittest.TestCase):
    """盲区覆盖测试。"""

    def test_uncovered_critical_gap_warns(self):
        resources = [
            {
                "resource_type": "article",
                "title": "Python 语法",
                "difficulty_level": "intermediate",
                "content": "只讲 Python 基础语法与数据类型，与前端框架无关。",
            }
        ]
        diagnosis = {
            "recommended_difficulty": "intermediate",
            "skill_gaps": [{"priority": "critical", "topic": "React Hooks 最佳实践"}],
        }
        result = asyncio.run(process(resources, diagnosis_result=diagnosis))
        self.assertEqual(result["verdict"], "approved")  # 仅 warning
        self.assertTrue(any("盲区" in i["detail"] for i in result["issues"]))

    def test_covered_critical_gap_no_warning(self):
        resources = [
            {
                "resource_type": "article",
                "title": "React Hooks 最佳实践",
                "difficulty_level": "intermediate",
                "content": "讲解 useState 与 useEffect 的用法与最佳实践，覆盖 React Hooks 核心知识点。",
                "target_skill_gaps": ["React Hooks 最佳实践"],
            }
        ]
        diagnosis = {
            "recommended_difficulty": "intermediate",
            "skill_gaps": [{"priority": "critical", "topic": "React Hooks 最佳实践"}],
        }
        result = asyncio.run(process(resources, diagnosis_result=diagnosis))
        self.assertFalse(any("盲区" in i["detail"] for i in result["issues"]))

    def test_accepts_agent1_style_fields(self):
        """兼容 agent1 的字段命名（skill_gaps.skill / severity=高，knowledge_map.name）。"""
        diagnosis = {
            "skill_gaps": [
                {"skill": "A", "severity": "高"},
                {"skill": "B", "severity": "中"},
            ],
            "knowledge_map": [{"name": "C", "priority": "high"}],
        }
        gaps = _collect_critical_gaps(diagnosis)
        topics = {t for _, t in gaps}
        self.assertIn("A", topics)
        self.assertIn("C", topics)
        self.assertNotIn("B", topics)


class LLMEnrichmentTests(unittest.TestCase):
    """可选 LLM 深度核验（注入 Fake 客户端，无网络请求）。"""

    def test_llm_issue_merged_and_flips_verdict(self):
        class FakeLLM:
            async def audit_resource(self, index, resource, diagnosis):
                return [{"severity": "error", "detail": "代码示例存在语法错误（mock）"}]

        result = asyncio.run(
            process([_clean_resource()], diagnosis_result={}, llm_client=FakeLLM())
        )
        self.assertEqual(result["verdict"], "needs_revision")
        self.assertTrue(any("语法错误" in i["detail"] for i in result["issues"]))

    def test_llm_failure_is_safe(self):
        class BrokenLLM:
            async def audit_resource(self, index, resource, diagnosis):
                raise RuntimeError("mock 网络故障")

        result = asyncio.run(
            process([_clean_resource()], diagnosis_result={}, llm_client=BrokenLLM())
        )
        # LLM 故障不影响规则审核；verdict 仍按规则层得出
        self.assertEqual(result["verdict"], "approved")
        self.assertTrue(any("大模型深度核验失败" in i["detail"] for i in result["issues"]))

    def test_llm_ignores_malformed_issues(self):
        class MessyLLM:
            async def audit_resource(self, index, resource, diagnosis):
                return ["不是 dict", {"severity": "unknown", "detail": ""}, {"detail": "无 severity"}]

        result = asyncio.run(
            process([_clean_resource()], diagnosis_result={}, llm_client=MessyLLM())
        )
        self.assertEqual(result["verdict"], "approved")


class TopicCoverageHelperTests(unittest.TestCase):
    def test_full_topic_match(self):
        self.assertTrue(_topic_covered("Python 装饰器与闭包", "本文介绍闭包概念".lower()))

    def test_partial_segment_match(self):
        # "Python 装饰器与闭包" 切分出 "闭包"，命中即可
        self.assertTrue(_topic_covered("Python 装饰器与闭包", "只提到闭包一词".lower()))

    def test_not_covered(self):
        self.assertFalse(_topic_covered("React Hooks 最佳实践", "本文只讲 Python 闭包".lower()))


class ExchangeIOTests(unittest.TestCase):
    """外部文件读 / 写 / 端到端审核（tempfile，不触碰真实 exchange 目录）。"""

    def test_extract_standard_input(self):
        data = {
            "diagnosis_result": {"recommended_difficulty": "beginner"},
            "generated_resources": [{"title": "A"}],
        }
        out = _extract_input(data)
        self.assertEqual(len(out["generated_resources"]), 1)
        self.assertEqual(out["diagnosis_result"]["recommended_difficulty"], "beginner")

    def test_extract_plain_list(self):
        out = _extract_input([{"title": "A"}, {"title": "B"}])
        self.assertEqual(len(out["generated_resources"]), 2)
        self.assertEqual(out["diagnosis_result"], {})

    def test_extract_nested_data_key(self):
        data = {"data": {"generated_resources": [{"title": "A"}], "diagnosis_result": {}}}
        out = _extract_input(data)
        self.assertEqual(len(out["generated_resources"]), 1)

    def test_extract_diagnosis_only(self):
        data = {"recommended_difficulty": "intermediate", "skill_gaps": []}
        out = _extract_input(data)
        self.assertEqual(out["generated_resources"], [])
        self.assertEqual(out["diagnosis_result"]["recommended_difficulty"], "intermediate")

    def test_read_input_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_input("Z:/no/such/dir/diagnosis_out.json")

    def test_read_input_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_input(str(p))

    def test_read_input_from_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "diagnosis_out.json"
            p.write_text(
                json.dumps(
                    {"generated_resources": [{"title": "A"}], "diagnosis_result": {}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            data = read_input(str(p))
            self.assertEqual(len(data["generated_resources"]), 1)

    def test_write_output_shape(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "audit_out.json"
            payload = write_output(
                str(out),
                {"verdict": "approved", "issues": []},
                [{"resource_index": 0, "verdict": "approved", "issues": []}],
                meta={"mode": "rule_only"},
            )
            self.assertTrue(out.exists())
            self.assertEqual(set(payload.keys()), {"verdict", "issues", "audit_result", "meta"})

    def test_audit_from_exchange_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "diagnosis_out.json"
            out = Path(td) / "audit_out.json"
            inp.write_text(
                json.dumps(
                    {
                        "diagnosis_result": {"recommended_difficulty": "intermediate", "skill_gaps": []},
                        "generated_resources": [_clean_resource()],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = asyncio.run(audit_from_exchange(str(inp), str(out)))

            self.assertTrue(out.exists())
            self.assertEqual(payload["verdict"], "approved")
            self.assertEqual(payload["issues"], [])
            self.assertEqual(payload["meta"]["resource_count"], 1)
            self.assertEqual(len(payload["audit_result"]), 1)

    def test_audit_from_exchange_writes_uncertain_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "diagnosis_out.json"
            out = Path(td) / "audit_out.json"
            inp.write_text(
                json.dumps({"diagnosis_result": {}, "generated_resources": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            payload = asyncio.run(audit_from_exchange(str(inp), str(out)))
            self.assertEqual(payload["verdict"], "uncertain")
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

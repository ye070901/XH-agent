"""修正 Agent 溯源绑定的回归测试。

覆盖路径 2（`_apply_arbitration_and_bind`）溯源绑定的两个收紧：
  1. `_collect_fact_points`：只收 `is_accurate=True` 的准确断言，
     跳过 `is_accurate=None`（unverifiable/partially_supported）与 `False`（hallucination），
     消除「刚被裁决删除的断言又被绑进溯源」的矛盾。
  2. `_format_fact_point`：超长 statement / source_text 各截 120 字，避免溯源块重复全文。
全部 mock/纯函数，不调 LLM。
"""

from __future__ import annotations

from src.agents.correction import CorrectionAgent


def test_collect_fact_points_only_accurate_items() -> None:
    agent = CorrectionAgent()
    audit_report = {
        "fact_check": {
            "items": [
                {
                    "claim": "准确的断言",
                    "is_accurate": True,
                    "evidence_from_kb": "KB原文A",
                    "citation_ref": "docA",
                    "chunk_index": 0,
                },
                {
                    "claim": "部分支持的断言",
                    "is_accurate": None,
                    "evidence_from_kb": "KB原文B",
                    "citation_ref": "docB",
                    "chunk_index": 1,
                },
                {
                    "claim": "无法验证的断言",
                    "is_accurate": None,
                    "evidence_from_kb": None,
                    "citation_ref": "",
                    "chunk_index": None,
                },
                {
                    "claim": "幻觉断言",
                    "is_accurate": False,
                    "evidence_from_kb": "反驳原文",
                    "citation_ref": "docC",
                    "chunk_index": 2,
                },
            ]
        }
    }
    points = agent._collect_fact_points({}, audit_report, [])
    statements = [p["statement"] for p in points]
    assert "准确的断言" in statements
    assert "部分支持的断言" not in statements
    assert "无法验证的断言" not in statements
    assert "幻觉断言" not in statements


def test_collect_fact_points_keeps_adjudication_replace() -> None:
    agent = CorrectionAgent()
    adjudications = [
        {
            "decision": "replace",
            "replacement_text": "KB修正文本",
            "claim": "原文错误断言",
            "evidence": "KB证据",
            "doc_id": "docD",
            "chunk_index": 4,
        }
    ]
    points = agent._collect_fact_points({}, {}, adjudications)
    assert len(points) == 1
    assert points[0]["statement"] == "KB修正文本"
    assert points[0]["doc_id"] == "docD"


def test_format_fact_point_truncates_long_fields() -> None:
    point = {
        "statement": "A" * 200,
        "source_text": "B" * 200,
        "doc_id": "doc1",
        "chunk_index": 3,
    }
    line = CorrectionAgent._format_fact_point(point)
    assert "A" * 120 + "…" in line
    assert "B" * 120 + "…" in line
    assert "A" * 121 not in line
    assert "B" * 121 not in line


def test_format_fact_point_short_fields_no_truncation() -> None:
    point = {"statement": "短陈述", "source_text": "短源", "doc_id": "doc1", "chunk_index": None}
    line = CorrectionAgent._format_fact_point(point)
    assert "【生成陈述】短陈述【KB原文出处】短源【来源】doc1" in line


def test_format_fact_point_flattens_newlines() -> None:
    # KB 原文自带换行（多行 markdown）→ 压平成单行，溯源块不再呈多行碎片
    point = {
        "statement": "第一行\n第二行\n第三行",
        "source_text": "源一行\n源二行",
        "doc_id": "doc1",
        "chunk_index": 0,
    }
    line = CorrectionAgent._format_fact_point(point)
    assert "\n" not in line
    assert "第一行 第二行 第三行" in line
    assert "源一行 源二行" in line


def test_apply_arbitration_replace_truncates_and_flattens_kb_text() -> None:
    # replace 内联：多行 KB 原文须压平 + 截断到 200 字，来源标注保留
    agent = CorrectionAgent()
    claim = "错误的断言"
    kb_text = "# KB文档\n\n" + "长文" * 500  # 多行且超长
    adjudications = [
        {
            "decision": "replace",
            "claim": claim,
            "replacement_text": kb_text,
            "doc_id": "docX",
            "chunk_index": 2,
        }
    ]
    content = f"正文 {claim} 结尾"
    new_content, logs = agent._apply_arbitration(content, adjudications, "r1", "lecture")

    assert claim not in new_content  # 已替换
    assert "\n" not in new_content  # 多行 KB 被压平成单行
    assert "长文" in new_content  # 截断后仍保留部分原文
    assert "长文" * 250 not in new_content  # 未整段内联（500 字原文被截到 200）
    assert "[来源: docX, 段落 2]" in new_content  # 来源标注保留
    assert logs[0]["action"] == "replaced"

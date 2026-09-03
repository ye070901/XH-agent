"""幂等重标注 reannotate_resources 单元测试。

验证流水线末端兜底标注（真实模式下修正 Agent 覆盖 content 丢脚注的场景）：
  - 对未标注的长文资源 content 追加块末分级脚注 + 产出 trace_report；
  - 幂等：对已带脚注的 content 重跑不产生重复脚注、结果一致；
  - 跳过 quiz（走前端结构化解析，不渲染块末脚注）；
  - 无知识库素材 / 空资源时保持原样。
"""

from backend.src.agents.generation_v2 import (
    _ANNOTATION_FOOTER_RE,
    reannotate_resources,
)

_CHUNKS = [
    {
        "doc_id": "K2_026_kuka_arctech_welding",
        "doc_title": "KUKA ArcTech 焊接参数",
        "chunk_index": 0,
        "content": "KUKA 机器人焊接：电流 180A、电压 24V、脉冲模式 PULSE_MODE、起弧 ARCON。",
    },
    {
        "doc_id": "K2_026_kuka_arctech_welding",
        "doc_title": "KUKA ArcTech 焊接参数",
        "chunk_index": 1,
        "content": "焊接速度 5mm/s，摆动模式 WEAVE，收弧 ARCOFF。",
    },
]

_TOPIC = "KUKA 机器人焊接参数设置"

_CONTENT = """# KUKA 焊接参数

## 起弧指令

起弧使用 ARCON 指令，收弧使用 ARCOFF 指令。

## 焊接电流

焊接电流应设为 180A，电压 24V。
"""


def _footer_count(content: str) -> int:
    return sum(1 for ln in content.split("\n") if _ANNOTATION_FOOTER_RE.match(ln))


def test_annotates_long_form_resource():
    res = [{"resource_type": "guide", "resource_id": "g1", "content": _CONTENT}]
    out = reannotate_resources(res, _CHUNKS, _TOPIC)
    assert out[0]["content"] != _CONTENT
    assert _footer_count(out[0]["content"]) >= 1
    report = out[0]["trace_report"]
    assert report["total_claims"] > 0
    assert report["source_docs"][0]["doc_id"] == "K2_026_kuka_arctech_welding"


def test_idempotent_no_duplicate_footers():
    res = [{"resource_type": "guide", "resource_id": "g1", "content": _CONTENT}]
    once = reannotate_resources(res, _CHUNKS, _TOPIC)[0]["content"]
    twice = reannotate_resources(
        [{"resource_type": "guide", "resource_id": "g1", "content": once}],
        _CHUNKS,
        _TOPIC,
    )[0]["content"]
    assert _footer_count(twice) == _footer_count(once)
    assert twice == once


def test_skips_quiz():
    res = [{"resource_type": "quiz", "resource_id": "q1", "content": _CONTENT}]
    out = reannotate_resources(res, _CHUNKS, _TOPIC)
    assert out[0]["content"] == _CONTENT
    assert "trace_report" not in out[0]


def test_empty_chunks_unchanged():
    res = [{"resource_type": "guide", "resource_id": "g1", "content": _CONTENT}]
    out = reannotate_resources(res, [], _TOPIC)
    assert out is res  # 无素材时原样返回同一列表
    assert out[0]["content"] == _CONTENT


def test_empty_resources():
    assert reannotate_resources([], _CHUNKS, _TOPIC) == []

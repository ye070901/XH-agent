"""审核兜底提取器 `_fallback_extract_claims` 的回归测试。

覆盖 LLM 提取失败 / 演示模式下的规则兜底路径：
  1. 引用块（`> 难度：…` / `> ⚠️ 安全提示：…`）不是可验证事实断言，须剔除；
  2. markdown 标题 / 代码块 / 链接照旧剔除；
  3. 正文事实断言仍正常保留。
全部为确定性规则，不调 LLM。
"""

from __future__ import annotations

from src.agents.audit import AuditAgent


def test_fallback_extract_filters_blockquote_metadata() -> None:
    agent = AuditAgent()
    content = (
        "> 难度：beginner · 风格：practice_first\n\n"
        "# 工业机器人示教器讲义\n\n"
        "进入手动模式前必须按下急停按钮。\n"
        "示教器用于对机器人进行点位示教与程序编辑。\n"
    )
    claims = agent._fallback_extract_claims(content)
    assert not any(c.lstrip().startswith(">") for c in claims)
    assert not any("难度" in c for c in claims)
    assert any("急停" in c for c in claims)


def test_fallback_extract_filters_safety_callout() -> None:
    agent = AuditAgent()
    content = "> ⚠️ 安全提示：进入手动模式前确认安全门关闭。\n\n示教点位前确认工作区间无人员。\n"
    claims = agent._fallback_extract_claims(content)
    assert not any(c.lstrip().startswith(">") for c in claims)
    # 普通正文句仍保留
    assert any("工作区间" in c for c in claims)


def test_fallback_extract_keeps_heading_and_code_filtering() -> None:
    agent = AuditAgent()
    content = (
        "# 标题\n"
        "```\nL P[2] 500mm/s CNT50\n```\n"
        "[链接文本](http://example.com)\n"
        "FANUC 控制器型号是 R-30iB。\n"
    )
    claims = agent._fallback_extract_claims(content)
    joined = "\n".join(claims)
    assert "标题" not in joined
    assert "CNT50" not in joined
    assert "example.com" not in joined
    assert any("R-30iB" in c for c in claims)


# ═══════════════════════════════════════════════════════════
# 证据清洗：_strip_doc_metadata（剥掉 KB chunk 开头的文档元数据头）
# ═══════════════════════════════════════════════════════════

_DOC_HEAD = (
    "# FANUC 示教器点位示教编程基础操作\n\n"
    "- **来源**：https://www.fanuc.co.jp/en/product/robot/teachpendant\n"
    "- **作者/机构**：FANUC Corporation\n"
    "- **日期**：2025-06-15\n"
    "- **权威等级**：A\n"
    "- **摘要**：介绍 FANUC 示教器编程流程\n\n"
    "---\n\n"
    "## 正文\n\n"
)


def test_strip_doc_metadata_removes_header() -> None:
    agent = AuditAgent()
    chunk = _DOC_HEAD + "FANUC 示教器（Teach Pendant, TP）是核心人机界面。\n"
    cleaned = agent._strip_doc_metadata(chunk)
    assert "示教器点位示教编程基础操作" not in cleaned  # 标题已剥
    assert "来源" not in cleaned and "权威等级" not in cleaned  # 元数据 bullet 已剥
    assert "正文" not in cleaned  # ## 正文 标题已剥
    assert "核心人机界面" in cleaned  # 正文保留


def test_strip_doc_metadata_keeps_body_chunk() -> None:
    # 正文 chunk（以 ### 小节标题开头）不应被误删
    agent = AuditAgent()
    chunk = "### 2. 运动指令类型\n\nFANUC 机器人支持三种基本运动指令。\n"
    assert agent._strip_doc_metadata(chunk) == chunk


def test_strip_doc_metadata_keeps_heading_without_metadata() -> None:
    # 标题后紧跟正文（非元数据 bullet）→ 视为正文，原样保留
    agent = AuditAgent()
    chunk = "# 快速上手\n\n进入手动模式前按下急停。\n"
    assert agent._strip_doc_metadata(chunk) == chunk

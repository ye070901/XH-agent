"""文档解析 + 智能分片工具。

支持的格式：.md / .txt / .pdf
智能分片策略（三级优先级）：
  1. 优先按 Markdown 标题切分（# / ## / ###）
  2. 标题下段落超长 → 按句子边界切分（。！？\n）
  3. overlap=100 字符保证上下文连贯

角色：人员4 — 知识库基础设施。
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

# ═══════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════


async def parse_file(file_path: str) -> str:
    """解析文档文件，返回纯文本内容。

    根据文件扩展名自动选择解析器：
      .md / .txt → UTF-8 直接读取
      .pdf       → pdfplumber 提取文本（降级：PyPDF2）

    Args:
        file_path: 文档文件的绝对路径。

    Returns:
        解析后的纯文本字符串。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 不支持的文件格式。
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文档不存在: {file_path}")

    suffix = path.suffix.lower()

    if suffix in (".md", ".txt"):
        return _parse_text(path)
    elif suffix == ".pdf":
        return await _parse_pdf(path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}。支持的格式: .md, .txt, .pdf")


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 100,
) -> list[dict]:
    """智能分片：Markdown 标题 → 句子边界 → overlap 衔接。

    分片策略（三级优先级）：
      1. 按 ## / ### 标题切分为逻辑段落
      2. 逻辑段落超长时，按句子边界（。！？\\n）切分
      3. 相邻 chunk 之间保留 overlap 字符的重叠，保证上下文连贯

    Args:
        text:     待分片的纯文本。
        chunk_size: 每个 chunk 的目标最大字符数（默认 512）。
        overlap:   相邻 chunk 之间的重叠字符数（默认 100）。

    Returns:
        list[dict]: 每个元素包含:
            - content:      分片文本内容
            - chunk_idx:    分片序号（从 0 开始）
            - heading_path: 该分片所属的标题路径，如 "第一章 > 1.1 概述"
            - char_count:   该分片的字符数
    """
    if not text or not text.strip():
        return []

    # ── 第一级：按 Markdown 标题切分 ──
    sections = _split_by_headings(text)

    # ── 第二/三级：每个 section 内按句子边界切分 + overlap ──
    chunks: list[dict] = []
    chunk_idx = 0

    for heading_path, section_text in sections:
        if not section_text.strip():
            continue

        if len(section_text) <= chunk_size:
            chunks.append(
                {
                    "content": section_text.strip(),
                    "chunk_idx": chunk_idx,
                    "heading_path": heading_path,
                    "char_count": len(section_text.strip()),
                }
            )
            chunk_idx += 1
        else:
            # 按句子边界切分
            sentences = _split_by_sentences(section_text)
            sub_chunks = _merge_sentences_with_overlap(sentences, chunk_size, overlap)
            for sc in sub_chunks:
                chunks.append(
                    {
                        "content": sc,
                        "chunk_idx": chunk_idx,
                        "heading_path": heading_path,
                        "char_count": len(sc),
                    }
                )
                chunk_idx += 1

    logger.info(
        f"[解析器] 分片完成: {len(chunks)} chunks (chunk_size={chunk_size}, overlap={overlap})"
    )
    return chunks


# ═══════════════════════════════════════════════════════════
# 私有：格式解析
# ═══════════════════════════════════════════════════════════


def _parse_text(path: Path) -> str:
    """读取 .md / .txt 文件，尝试 UTF-8 → GBK 降级。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning(f"[解析器] UTF-8 解码失败，尝试 GBK: {path.name}")
        try:
            return path.read_text(encoding="gbk")
        except UnicodeDecodeError:
            # 最后尝试：忽略无法解码的字符
            logger.warning(f"[解析器] GBK 也失败，使用 errors='ignore': {path.name}")
            return path.read_text(encoding="utf-8", errors="ignore")


async def _parse_pdf(path: Path) -> str:
    """解析 PDF 文件。

    优先使用 pdfplumber（中文支持更好），失败则降级 PyPDF2，
    再失败则抛出异常。
    """
    # 尝试 1：pdfplumber
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            pages: list[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            result = "\n\n".join(pages)
            if result.strip():
                logger.info(f"[解析器] pdfplumber 解析成功: {path.name} ({len(pages)} 页)")
                return result
    except ImportError:
        logger.debug("[解析器] pdfplumber 未安装，尝试 PyPDF2")
    except Exception as e:
        logger.warning(f"[解析器] pdfplumber 解析失败: {e}，尝试 PyPDF2")

    # 尝试 2：PyPDF2
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        result = "\n\n".join(pages)
        if result.strip():
            logger.info(f"[解析器] PyPDF2 解析成功: {path.name} ({len(pages)} 页)")
            return result
    except ImportError:
        logger.error("[解析器] PyPDF2 也未安装。请安装 pdfplumber 或 PyPDF2")
    except Exception as e:
        logger.error(f"[解析器] PyPDF2 解析失败: {e}")

    raise RuntimeError(
        f"无法解析 PDF 文件 '{path.name}'。"
        f"请安装 pdfplumber (`pip install pdfplumber`) 或 PyPDF2 (`pip install PyPDF2`)。"
    )


# ═══════════════════════════════════════════════════════════
# 私有：分片逻辑
# ═══════════════════════════════════════════════════════════

# 匹配 Markdown 标题行（## 标题 / ### 标题）
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# 中文句子边界 + 英文句号 + 换行
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？\.\!\?\n])\s*")


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """按 Markdown 标题切分文档，返回 [(标题路径, 段落文本), ...]。

    文档开头无标题的内容归入空标题路径 ""。
    """
    matches = list(_HEADING_PATTERN.finditer(text))

    if not matches:
        # 整个文档没有 Markdown 标题，作为一个整体
        return [("", text)]

    sections: list[tuple[str, str]] = []

    # 第一个标题之前的内容
    first_match = matches[0]
    if first_match.start() > 0:
        prefix = text[: first_match.start()].strip()
        if prefix:
            sections.append(("", prefix))

    # 按标题切分
    # 构建标题路径栈（用于追踪层级关系）
    heading_stack: list[str] = []

    for i, match in enumerate(matches):
        level = len(match.group(1))  # # 的数量
        heading_text = match.group(2).strip()

        # 更新标题栈：弹出 >= 当前层级的标题
        while heading_stack and len(heading_stack) >= level:
            heading_stack.pop()
        heading_stack.append(heading_text)

        # 构建完整标题路径
        heading_path = " > ".join(heading_stack)

        # 该标题下的内容（到下一个标题或文档末尾）
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        if content:
            sections.append((heading_path, content))

    return sections


def _split_by_sentences(text: str) -> list[str]:
    """按句子边界切分文本，返回句子列表。"""
    parts = _SENTENCE_BOUNDARY.split(text)
    # 合并分隔符到前一个句子
    sentences: list[str] = []
    for part in parts:
        stripped = part.strip()
        if stripped:
            sentences.append(stripped)
    return sentences


def _merge_sentences_with_overlap(
    sentences: list[str],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """将句子列表合并为 chunk_size 大小的块，块之间保留 overlap 字符重叠。

    策略：贪心合并，当前块累计长度超过 chunk_size 时截断，
    下一个块从前一个块末尾取 overlap 字符开始。
    """
    if not sentences:
        return []

    chunks: list[str] = []
    current = ""
    current_len = 0

    for sentence in sentences:
        if current_len + len(sentence) <= chunk_size:
            current += sentence
            current_len += len(sentence)
        else:
            # 当前块满了
            if current.strip():
                chunks.append(current.strip())

            # 新块：从前一块末尾取 overlap 字符作为上下文
            if overlap > 0 and current:
                overlap_text = current[-overlap:] if len(current) >= overlap else current
                current = overlap_text + sentence
                current_len = len(current)
            else:
                current = sentence
                current_len = len(sentence)

    # 最后一个块
    if current.strip():
        chunks.append(current.strip())

    return chunks

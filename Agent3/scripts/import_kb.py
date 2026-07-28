"""知识库批量导入脚本。

用法：
    python scripts/import_kb.py <docs_dir>                # 增量导入
    python scripts/import_kb.py <docs_dir> --reset        # 清空后重新导入
    python scripts/import_kb.py <docs_dir> --dry-run      # 预览，不入库

示例：
    python scripts/import_kb.py data/knowledge_base
    python scripts/import_kb.py data/knowledge_base --reset

角色：人员4 — 知识库基础设施。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 Python path（确保能 import backend）
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.src.knowledge.parser import parse_file
from backend.src.knowledge.store import knowledge_base

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}

# 根据文件名/目录名推断 source_level 的规则
SOURCE_LEVEL_RULES: list[tuple[str, str]] = [
    ("official", "official"),
    ("官方", "official"),
    ("community", "community"),
    ("社区", "community"),
    ("个人", "personal"),
    ("personal", "personal"),
]


def infer_metadata(file_path: Path) -> dict:
    """根据文件路径推断元数据。

    规则：
      - source_level: 路径中包含 official/官方 → official，
                      包含 community/社区 → community，
                      其他 → personal
      - reviewer: 默认为空（待人工填写）
      - code_verified: 默认为 False
    """
    path_str = str(file_path).lower()

    source_level = "personal"
    for keyword, level in SOURCE_LEVEL_RULES:
        if keyword in path_str:
            source_level = level
            break

    return {
        "source_level": source_level,
        "reviewer": "",
        "code_verified": False,
    }


def collect_files(docs_dir: Path) -> list[Path]:
    """递归扫描目录，收集所有支持的文档文件。"""
    if not docs_dir.exists():
        print(f"[Error] Directory not found: {docs_dir}")
        return []

    files: list[Path] = []
    for path in docs_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)

    # 按文件名排序，保证导入顺序一致
    files.sort(key=lambda p: p.name)
    return files


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════


async def import_directory(
    docs_dir: str,
    reset: bool = False,
    dry_run: bool = False,
) -> dict:
    """批量导入目录下的所有文档到知识库。

    Args:
        docs_dir: 文档目录路径。
        reset:    True → 无法在 ChromaDB 层清空整个 collection，
                  但会逐文档覆盖（add_document 内部先删后加）。
        dry_run:  True → 仅预览，不实际写入。

    Returns:
        dict: 导入统计
            - total_files:      发现的文件总数
            - success:          成功导入数
            - failed:           失败数
            - total_chunks:     总 chunk 数
            - details:          [{file, status, chunks, error}, ...]
    """
    docs_path = Path(docs_dir).resolve()
    files = collect_files(docs_path)

    if not files:
        print(f"[Warning] No supported files found in {docs_path}")
        print(f"  Supported formats: {', '.join(SUPPORTED_SUFFIXES)}")
        return {"total_files": 0, "success": 0, "failed": 0, "total_chunks": 0, "details": []}

    print(f"\n{'=' * 60}")
    print(f"  KB Batch Import")
    print(f"{'=' * 60}")
    print(f"  Source Dir:  {docs_path}")
    print(f"  Files:       {len(files)}")
    print(f"  Mode:        {'Preview (dry-run)' if dry_run else 'Write' + (' (reset)' if reset else ' (incremental)')}")
    print(f"  Start Time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")

    if dry_run:
        print("[Preview] Files to import:\n")
        for i, f in enumerate(files, 1):
            meta = infer_metadata(f)
            print(f"  {i:3d}. {f.name}")
            print(f"       Path: {f}")
            print(f"       source_level: {meta['source_level']}")
        print(f"\n  Total {len(files)} files (not written)")
        return {"total_files": len(files), "success": 0, "failed": 0, "total_chunks": 0, "details": []}

    # 初始化知识库
    await knowledge_base.initialize()

    # --reset：清空已有数据后重建
    if reset and knowledge_base._collection is not None:
        try:
            all_ids = knowledge_base._collection.get(include=[])["ids"]
            if all_ids:
                knowledge_base._collection.delete(ids=all_ids)
                print(f"  [reset] Cleared {len(all_ids)} existing chunks\n")
        except Exception as e:
            print(f"  [reset] Warning: Could not clear collection: {e}\n")

    success = 0
    failed = 0
    total_chunks = 0
    details: list[dict] = []

    for i, file_path in enumerate(files, 1):
        try:
            # 解析文档
            text = await parse_file(str(file_path))
            if not text or not text.strip():
                print(f"  [{i}/{len(files)}] [SKIP] {file_path.name} (empty)")
                details.append({
                    "file": file_path.name,
                    "status": "skipped",
                    "chunks": 0,
                    "error": "文件内容为空",
                })
                continue

            # 推断元数据
            metadata = infer_metadata(file_path)

            # 入库（add_document 内部自动分片）
            doc_id = file_path.stem
            chunks = await knowledge_base.add_document(
                doc_id=doc_id,
                title=file_path.stem,
                content=text,
                metadata=metadata,
            )

            chunk_count = len(chunks)
            total_chunks += chunk_count
            success += 1

            print(
                f"  [{i}/{len(files)}] [OK] {file_path.name}"
                f"  -> {chunk_count} chunks"
                f"  [{metadata['source_level']}]"
            )
            details.append({
                "file": file_path.name,
                "status": "success",
                "chunks": chunk_count,
                "error": None,
            })

        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(files)}] [FAIL] {file_path.name} -> {type(e).__name__}: {e}")
            details.append({
                "file": file_path.name,
                "status": "failed",
                "chunks": 0,
                "error": str(e),
            })

    # 最终统计
    stats = await knowledge_base.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  Import Done!")
    print(f"  Success: {success}  Failed: {failed}  Skipped: {len(files) - success - failed}")
    print(f"  Total Chunks: {total_chunks}")
    print(f"  KB Status: {stats['mode']} | {stats['total_documents']} docs | {stats['total_chunks']} chunks")
    print(f"  Source Breakdown: {stats['source_breakdown']}")
    print(f"  End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")

    return {
        "total_files": len(files),
        "success": success,
        "failed": failed,
        "total_chunks": total_chunks,
        "details": details,
    }


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════


def main() -> None:
    """命令行入口。"""
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        return

    docs_dir = args[0]
    reset = "--reset" in args
    dry_run = "--dry-run" in args

    asyncio.run(import_directory(docs_dir, reset=reset, dry_run=dry_run))


if __name__ == "__main__":
    main()

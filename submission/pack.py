"""提交包打包脚本：把代码 / 材料文档 / 测试数据 组装成题目要求的三项并列 zip。

对应题目「八、作品提交方式」：材料文档 + 软件模块(源码) + 测试数据 统一打包，
压缩包命名：<学校>—<姓名>—<作品名称>—<电话>。

用法（在项目根目录 XH-agent 下运行，用 .venv/Scripts/python.exe）：
    python submission/pack.py --dry-run        # 只看将打包的结构，不动文件、不产 zip
    python submission/pack.py --only-testdata  # 只刷新 03_测试数据（幻觉率调完重跑后执行）
    python submission/pack.py                  # 完整打包，产出最终 zip

打包结构（更清晰版，三项并列、评委顶层可见）：
    <学校>—<姓名>—<作品名称>—<电话>.zip
    ├── 01_材料文档/    方案文档 + PPT + 演示视频（从 submission/01_材料文档 原样取）
    ├── 02_软件模块/    仓库源代码导出（排除 .git/.venv/chroma 等派生文件）
    └── 03_测试数据/    submission_test_data 的副本（知识库切片 + 画像 + 输入输出示例）

注意：
- 本脚本只负责「目录结构」，不负责 ONNX 模型缓存打包（见 docs/打包方案 与记忆里解法A）。
- 幻觉率等指标尚未定稿时，别急着产最终 zip；等别人测完 → 重跑样例 → 再 pack。
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # XH-agent/
SUB = REPO / "submission"
DOC = SUB / "01_材料文档"
SOFT = SUB / "02_软件模块"
TEST = SUB / "03_测试数据"
TEST_SRC = REPO / "submission_test_data"

# ── 打包命名（提交前改成真实值）──────────────────────────────
SCHOOL = "XX大学"
AUTHOR = "张三"
TITLE = "领域知识个性化生成与多智能体协同决策系统"
PHONE = "13800000000"

# ── 仓库导出时排除的目录（相对 REPO，精确名）───────────────
EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "logs",
    "submission",
    "submission_test_data",
    ".pytest-tmp",
}
# 派生数据：ChromaDB 向量库靠 data/raw 重建，不导出
EXCLUDE_DIR_PATHS = {
    "data/chroma",
    "data/chroma.bak_过期残留_20260815",
    "backend/data/chroma",
}

EXCLUDE_SUFFIXES = {".pyc", ".log", ".coverage"}


def _excluded(rel: Path) -> bool:
    """判断仓库内某个相对路径是否应排除出导出。"""
    parts = rel.parts
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return True
    posix = rel.as_posix()
    if any(posix == d or posix.startswith(d + "/") for d in EXCLUDE_DIR_PATHS):
        return True
    if rel.suffix in EXCLUDE_SUFFIXES or rel.name in {".coverage", ".DS_Store"}:
        return True
    return False


def export_repo() -> int:
    """把仓库源代码导出到 02_软件模块/（清空后重建）。"""
    if not (REPO / "backend").exists():
        print(f"✗ 找不到 {REPO / 'backend'}，请在 XH-agent 根目录运行")
        return 2
    if SOFT.exists():
        shutil.rmtree(SOFT)
    SOFT.mkdir(parents=True)
    count = 0
    for p in REPO.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(REPO)
        if _excluded(rel):
            continue
        dest = SOFT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        count += 1
    print(f"  02_软件模块 ← 导出 {count} 个文件")
    return 0


def export_testdata() -> int:
    """把 submission_test_data 复制到 03_测试数据/（清空后重建）。"""
    if not TEST_SRC.exists():
        print(f"✗ 找不到 {TEST_SRC}")
        return 2
    if TEST.exists():
        shutil.rmtree(TEST)
    shutil.copytree(TEST_SRC, TEST)
    print(f"  03_测试数据 ← 复制 {TEST_SRC.name}")
    return 0


def make_zip() -> Path:
    name = f"{SCHOOL}—{AUTHOR}—{TITLE}—{PHONE}.zip"
    out = SUB / name
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in (DOC, SOFT, TEST):
            if not d.exists():
                print(f"  ⚠ 缺少 {d.name}，跳过")
                continue
            for f in d.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(SUB))
    print(f"  已产出 {out.name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只打印结构，不动文件")
    ap.add_argument("--only-testdata", action="store_true", help="只刷新 03_测试数据")
    args = ap.parse_args()

    DOC.mkdir(parents=True, exist_ok=True)
    SUB.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("将打包为：")
        print(f"  {SCHOOL}—{AUTHOR}—{TITLE}—{PHONE}.zip")
        print("  ├── 01_材料文档/   （方案文档 + PPT + 视频，放入 submission/01_材料文档）")
        print("  ├── 02_软件模块/   （仓库源码导出，排除 .git/.venv/chroma 等）")
        print("  └── 03_测试数据/   （submission_test_data 副本）")
        print("\n（--dry-run 未改动任何文件）")
        return 0

    if args.only_testdata:
        return export_testdata()

    rc = export_repo() or export_testdata()
    if rc:
        return rc
    make_zip()
    print("\n完成。压缩包在 submission/ 下。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

# ── 打包命名 ──────────────────────────────────────────────
# 真实姓名/电话属隐私，放本地文件 `submission/pack_config_local.py`（已 .gitignore，不进公开仓库）。
# 提交到公开仓库的 pack.py 只含占位符；本地打包时读 pack_config_local.py 得到真实命名。
try:
    from pack_config_local import SCHOOL, AUTHOR, TITLE, PHONE  # type: ignore
except ImportError:
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


def export_onnx() -> int:
    """把 ONNX embedding 模型缓存随包带上（解法 A），评委离线时放到 ~/.cache/... 即可。

    对应 store.py:76 的加载路径：~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz。
    不带上它，评委离线时 ChromaDB 内置 ONNX Embedding 会尝试联网下载失败，退化为关键词检索。
    """
    onnx_src = Path.home() / ".cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz"
    if not onnx_src.exists():
        print("  ⚠ 未找到 ONNX 模型缓存（~/.cache/chroma/.../onnx.tar.gz），跳过")
        return 0
    dest_dir = SOFT / "models"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(onnx_src, dest_dir / "onnx.tar.gz")
    mb = onnx_src.stat().st_size // (1024 * 1024)
    # 放置说明，让评委离线时知道放哪
    (dest_dir / "README.md").write_text(
        "# ONNX Embedding 模型缓存（离线必需）\n\n"
        "首次启动后端前，把本目录的 `onnx.tar.gz` 复制到以下路径：\n\n"
        "    ~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz\n\n"
        "（Windows 即 `C:\\Users\\<用户名>\\.cache\\chroma\\onnx_models\\all-MiniLM-L6-v2\\onnx.tar.gz`）\n\n"
        "不放置该文件，系统在离线环境下会退化为关键词检索（BM25），向量语义检索不可用。\n",
        encoding="utf-8",
    )
    print(f"  02_软件模块/models ← ONNX 模型缓存（{mb}MB）")
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

    rc = export_repo() or export_onnx() or export_testdata()
    if rc:
        return rc
    make_zip()
    print("\n完成。压缩包在 submission/ 下。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

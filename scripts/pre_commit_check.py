#!/usr/bin/env python3
"""XH-Agent 提交前自检脚本。

三阶段校验：
  阶段 1 — Ruff 格式化检查（自动修复 + 报告状态）
  阶段 2 — Ruff 静态代码检查（--fix 自动修复 + 残留问题报告）
  阶段 3 — 关键模块导入检测（确保包结构完整）

用法：
  python scripts/pre_commit_check.py

返回值：
  全部通过 → exit(0)
  任意失败 → exit(1)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"

# ═══════════════════════════════════════════════════════════
# 强制 UTF-8 输出（规避 Windows 终端 GBK 乱码）
# ═══════════════════════════════════════════════════════════
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass  # 非交互环境可能不支持 reconfigure，静默跳过

# ═══════════════════════════════════════════════════════════
# 子进程编码常量 —— Windows 下必须显式指定 UTF-8，
# 否则 text=True 会使用系统默认 GBK 编码导致 decode 崩溃
# ═══════════════════════════════════════════════════════════
_SUBPROCESS_KWARGS: dict = {
    "capture_output": True,
    "encoding": "utf-8",
    "errors": "replace",  # 极端情况下防 decode 崩溃
}

# ═══════════════════════════════════════════════════════════
# 待导入模块清单（阶段 3 使用）
# ═══════════════════════════════════════════════════════════
_MODULES_TO_CHECK: list[tuple[str, str]] = [
    # 核心单文件模块
    ("backend.src.config", "全局配置 Settings 单例"),
    ("backend.src.exceptions", "四层 XH 异常体系"),
    ("backend.src.schemas", "接口 Schema 定义（Pydantic 模型）"),
    # 包（含 __init__.py 的目录）
    ("backend.src.agents", "Agent 包"),
    ("backend.src.agents.base", "BaseAgent 抽象基类"),
    ("backend.src.api", "API 路由包"),
    ("backend.src.graph", "Graph 编排包"),
    ("backend.src.knowledge", "知识库包"),
    ("backend.src.llm", "LLM 客户端包"),
    ("backend.src.scheduler", "Agent 调度器包"),
    ("backend.src.quality_gate", "质量闸门包"),
    ("backend.src.quality_gate.base", "BaseGate 抽象基类"),
    ("backend.src.quality_gate.gates", "三道闸门实现"),
    ("backend.src.event_broadcast", "事件广播包"),
    ("backend.src.models", "数据模型包"),
    ("backend.src.utils", "工具函数包"),
]


def _run_ruff(args: list[str]) -> subprocess.CompletedProcess:
    """在项目根目录执行 ruff 命令，统一使用 UTF-8 编码。"""
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=str(PROJECT_ROOT),
        **_SUBPROCESS_KWARGS,
    )


def _safe_stdout(result: subprocess.CompletedProcess) -> str:
    """安全获取 subprocess 的 stdout 字符串。"""
    return (result.stdout or "").strip()


# ═══════════════════════════════════════════════════════════
# 阶段 1：Ruff 格式化
# ═══════════════════════════════════════════════════════════


def phase1_ruff_format() -> bool:
    """Ruff 格式化检查。

    先 --check 探测；需要格式化时自动执行 ruff format . 修复。
    返回值：格式化本就正确时返回 True；需要修复（已自动修复）返回 False。
    """
    print("=" * 60)
    print("  阶段 1/3：Ruff 代码格式化检查")
    print("=" * 60)

    # Step 1a：检查是否需要格式化
    check = _run_ruff(["format", "--check", "."])

    if check.returncode == 0:
        print("  ✅ Ruff 格式化检查通过（格式正确）")
        return True

    # Step 1b：自动格式化
    _run_ruff(["format", "."])
    print("  ❌ Ruff 格式化未通过（已自动修复）")
    print("  💡 提示：格式化已完成，请重新 git add 变更的文件后再次提交")
    # 打印受影响文件的前 10 行
    stdout = _safe_stdout(check)
    if stdout:
        for line in stdout.split("\n")[:10]:
            print(f"     {line}")
    return False


# ═══════════════════════════════════════════════════════════
# 阶段 2：Ruff 静态检查
# ═══════════════════════════════════════════════════════════


def phase2_ruff_check() -> bool:
    """Ruff 静态代码检查。

    先 --fix 自动修复；再次检查确认是否有不可自动修复的残留。
    返回值：无残留问题时返回 True；有不可修复问题时返回 False。
    """
    print()
    print("=" * 60)
    print("  阶段 2/3：Ruff 静态代码检查")
    print("=" * 60)

    # Step 2a：自动修复可修复的问题
    _run_ruff(["check", ".", "--fix"])

    # Step 2b：再次检查残留问题
    result = _run_ruff(["check", "."])

    if result.returncode == 0:
        print("  ✅ Ruff 静态检查通过（无残留问题）")
        return True

    # 有不可自动修复的问题
    print("  ❌ Ruff 静态检查未通过（含不可自动修复的问题）")
    stdout = _safe_stdout(result)
    if stdout:
        lines = stdout.split("\n")
        for line in lines[:30]:
            print(f"     {line}")
        if len(lines) > 30:
            print(f"     ... 共 {len(lines)} 条问题，仅显示前 30 条")
            print("     💡 在项目根目录运行 `ruff check .` 查看完整列表")
    return False


# ═══════════════════════════════════════════════════════════
# 阶段 3：关键模块导入检测
# ═══════════════════════════════════════════════════════════

# 将项目根目录加入 sys.path，使 backend.src.xxx 绝对导入路径可用
# （对应 api/main.py 中的 `from backend.src.config import settings` 风格）
sys.path.insert(0, str(PROJECT_ROOT))


def phase3_module_imports() -> bool:
    """关键模块导入检测。

    遍历 _MODULES_TO_CHECK 列表，逐一尝试 import。
    返回值：全部导入成功返回 True；任意失败返回 False。
    """
    print()
    print("=" * 60)
    print("  阶段 3/3：关键模块导入检测")
    print("=" * 60)

    all_pass = True
    passed = 0
    failed: list[str] = []

    for module_name, description in _MODULES_TO_CHECK:
        try:
            __import__(module_name)
            print(f"  ✅ {module_name:<30} {description}")
            passed += 1
        except ModuleNotFoundError as e:
            print(f"  ❌ {module_name:<30} ModuleNotFoundError: {e}")
            all_pass = False
            failed.append(module_name)
        except Exception as e:
            print(f"  ❌ {module_name:<30} {type(e).__name__}: {e}")
            all_pass = False
            failed.append(module_name)

    print()
    print(f"  结果：{passed}/{len(_MODULES_TO_CHECK)} 个模块导入成功")
    if failed:
        print(f"  失败模块：{', '.join(failed)}")
    return all_pass


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════


def main() -> None:
    """执行三阶段自检，汇总结果，返回对应的 exit code。"""
    print()
    print("╔" + "═" * 58 + "╗")
    print("║  XH-Agent  提交前自检脚本" + " " * 31 + "║")
    print("║  Ruff 格式化 → 静态检查 → 模块导入检测" + " " * 12 + "║")
    print("╚" + "═" * 58 + "╝")
    print(f"  项目根目录：{PROJECT_ROOT}")
    print()

    # 三阶段独立执行，互不阻断（一次运行看到全部问题）
    results: dict[str, bool] = {
        "format": phase1_ruff_format(),
        "lint": phase2_ruff_check(),
        "modules": phase3_module_imports(),
    }

    # ── 汇总 ──
    print()
    print("=" * 60)
    print("  自检汇总")
    print("=" * 60)
    labels = {
        "format": "Ruff 格式化检查",
        "lint": "Ruff 静态检查",
        "modules": "模块导入检测",
    }
    for key, label in labels.items():
        status = "✅ 通过" if results[key] else "❌ 失败"
        print(f"  {status}  {label}")

    all_pass = all(results.values())
    print()
    if all_pass:
        print("✅ 全部校验通过，可以提交代码！")
        sys.exit(0)
    else:
        failed_count = sum(1 for v in results.values() if not v)
        print(f"❌ {failed_count}/3 项校验失败，请修复后重新执行")
        sys.exit(1)


if __name__ == "__main__":
    main()

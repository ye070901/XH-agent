#!/usr/bin/env python3
"""XH-Agent 全局提交前自检脚本。

只做只读检查，不修改任何文件：
  - Ruff 代码规范校验（format --check + check，均不加 --fix）
  - 业务模块导入校验（backend.src.* 各子模块）

Run:
    python scripts/check_contracts.py
"""

import subprocess
import sys
from pathlib import Path

# ===================== 路径配置 =====================
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"

# Windows 控制台默认 GBK，输出 emoji 会触发 UnicodeEncodeError；统一按 UTF-8 输出兜底
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 添加仓库根目录到搜索路径，使 backend.src.* 绝对导入可解析
sys.path.insert(0, str(PROJECT_ROOT))


# 彩色输出类
class Color:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def print_green(msg: str) -> None:
    print(f"{Color.GREEN}{msg}{Color.RESET}")


def print_red(msg: str) -> None:
    print(f"{Color.RED}{msg}{Color.RESET}")


def print_yellow(msg: str) -> None:
    print(f"{Color.YELLOW}{msg}{Color.RESET}")


# Ruff 规范校验（只读）
def check_ruff() -> bool:
    print_yellow("===== 开始 Ruff 代码规范校验（只读，不修改文件） =====")
    ok = True

    fmt = subprocess.run([sys.executable, "-m", "ruff", "format", "--check", "."], cwd=PROJECT_ROOT)
    if fmt.returncode == 0:
        print_green("Ruff Format 格式检查通过")
    else:
        print_red("Ruff Format 格式检查未通过（存在未格式化文件）")
        ok = False

    ret = subprocess.run([sys.executable, "-m", "ruff", "check", "."], cwd=PROJECT_ROOT)
    if ret.returncode == 0:
        print_green("Ruff 代码规范校验通过")
    else:
        print_red("Ruff 代码规范校验未通过")
        ok = False
    return ok


# 模块导入校验
def check_modules() -> bool:
    print_yellow("===== 开始业务模块导入校验 =====")
    module_list = [
        "backend.src.scheduler",
        "backend.src.quality_gate",
        "backend.src.event_broadcast",
        "backend.src.models",
        "backend.src.utils",
    ]
    all_pass = True
    for mod in module_list:
        try:
            __import__(mod)
            print_green(f"模块 {mod} 导入成功")
        except Exception as exc:  # noqa: BLE001 缺依赖/内部引用错误等都会导致导入失败，如实报告
            print_red(f"模块 {mod} 导入失败: {exc}")
            all_pass = False
    return all_pass


def main() -> None:
    print_yellow("===== XH-Agent 全局提交前自检脚本启动 =====")
    ruff_ok = check_ruff()
    mod_ok = check_modules()
    if ruff_ok and mod_ok:
        print_green("\n✅ 全部校验通过，可以提交代码！")
        sys.exit(0)
    print_red("\n❌ 存在校验错误，请修复后重新执行！")
    sys.exit(1)


if __name__ == "__main__":
    main()

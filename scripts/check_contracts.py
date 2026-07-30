#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

# ===================== 路径配置 =====================
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"

# 调试打印路径
print(f"[DEBUG] 项目根目录: {PROJECT_ROOT}")
print(f"[DEBUG] backend/src路径: {BACKEND_SRC}")
print(f"[DEBUG] 文件夹存在? {BACKEND_SRC.exists()}")

# 添加模块搜索路径
sys.path.insert(0, str(BACKEND_SRC))


# 彩色输出类 + 完整函数定义（保证不会报未定义）
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


# Ruff 规范校验
def check_ruff() -> bool:
    print_yellow("===== 开始 Ruff 代码规范校验 =====")
    subprocess.run([sys.executable, "-m", "ruff", "format", "."], cwd=PROJECT_ROOT)
    print_green("Ruff Format 格式化完成")
    ret = subprocess.run([sys.executable, "-m", "ruff", "check", ".", "--fix"], cwd=PROJECT_ROOT)
    if ret.returncode != 0:
        print_red("Ruff 代码规范校验未通过")
        return False
    print_green("Ruff 代码规范校验全部通过")
    return True


# 模块导入校验
def check_modules() -> bool:
    print_yellow("===== 开始业务模块导入校验 =====")
    module_list = ["scheduler", "quality_gate", "event_broadcast", "models", "utils"]
    all_pass = True
    for mod in module_list:
        try:
            __import__(mod)
            print_green(f"模块 {mod} 导入成功")
        except ModuleNotFoundError:
            print_red(f"模块 {mod} 导入失败: No module named '{mod}'")
            all_pass = False
    return all_pass


def main():
    print_yellow("===== XH-Agent 全局提交前自检脚本启动 =====")
    ruff_ok = check_ruff()
    mod_ok = check_modules()
    if ruff_ok and mod_ok:
        print_green("\n✅ 全部校验通过，可以提交代码！")
        sys.exit(0)
    else:
        print_red("\n❌ 存在校验错误，请修复后重新执行！")
        sys.exit(1)


if __name__ == "__main__":
    main()

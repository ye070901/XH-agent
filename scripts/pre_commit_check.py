#!/usr/bin/env python3
from pathlib import Path
import sys
import subprocess

# 路径配置
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"

# 调试打印
print(f"[DEBUG] 项目根目录: {PROJECT_ROOT}")
print(f"[DEBUG] backend/src路径: {BACKEND_SRC}")
print(f"[DEBUG] 文件夹存在? {BACKEND_SRC.exists()}")

sys.path.insert(0, str(BACKEND_SRC))


# Ruff校验
def check_ruff() -> bool:
    print("===== 开始 Ruff 代码规范校验 =====")
    subprocess.run([sys.executable, "-m", "ruff", "format", "."], cwd=PROJECT_ROOT)
    print("Ruff Format 格式化完成")
    ret = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--fix"], cwd=PROJECT_ROOT
    )
    if ret.returncode != 0:
        print("Ruff 代码规范校验未通过")
        return False
    print("Ruff 代码规范校验全部通过")
    return True


# 模块导入校验
def check_modules() -> bool:
    print("===== 开始业务模块导入校验 =====")
    module_list = ["scheduler", "quality_gate", "event_broadcast", "models", "utils"]
    all_pass = True
    for mod in module_list:
        try:
            __import__(mod)
            print(f"模块 {mod} 导入成功")
        except ModuleNotFoundError:
            print(f"模块 {mod} 导入失败: No module named '{mod}'")
            all_pass = False
    return all_pass


def main():
    print("===== XH-Agent 全局提交前自检脚本启动 =====")
    ruff_ok = check_ruff()
    mod_ok = check_modules()
    if ruff_ok and mod_ok:
        print("\n✅ 全部校验通过，可以提交代码！")
        sys.exit(0)
    else:
        print("\n❌ 存在校验错误，请修复后重新执行！")
        sys.exit(1)


if __name__ == "__main__":
    main()

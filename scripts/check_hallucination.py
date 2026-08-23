#!/usr/bin/env python3
"""符号溯源校验 — 抓「虚构接口 / 库 / 枚举值」级幻觉（只读，不修改文件）。

对应 CLAUDE.md「防幻觉铁律」的工程侧硬约束，把「自检 Prompt」升级为确定性检查。

扫描 backend/src 下所有 .py，做两类静态校验：

  1. Import 溯源（维度6·实体编造检查，最硬核）：
       from backend.src.X import a, b   → 模块 X 存在 且 符号 a/b 在 X 顶层可导出集合中
       import backend.src.X             → 模块 X 存在
     抓到「import 了一个不存在的库/符号」这类幻觉。

  2. 枚举成员溯源（维度6·虚构枚举值检查）：
       EventType / GateVerdict / ThreeState / GateStrategy
     这四个纯 Enum 的成员访问（Enum.MEMBER）必须真实定义。
     抓到「用了 EventType.DEBATE_ROUND 但枚举里没这个成员」这类幻觉。

只读、零误报优先：宁可漏报（保守），不把「疑似」当「实锤」。

Run:
    python scripts/check_hallucination.py
Exit:
    0 = 未发现编造符号；1 = 发现疑似编造符号，请逐条复核
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ===================== 路径配置 =====================
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"

# Windows 控制台默认 GBK，统一 UTF-8 输出兜底
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(PROJECT_ROOT))

# 只溯源这 4 个纯 Enum（成员是显式赋值，静态可查、误报低）。
# 不校验 settings（pydantic 有继承/基类字段，误报高），配置项幻觉靠 Import 溯源 + 人工复核兜底。
KNOWN_ENUMS = ("EventType", "GateVerdict", "ThreeState", "GateStrategy")


# ===================== 彩色输出 =====================
class Color:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def _green(msg: str) -> None:
    print(f"{Color.GREEN}{msg}{Color.RESET}")


def _red(msg: str) -> None:
    print(f"{Color.RED}{msg}{Color.RESET}")


def _yellow(msg: str) -> None:
    print(f"{Color.YELLOW}{msg}{Color.RESET}")


# ===================== AST 工具 =====================
def _parse(file: Path) -> ast.Module | None:
    """解析文件为 AST；语法错误/编码错误返回 None（调用方自行报告）。"""
    try:
        return ast.parse(file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _top_level_exports(tree: ast.Module) -> set[str]:
    """收集模块顶层「可导出符号」：def/class/赋值目标/再导出的名字。

    覆盖 re-export 场景：`from .correction import CorrectionAgent` 会把
    CorrectionAgent 视为本模块可导出符号，避免误报。
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _enum_members(tree: ast.Module, enum_name: str) -> set[str]:
    """收集指定枚举类的成员名（class body 内的显式赋值目标）。"""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == enum_name:
            members: set[str] = set()
            for sub in node.body:
                if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            members.add(t.id)
            return members
    return set()


# ===================== 模块定位 =====================
def _module_to_files(mod_name: str) -> list[Path]:
    """把 'backend.src.scheduler.pipeline' 解析为候选文件路径（模块 or 包 __init__）。

    只处理 backend.src.* 前缀的绝对导入；其余返回空（相对导入内部一致，不做跨模块溯源）。
    """
    if not mod_name.startswith("backend.src"):
        return []
    rel = mod_name[len("backend.src"):].strip(".")
    parts = rel.split(".") if rel else []
    base = BACKEND_SRC
    for p in parts[:-1]:
        base = base / p
    last = parts[-1] if parts else None
    if last is None:
        return [BACKEND_SRC / "__init__.py"]
    return [
        base / f"{last}.py",
        base / last / "__init__.py",
    ]


# ===================== 主流程 =====================
def _collect_all_exports() -> dict[Path, set[str]]:
    """预扫描 backend/src 下所有 .py，建立 {文件路径: 顶层可导出符号}。"""
    exports: dict[Path, set[str]] = {}
    for py in BACKEND_SRC.rglob("*.py"):
        tree = _parse(py)
        if tree is not None:
            exports[py.resolve()] = _top_level_exports(tree)
    return exports


def _collect_enum_members() -> dict[str, set[str]]:
    """定位 4 个枚举类的定义文件，返回 {枚举名: 成员集合}。"""
    members: dict[str, set[str]] = {}
    for py in BACKEND_SRC.rglob("*.py"):
        tree = _parse(py)
        if tree is None:
            continue
        for enum_name in KNOWN_ENUMS:
            if enum_name not in members:
                found = _enum_members(tree, enum_name)
                if found:
                    members[enum_name] = found
    return members


def check_imports(exports: dict[Path, set[str]]) -> list[str]:
    """校验所有绝对导入（from backend.src.X import y / import backend.src.X）。"""
    problems: list[str] = []
    for py in BACKEND_SRC.rglob("*.py"):
        tree = _parse(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend.src"):
                for alias in node.names:
                    files = _module_to_files(node.module)
                    hits = [f for f in files if f.resolve() in exports]
                    if not hits:
                        problems.append(
                            f"{py.relative_to(PROJECT_ROOT)}: 模块 '{node.module}' 不存在"
                        )
                        continue
                    # 校验符号（跳过 `from x import *`）
                    if alias.name == "*":
                        continue
                    if not any(alias.name in exports[h] for h in hits):
                        problems.append(
                            f"{py.relative_to(PROJECT_ROOT)}: "
                            f"from {node.module} import '{alias.name}' — 符号不在目标模块顶层"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend.src"):
                        files = _module_to_files(alias.name)
                        if not any(f.resolve() in exports for f in files):
                            problems.append(
                                f"{py.relative_to(PROJECT_ROOT)}: 模块 '{alias.name}' 不存在"
                            )
    return problems


def check_enum_members(enum_members: dict[str, set[str]]) -> list[str]:
    """校验 4 个枚举的成员访问（Enum.MEMBER 的 MEMBER 必须已定义）。"""
    problems: list[str] = []
    for py in BACKEND_SRC.rglob("*.py"):
        tree = _parse(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            # 形如 EventType.X / GateVerdict.X 的访问，只校验第一层属性
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                name = node.value.id
                if name in KNOWN_ENUMS and name in enum_members:
                    if node.attr not in enum_members[name]:
                        problems.append(
                            f"{py.relative_to(PROJECT_ROOT)}: "
                            f"'{name}.{node.attr}' — 成员不在 {name} 枚举定义中"
                        )
    return problems


def main() -> None:
    _yellow("===== 符号溯源校验启动（只读，抓虚构接口/库/枚举值） =====")

    exports = _collect_all_exports()
    enum_members = _collect_enum_members()

    _yellow("\n[1/2] Import 溯源（from backend.src.X import y）")
    import_problems = check_imports(exports)
    if import_problems:
        for p in import_problems:
            _red(f"  ✗ {p}")
    else:
        _green("  通过：所有绝对导入的模块与符号均真实存在")

    _yellow("\n[2/2] 枚举成员溯源（EventType/GateVerdict/ThreeState/GateStrategy）")
    enum_problems = check_enum_members(enum_members)
    if enum_problems:
        for p in enum_problems:
            _red(f"  ✗ {p}")
    else:
        _green("  通过：所有枚举成员访问均已在枚举类中定义")

    total = len(import_problems) + len(enum_problems)
    if total == 0:
        _green("\n✅ 未发现编造符号。")
        sys.exit(0)
    _red(f"\n❌ 发现 {total} 处疑似编造符号，请逐条复核（可能是幻觉，也可能是 re-export 未覆盖的边界）")
    sys.exit(1)


if __name__ == "__main__":
    main()

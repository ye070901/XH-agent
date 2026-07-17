"""
接口契约自动检查脚本。

CI 会跑这个脚本，确保所有人的 Agent 实现没有违反接口契约。
如果这个脚本报错，说明你的实现和约定不一致——集成时一定会出问题。
"""
import sys
import ast
from pathlib import Path

BACKEND_SRC = Path(__file__).parent.parent / "backend" / "src"


def check_agent_has_process(agent_path: str, agent_name: str) -> list[str]:
    """检查 Agent 是否实现了 process 方法"""
    errors = []
    try:
        with open(agent_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        has_process = False
        has_async = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "process":
                has_process = True
                has_async = True
            elif isinstance(node, ast.FunctionDef) and node.name == "process":
                has_process = True

        if not has_process:
            errors.append(f"{agent_name}: 缺少 process 方法")
        if not has_async:
            errors.append(f"{agent_name}: process 方法必须是 async def")
    except Exception as e:
        errors.append(f"{agent_name}: 无法解析文件 - {e}")
    return errors


def check_agent_inherits_base(agent_path: str, agent_name: str) -> list[str]:
    """检查 Agent 是否继承 BaseAgent"""
    errors = []
    try:
        with open(agent_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        has_base_agent = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseAgent":
                        has_base_agent = True
                    elif isinstance(base, ast.Attribute) and base.attr == "BaseAgent":
                        has_base_agent = True

        if not has_base_agent:
            errors.append(f"{agent_name}: 没有继承 BaseAgent")
    except Exception as e:
        errors.append(f"{agent_name}: 无法解析文件 - {e}")
    return errors


def check_schemas_exist() -> list[str]:
    """检查 schemas.py 是否存在且完整"""
    errors = []
    schemas_path = BACKEND_SRC / "schemas.py"
    if not schemas_path.exists():
        errors.append("schemas.py 不存在！")
        return errors

    required_models = [
        "LearnerProfile", "SkillGap", "KnowledgeItem",
        "GeneratedResource", "Citation",
        "AuditReport", "HallucinationFlag", "FactCheckResult",
        "DebateRecord", "DebateRound",
        "AuditChallenge", "AgentDefense",
        "ReportResponse",
    ]
    with open(schemas_path, encoding="utf-8") as f:
        content = f.read()

    for model in required_models:
        if f"class {model}" not in content:
            errors.append(f"schemas.py 缺少 {model}")
    return errors


def check_no_sys_path_hacks() -> list[str]:
    """检查是否有人用了 sys.path.insert 的 hack"""
    errors = []
    for py_file in BACKEND_SRC.rglob("*.py"):
        with open(py_file, encoding="utf-8") as f:
            content = f.read()
        if "sys.path.insert" in content or "sys.path.append" in content:
            errors.append(f"{py_file.name}: 使用了 sys.path hack，请用正确的包导入")
    return errors


def main():
    errors = []

    # 检查 Agent
    agents = [
        (BACKEND_SRC / "agents" / "diagnosis.py", "DiagnosisAgent"),
        (BACKEND_SRC / "agents" / "generation.py", "GenerationAgent"),
        (BACKEND_SRC / "agents" / "audit.py", "AuditAgent"),
    ]
    for path, name in agents:
        if path.exists():
            errors.extend(check_agent_inherits_base(str(path), name))
            errors.extend(check_agent_has_process(str(path), name))
        else:
            errors.append(f"{name} 的文件不存在: {path}")

    # 检查 schemas
    errors.extend(check_schemas_exist())

    # 检查 sys.path hack
    errors.extend(check_no_sys_path_hacks())

    if errors:
        print("=" * 60)
        print("[FAIL] Interface contract check FAILED!")
        print("=" * 60)
        for e in errors:
            print(f"  - {e}")
        print(f"\n  {len(errors)} issues found. Must fix before merge.")
        sys.exit(1)
    else:
        print("=" * 60)
        print("[PASS] Interface contract check passed")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()

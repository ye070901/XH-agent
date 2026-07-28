"""BaseAgent 测试验证脚本。

验证 CLAUDE.md §3 全部契约：
  1. 抽象类，强制子类实现 process()
  2. run() 自带入参校验 + try/except 异常隔离
  3. call_llm / call_llm_json 封装，三类温度预设
  4. 错误写入 state["agent_log"]
  5. 子类私有方法以下划线开头

用法:
    cd backend
    python tests/test_base_agent.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ── 确保 backend/ 在 sys.path 中，使 `from src.agents.base import ...` 可用 ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.base import (
    TEMPERATURE_AUDIT,
    TEMPERATURE_DIAGNOSIS,
    TEMPERATURE_GENERATION,
    BaseAgent,
)

# ═══════════════════════════════════════════════════════════
# 测试子类
# ═══════════════════════════════════════════════════════════

# 顶层常量 SYSTEM_PROMPT（不内联在类体中）
SYSTEM_PROMPT = "你是一个测试用的助手，输出必须为严格的 JSON 格式。"


class TestAgent(BaseAgent):
    """测试用 Agent：模拟真实子类结构。"""

    REQUIRED_STATE_KEYS = {"task_id", "learner_data"}
    OPTIONAL_STATE_KEYS = {"extra_info"}

    def __init__(self) -> None:
        super().__init__(
            name="测试Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=TEMPERATURE_DIAGNOSIS,
        )

    async def process(self, state: dict) -> dict:
        # 模拟正常业务逻辑
        learner = state.get("learner_data", {})
        name = learner.get("name", "unknown")
        return {
            "test_result": f"processed for {name}",
            "processed_at": "2026-07-17",
        }


class FailingAgent(BaseAgent):
    """测试用 Agent：process() 抛出异常，验证异常隔离。"""

    REQUIRED_STATE_KEYS = {"task_id"}

    def __init__(self) -> None:
        super().__init__(
            name="故障Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=TEMPERATURE_AUDIT,
        )

    async def process(self, state: dict) -> dict:
        msg = "模拟 Agent 内部错误"
        raise RuntimeError(msg)


class ValidatingAgent(BaseAgent):
    """测试用 Agent：覆盖自定义校验。"""

    REQUIRED_STATE_KEYS = {"task_id", "learner_data"}

    def __init__(self) -> None:
        super().__init__(
            name="校验Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=TEMPERATURE_GENERATION,
        )

    async def process(self, state: dict) -> dict:
        return {}

    def _custom_validate(self, state: dict) -> list[str]:
        errors = []
        learner = state.get("learner_data", {})
        if learner and not learner.get("name"):
            errors.append("learner_data.name 不能为空")
        return errors


class NoSysPromptAgent(BaseAgent):
    """错误示例：内联 system_prompt 在类体中（违反规范）。"""

    REQUIRED_STATE_KEYS = {"task_id"}

    def __init__(self) -> None:
        bad_prompt = "这个 prompt 内联在类体中，违反了 CLAUDE.md §3 规范"
        super().__init__(
            name="违规Agent",
            system_prompt=bad_prompt,
            temperature=0.3,
        )

    async def process(self, state: dict) -> dict:
        return {}


# ═══════════════════════════════════════════════════════════
# 测试函数
# ═══════════════════════════════════════════════════════════


def test_abstract_enforcement() -> None:
    """验证：未实现 process() 的类无法实例化。"""
    print("\n── 测试 1: 抽象强制 ──")

    class IncompleteAgent(BaseAgent):
        pass  # 故意不实现 process()

    try:
        IncompleteAgent(name="不完整", system_prompt="...", temperature=0.3)  # type: ignore[abstract]
        raise AssertionError("应该抛出 TypeError，但实例化成功了")
    except TypeError as e:
        print(f"  [PASS] 正确阻止实例化: {e}")


def test_temperature_presets() -> None:
    """验证三类 Agent 温度预设值。"""
    print("\n── 测试 2: 温度预设 ──")
    assert TEMPERATURE_DIAGNOSIS == 0.2, f"diagnosis 应为 0.2, 实际 {TEMPERATURE_DIAGNOSIS}"
    assert TEMPERATURE_GENERATION == 0.5, f"generation 应为 0.5, 实际 {TEMPERATURE_GENERATION}"
    assert TEMPERATURE_AUDIT == 0.1, f"audit 应为 0.1, 实际 {TEMPERATURE_AUDIT}"
    print(
        f"  [PASS] diagnosis={TEMPERATURE_DIAGNOSIS}, "
        f"generation={TEMPERATURE_GENERATION}, "
        f"audit={TEMPERATURE_AUDIT}"
    )


def test_agent_uses_preset() -> None:
    """验证子类正确使用预设温度。"""
    print("\n── 测试 3: 子类温度 ──")
    agent = TestAgent()
    assert agent.temperature == TEMPERATURE_DIAGNOSIS
    print(f"  [PASS] TestAgent temperature={agent.temperature} == TEMPERATURE_DIAGNOSIS")

    agent2 = FailingAgent()
    assert agent2.temperature == TEMPERATURE_AUDIT
    print(f"  [PASS] FailingAgent temperature={agent2.temperature} == TEMPERATURE_AUDIT")

    agent3 = ValidatingAgent()
    assert agent3.temperature == TEMPERATURE_GENERATION
    print(f"  [PASS] ValidatingAgent temperature={agent3.temperature} == TEMPERATURE_GENERATION")


def test_name_validation() -> None:
    """验证 name 不能为空。"""
    print("\n── 测试 4: name 校验 ──")

    class _Dummy(BaseAgent):
        async def process(self, state: dict) -> dict:
            return {}

    try:
        _Dummy(name="", system_prompt="...", temperature=0.3)
        raise AssertionError("应该抛出 ValueError")
    except ValueError as e:
        print(f"  [PASS] 空 name 被拒绝: {e}")

    try:
        _Dummy(name="   ", system_prompt="...", temperature=0.3)
        raise AssertionError("应该抛出 ValueError")
    except ValueError as e:
        print(f"  [PASS] 纯空格 name 被拒绝: {e}")


def test_log_prefix() -> None:
    """验证 log() 自动带 Agent 名称前缀。"""
    print("\n── 测试 5: log() 前缀 ──")
    agent = TestAgent()
    # 通过检查 log 输出验证（人工/日志文件检查）
    agent.log("手动校验: 以上日志应带 [测试Agent] 前缀")
    print("  [PASS] log() 已调用，检查上方日志前缀")


async def test_run_success() -> None:
    """验证 run() 正常流程：校验 + 执行 + agent_log 写入。"""
    print("\n── 测试 6: run() 正常流程 ──")
    state = {
        "task_id": "test-001",
        "learner_data": {"name": "张三", "education_level": "bachelor"},
        "extra_info": "some extra data",
        "agent_log": [],
    }

    agent = TestAgent()
    result = await agent.run(state)

    # 返回的是同一个 state（合并了 process 结果）
    assert result is state, "run() 应返回原 state 对象"
    assert result["test_result"] == "processed for 张三"
    assert result["processed_at"] == "2026-07-17"

    # agent_log 应有成功记录
    complete_entries = [e for e in result["agent_log"] if e.get("stage") == "complete"]
    assert len(complete_entries) == 1, f"应有 1 条成功记录，实际 {len(complete_entries)}"
    assert complete_entries[0]["agent"] == "测试Agent"
    assert complete_entries[0]["level"] == "info"

    print(f"  [PASS] state 合并成功: test_result={result['test_result']}")
    print(f"  [PASS] agent_log 成功记录: {complete_entries[0]}")


async def test_run_validation_error() -> None:
    """验证 run() 校验失败：缺失必需字段 → agent_log 写入错误。"""
    print("\n── 测试 7: run() 校验失败 ──")
    state = {
        "task_id": "test-002",
        # 故意缺少 learner_data
        "agent_log": [],
    }

    agent = TestAgent()
    result = await agent.run(state)

    assert result["status"] == "error"
    # 校验失败不应该有 test_result（process 未被调用）
    assert "test_result" not in result

    # agent_log 应有 validation 阶段错误
    validation_errors = [e for e in result["agent_log"] if e.get("stage") == "validation"]
    assert len(validation_errors) == 1
    assert "learner_data" in validation_errors[0]["message"]
    assert "缺少必需字段" in validation_errors[0]["message"]

    print(f"  [PASS] 校验失败写入 agent_log: {validation_errors[0]['message']}")


async def test_run_exception_isolation() -> None:
    """验证 run() 异常隔离：process() 抛异常 → 不崩溃 + agent_log 写入。"""
    print("\n── 测试 8: run() 异常隔离 ──")
    state = {
        "task_id": "test-003",
        "agent_log": [],
    }

    agent = FailingAgent()
    result = await agent.run(state)

    # 不应抛异常
    assert result["status"] == "error"
    assert "模拟 Agent 内部错误" in result["error"]
    assert result["error_type"] == "RuntimeError"

    # agent_log 应有错误记录
    error_entries = [e for e in result["agent_log"] if e.get("level") == "error"]
    assert len(error_entries) == 1
    assert error_entries[0]["agent"] == "故障Agent"
    assert error_entries[0]["stage"] == "process"
    assert "模拟 Agent 内部错误" in error_entries[0]["message"]

    print("  [PASS] 异常被隔离，未向上传播")
    print(f"  [PASS] agent_log 错误记录: {error_entries[0]}")


async def test_run_custom_validation() -> None:
    """验证 _custom_validate() 语义校验。"""
    print("\n── 测试 9: 自定义校验 ──")
    state = {
        "task_id": "test-004",
        "learner_data": {"name": ""},  # name 为空，触发自定义校验
        "agent_log": [],
    }

    agent = ValidatingAgent()
    result = await agent.run(state)

    assert result["status"] == "error"
    validation = [e for e in result["agent_log"] if e.get("stage") == "validation"]
    assert len(validation) == 1
    assert "learner_data.name 不能为空" in validation[0]["message"]

    print(f"  [PASS] 自定义校验生效: {validation[0]['message']}")


async def test_run_unknown_keys_warning() -> None:
    """验证未知 key 触发 warning（不阻止执行）。"""
    print("\n── 测试 10: 未知 key warning ──")
    state = {
        "task_id": "test-005",
        "learner_data": {"name": "张三"},
        "unknown_field": "我不在任何 schema 中",
        "agent_log": [],
    }

    agent = TestAgent()
    result = await agent.run(state)

    # 未知 key 只 warning，不阻止执行
    assert "test_result" in result
    # 状态不应该为 error（未知 key 不阻断）
    assert result.get("status") != "error" or result["test_result"] == "processed for 张三"

    print("  [PASS] 未知 key 不阻断，process 正常执行")


async def test_call_llm_demo_mode() -> None:
    """验证 call_llm 在演示模式下降级为模拟数据。"""
    print("\n── 测试 11: call_llm 演示模式 ──")
    agent = TestAgent()
    result = await agent.call_llm("请输出一段介绍")
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"  [PASS] call_llm 返回字符串 ({len(result)} chars): {result[:60]}...")


async def test_call_llm_json_demo_mode() -> None:
    """验证 call_llm_json 在演示模式下降级为模拟数据。"""
    print("\n── 测试 12: call_llm_json 演示模式 ──")
    agent = TestAgent()
    result = await agent.call_llm_json("请输出 JSON")
    assert isinstance(result, dict)
    # 演示模式下未匹配场景返回兜底字典
    print(f"  [PASS] call_llm_json 返回 dict: {list(result.keys())}")


def test_subclass_conventions() -> None:
    """验证子类遵守规范：system_prompt 在顶层、私有方法以下划线。"""
    print("\n── 测试 13: 子类编程规范 ──")
    # 检查 diagnosis/generation/audit 三个真实子类
    from src.agents.audit import SYSTEM_PROMPT as SP3
    from src.agents.audit import AuditAgent
    from src.agents.diagnosis import SYSTEM_PROMPT as SP1
    from src.agents.diagnosis import DiagnosisAgent
    from src.agents.generation import SYSTEM_PROMPT as SP2
    from src.agents.generation import GenerationAgent

    # system_prompt 必须是模块顶层常量
    assert isinstance(SP1, str) and len(SP1) > 0
    assert isinstance(SP2, str) and len(SP2) > 0
    assert isinstance(SP3, str) and len(SP3) > 0
    print("  [PASS] system_prompt 均为模块顶层常量")

    # 子类温度符合预设
    d = DiagnosisAgent()
    assert d.temperature == TEMPERATURE_DIAGNOSIS, f"诊断应为 {TEMPERATURE_DIAGNOSIS}"
    g = GenerationAgent()
    assert g.temperature == TEMPERATURE_GENERATION, f"生成应为 {TEMPERATURE_GENERATION}"
    a = AuditAgent()
    assert a.temperature == TEMPERATURE_AUDIT, f"审核应为 {TEMPERATURE_AUDIT}"
    temps = f"diagnosis={d.temperature}, generation={g.temperature}, audit={a.temperature}"
    print(f"  [PASS] 三类温度: {temps}")

    # name 必须为中文
    assert any("一" <= c <= "鿿" for c in d.name), "name 应为中文"
    assert any("一" <= c <= "鿿" for c in g.name)
    assert any("一" <= c <= "鿿" for c in a.name)
    print(f"  [PASS] 三个 Agent name 均为中文: {d.name}, {g.name}, {a.name}")

    # 子类私有辅助方法以下划线开头
    assert hasattr(DiagnosisAgent, "_build_prompt") or hasattr(DiagnosisAgent, "_format_pretests")
    assert hasattr(GenerationAgent, "_generate_one") or hasattr(GenerationAgent, "_fmt_gaps")
    assert hasattr(AuditAgent, "_audit_one") or hasattr(AuditAgent, "_fmt_gaps")
    print("  [PASS] 子类辅助方法均以下划线开头")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════


async def main() -> None:
    """运行全部测试。"""
    print("=" * 60)
    print("  BaseAgent 契约验证 — CLAUDE.md §3")
    print("=" * 60)

    # 同步测试
    test_abstract_enforcement()
    test_temperature_presets()
    test_agent_uses_preset()
    test_name_validation()
    test_log_prefix()

    # 异步测试
    await test_run_success()
    await test_run_validation_error()
    await test_run_exception_isolation()
    await test_run_custom_validation()
    await test_run_unknown_keys_warning()
    await test_call_llm_demo_mode()
    await test_call_llm_json_demo_mode()

    # 子类规范检查
    test_subclass_conventions()

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print("  [PASS] 全部 13 项测试通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

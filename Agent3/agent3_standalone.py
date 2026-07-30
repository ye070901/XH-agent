"""
Agent 3: 内容审核 Agent — 项目架构独立版
══════════════════════════════════════════
完整复刻 XH-agent 项目架构：BaseAgent → Settings → loguru → LLMClient。
可直接运行，无需依赖项目目录。

架构层次：
  Settings  (全局配置，环境变量驱动)
  LLMClient (LLM 抽象层，演示/真实双模式)
  BaseAgent (Agent 基类，state 校验 + 异常隔离 + 日志)
  AuditAgent(内容审核，继承 BaseAgent)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
安装依赖
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  pip install loguru python-dotenv

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
快速开始
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python agent3_standalone.py              # 演示模式
  python agent3_standalone.py --real       # 真实 LLM
  python agent3_standalone.py --help       # 帮助

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
真实 LLM 配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  $env:LLM_API_KEY="sk-xxx"
  $env:LLM_BASE_URL="https://api.deepseek.com"
  $env:LLM_MODEL="deepseek-chat"
  python agent3_standalone.py --real
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

# ── Windows 终端 UTF-8（stdout + stderr）──
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ── loguru 配置：移除默认 handler，添加 UTF-8 handler ──
try:
    from loguru import logger

    logger.remove()  # 移除默认 stderr handler
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
        colorize=False,
    )
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════
# 1. Settings — 全局配置单例（等价于 backend.src.config.Settings）
# ═══════════════════════════════════════════════════════════════


class _MissingSentinel:
    """标记"未设置"，区别于 None / 空字符串 / False。"""

    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _MissingSentinel()


def _env_str(key: str, default: str | _MissingSentinel = _MISSING) -> str:
    val = os.getenv(key)
    if val is not None:
        return val
    if isinstance(default, _MissingSentinel):
        raise KeyError(f"环境变量 {key} 未设置且无默认值")
    return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class Settings:
    """全局配置单例 — 与 backend.src.config.Settings 接口一致。"""

    # ── LLM ──
    LLM_PROVIDER: str = _env_str("LLM_PROVIDER", "openai")
    LLM_API_KEY: str = _env_str("LLM_API_KEY", "")
    LLM_BASE_URL: str = _env_str("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = _env_str("LLM_MODEL", "gpt-4o")

    # Agent 粒度模型覆盖
    LLM_MODEL_AUDIT: str = _env_str("LLM_MODEL_AUDIT", "")

    # LLM 参数
    LLM_TIMEOUT_SECONDS: int = _env_int("LLM_TIMEOUT_SECONDS", 120)
    LLM_MAX_RETRIES: int = _env_int("LLM_MAX_RETRIES", 2)

    # 各 Agent 推荐温度
    LLM_TEMPERATURE_DIAGNOSIS: float = _env_float("LLM_TEMPERATURE_DIAGNOSIS", 0.2)
    LLM_TEMPERATURE_GENERATION: float = _env_float("LLM_TEMPERATURE_GENERATION", 0.5)
    LLM_TEMPERATURE_AUDIT: float = _env_float("LLM_TEMPERATURE_AUDIT", 0.1)

    # ── Agent ──
    AGENT_MAX_RETRIES: int = _env_int("AGENT_MAX_RETRIES", 3)
    DEBATE_MAX_ROUNDS: int = _env_int("DEBATE_MAX_ROUNDS", 3)

    @property
    def is_demo_mode(self) -> bool:
        return not bool(self.LLM_API_KEY)

    def get_model_for_agent(self, agent_name: str) -> str:
        """Agent 粒度模型覆盖，为空回退到 LLM_MODEL。"""
        mapping = {"audit": "LLM_MODEL_AUDIT", "agent3": "LLM_MODEL_AUDIT"}
        attr = mapping.get(agent_name.lower(), "")
        if attr:
            override = getattr(self, attr, "")
            if override:
                return override
        return self.LLM_MODEL

    def get_temperature_for_agent(self, agent_name: str) -> float:
        mapping = {"audit": "LLM_TEMPERATURE_AUDIT"}
        attr = mapping.get(agent_name.lower(), "")
        if attr:
            return getattr(self, attr, 0.3)
        return 0.3

    def display(self) -> str:
        lines = [
            "─" * 50,
            "  Config Summary",
            "─" * 50,
            f"  LLM Provider : {self.LLM_PROVIDER}",
            f"  LLM Model    : {self.get_model_for_agent('audit')}",
            f"  Demo Mode    : {self.is_demo_mode}",
            f"  Timeout      : {self.LLM_TIMEOUT_SECONDS}s",
            f"  Max Retries  : {self.LLM_MAX_RETRIES}",
            "─" * 50,
        ]
        return "\n".join(lines)


settings = Settings()


# ═══════════════════════════════════════════════════════════════
# 2. LLMClient — LLM 抽象层（等价于 backend.src.llm.client）
# ═══════════════════════════════════════════════════════════════


class LLMClient:
    """LLM 调用客户端。

    - API Key 为空 → 演示模式（_demo_audit）
    - API Key 非空 → 真实 OpenAI 兼容 API
    """

    def __init__(self) -> None:
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.get_model_for_agent("audit")
        self.max_retries = settings.LLM_MAX_RETRIES
        self.timeout = settings.LLM_TIMEOUT_SECONDS

    @property
    def is_demo(self) -> bool:
        return settings.is_demo_mode

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
    ) -> str:
        """调用 LLM，返回原始文本。"""
        if self.is_demo:
            # 演示模式返回模拟文本（实际不走这里，call_json 直接分派）
            return json.dumps(
                self._demo_audit(user_message),
                ensure_ascii=False,
            )

        return await self._api_call(system_prompt, user_message, temperature)

    async def call_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """调用 LLM，返回解析后的 JSON dict。解析失败返回 {}。"""
        if self.is_demo:
            return self._demo_audit(user_message)

        text = await self._api_call(system_prompt, user_message, temperature)
        return self._parse_json(text)

    async def _api_call(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """真实 API 调用 + 重试。"""
        import urllib.request

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                # 在线程池中运行同步 HTTP 调用，避免阻塞事件循环
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlopen(req, timeout=self.timeout),
                )
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(1 * (attempt + 1))

        raise last_error  # type: ignore[misc]

    def _demo_audit(self, user_message: str) -> dict[str, Any]:
        """演示模式：根据 prompt 中的 resource_index 返回模拟审核结果。"""
        m = re.search(r'"resource_index":\s*(\d+)', user_message)
        idx = int(m.group(1)) if m else -1

        scenarios = {
            0: {
                "resource_index": 0,
                "resource_type": "article",
                "verdict": "approved",
                "issues": [
                    {
                        "severity": "info",
                        "detail": "建议补充闭包的实际应用场景（如工厂函数、回调封装），帮助理解使用动机",
                    },
                ],
            },
            1: {
                "resource_index": 1,
                "resource_type": "video",
                "verdict": "needs_revision",
                "issues": [
                    {
                        "severity": "error",
                        "detail": "装饰器示例中 @timer 缺少 @functools.wraps 包装，会导致被装饰函数的 __name__ 和 __doc__ 丢失",
                    },
                    {
                        "severity": "warning",
                        "detail": "视频内容偏难（advanced），学习者当前为 intermediate，建议增加过渡性讲解",
                    },
                ],
            },
            2: {
                "resource_index": 2,
                "resource_type": "exercise",
                "verdict": "needs_revision",
                "issues": [
                    {
                        "severity": "error",
                        "detail": "useEffect 空依赖数组可能导致 missing dependency warning，且 fetchData 未处理 cleanup",
                    },
                    {
                        "severity": "warning",
                        "detail": "练习难度偏高（advanced），学习者当前为 intermediate，缺少 useState/useEffect 基础练习",
                    },
                    {
                        "severity": "info",
                        "detail": "建议先增加 useState 和 useEffect 的独立练习，再引入自定义 useLocalStorage Hook",
                    },
                ],
            },
            3: {
                "resource_index": 3,
                "resource_type": "article",
                "verdict": "approved",
                "issues": [
                    {
                        "severity": "warning",
                        "detail": "文章未覆盖诊断结果中的 critical 盲区：Python 装饰器与闭包、React Hooks 最佳实践",
                    },
                    {
                        "severity": "info",
                        "detail": "可以增加混淆矩阵和 ROC 曲线的可视化图示，帮助理解模型评估",
                    },
                ],
            },
        }
        return scenarios.get(idx, {"verdict": "approved", "issues": []})

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """容错 JSON 解析：直接 → 代码块 → 花括号提取。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {}


# 全局 LLM 客户端实例
llm = LLMClient()


# ═══════════════════════════════════════════════════════════════
# 3. BaseAgent — Agent 基类（等价于 backend.src.agents.base.BaseAgent）
# ═══════════════════════════════════════════════════════════════


class BaseAgent(ABC):
    """Agent 基类 —— 所有 Agent 的唯一父类。

    子类必须：
      1. 实现 async def process(self, state: dict) -> dict
      2. 在 __init__ 中调用 super().__init__(name=..., system_prompt=..., temperature=...)

    外部调用：
      推荐: await agent.run(state)      # 自动校验 + 错误隔离 + agent_log
      直接: await agent.process(state)  # 仅业务逻辑，无包装
    """

    REQUIRED_STATE_KEYS: set[str] = set()
    OPTIONAL_STATE_KEYS: set[str] = set()

    def __init__(self, name: str, system_prompt: str, temperature: float = 0.3) -> None:
        if not name or not name.strip():
            raise ValueError("Agent name 不能为空")
        self.name: str = name.strip()
        self.system_prompt: str = system_prompt
        self.temperature: float = temperature
        self.log(f"Agent 初始化完成 (temperature={self.temperature})")

    # ── 公开 API ──

    async def run(self, state: dict) -> dict:
        """统一入口：校验 state → 调用 process() → 错误兜底。

        自动完成 state 校验、生命周期日志、异常隔离。
        错误写入 state["agent_log"]，单个 Agent 故障不阻断系统。
        """
        state.setdefault("agent_log", [])

        # 1. 表单校验
        validation_errors = self._validate_state(state)
        if validation_errors:
            self.log(f"state 校验失败: {'; '.join(validation_errors)}")
            state["agent_log"].append(
                {
                    "agent": self.name,
                    "level": "error",
                    "stage": "validation",
                    "message": f"state 校验失败: {'; '.join(validation_errors)}",
                    "errors": validation_errors,
                }
            )
            state["status"] = "error"
            return state

        # 2. 执行 process()
        self.log("开始执行")
        try:
            result = await self.process(state)
            if not isinstance(result, dict):
                self.log(f"警告: process() 返回了 {type(result).__name__} 而非 dict，已包装")
                result = {"result": result}
            state.update(result)
            state["agent_log"].append(
                {
                    "agent": self.name,
                    "level": "info",
                    "stage": "complete",
                    "message": "执行完成",
                }
            )
            self.log("执行完成")
            return state
        except Exception as e:
            self.log(f"执行异常: {type(e).__name__}: {e}")
            state["agent_log"].append(
                {
                    "agent": self.name,
                    "level": "error",
                    "stage": "process",
                    "message": str(e),
                    "error_type": type(e).__name__,
                }
            )
            state["status"] = "error"
            state["error"] = str(e)
            state["error_type"] = type(e).__name__
            return state

    @abstractmethod
    async def process(self, state: dict) -> dict:
        """处理输入状态，返回更新后的状态字典（由 run() 合并）。"""
        ...

    # ── LLM 调用工具 ──

    async def call_llm(self, user_message: str, *, temperature: float | None = None) -> str:
        temp = temperature if temperature is not None else self.temperature
        return await llm.call(
            system_prompt=self.system_prompt,
            user_message=user_message,
            temperature=temp,
        )

    async def call_llm_json(
        self,
        user_message: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        temp = temperature if temperature is not None else self.temperature
        return await llm.call_json(
            system_prompt=self.system_prompt,
            user_message=user_message,
            temperature=temp,
        )

    # ── 日志 ──

    def log(self, message: str) -> None:
        """统一日志，自动带 [Agent名称] 前缀。"""
        try:
            from loguru import logger

            logger.info(f"[{self.name}] {message}")
        except ImportError:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] [{self.name}] {message}")

    # ── State 校验（私有）──

    def _validate_state(self, state: dict) -> list[str]:
        errors: list[str] = []
        allowed = self.REQUIRED_STATE_KEYS | self.OPTIONAL_STATE_KEYS

        missing = self.REQUIRED_STATE_KEYS - set(state.keys())
        if missing:
            errors.append(f"缺少必需字段: {', '.join(sorted(missing))}")

        if allowed:
            unknown = set(state.keys()) - allowed
            if unknown:
                try:
                    from loguru import logger

                    logger.warning(
                        f"[{self.name}] state 包含未声明的键: {', '.join(sorted(unknown))}"
                    )
                except ImportError:
                    pass

        custom = self._custom_validate(state)
        errors.extend(custom)
        return errors

    def _custom_validate(self, state: dict) -> list[str]:
        return []


# ═══════════════════════════════════════════════════════════════
# 4. SYSTEM_PROMPT — 模块顶层常量
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个严格的内容审核专家。你的任务是检查学习资源的质量，但不要修改内容。

检查清单：
1. 事实错误：API 名称对不对？概念定义准确吗？代码示例能运行吗？
2. 难度匹配：学习者的推荐难度是 X，这份内容的难度是 X 吗？有没有偏难或偏简单？
3. 盲区覆盖：学习者有 critical 和 high 优先级的知识盲区，这份内容覆盖到了吗？

审核意见分三级：
- error: 事实性错误（必须指出）
- warning: 不够好但没有错（难度偏高、遗漏某个盲区）
- info: 改进建议（可以加一道题、可以加个比喻）

输出必须为严格的 JSON 格式。"""


# ═══════════════════════════════════════════════════════════════
# 5. AuditAgent — Agent 3 实现（继承 BaseAgent）
# ═══════════════════════════════════════════════════════════════


class AuditAgent(BaseAgent):
    """内容审核 Agent — 只审不修。

    逐条审核 Agent 2 生成的每个资源，输出包含 verdict + issues 的审核报告。
    单条 LLM 调用失败不阻断整条流水线，使用兜底报告保证系统鲁棒性。
    """

    REQUIRED_STATE_KEYS = {"generated_resources", "diagnosis_result"}
    OPTIONAL_STATE_KEYS = {
        "learner_data",
        "task_id",
        "agent_log",
        "status",
        "resource_types",
    }

    def __init__(self) -> None:
        super().__init__(
            name="审核Agent",
            system_prompt=SYSTEM_PROMPT,
            temperature=settings.LLM_TEMPERATURE_AUDIT,
        )

    # ── 主流程 ──

    async def process(self, state: dict) -> dict:
        """逐条审核 generated_resources 中的每个资源。

        Returns:
            dict: {"audit_result": list[dict]}  由 BaseAgent.run() 合并到 state。
        """
        resources = state.get("generated_resources", [])
        diagnosis = state.get("diagnosis_result", {})

        if not resources:
            self.log("警告: generated_resources 为空，跳过审核")
            return {"audit_result": []}

        audit_results: list[dict] = []
        for i, resource in enumerate(resources):
            report = await self._audit_one(i, resource, diagnosis)
            audit_results.append(report)

        approved = sum(1 for r in audit_results if r.get("verdict") == "approved")
        self.log(
            f"审核完成: {len(audit_results)} 个资源 "
            f"({approved} approved, {len(audit_results) - approved} needs_revision)"
        )
        return {"audit_result": audit_results}

    # ── 单资源审核 ──

    async def _audit_one(self, index: int, resource: dict, diagnosis: dict) -> dict:
        """审核单个资源，LLM 异常时返回兜底报告。"""
        difficulty = diagnosis.get("recommended_difficulty", "beginner")
        skill_gaps = diagnosis.get("skill_gaps", [])
        critical_gaps = [g for g in skill_gaps if g.get("priority") in ("critical", "high")]

        # 安全取值：防御 None / 非字符串 / 双引号破坏 JSON 模板
        resource_type = str(resource.get("resource_type") or "").replace('"', "'")
        resource_title = str(resource.get("title") or "").replace('"', "'")
        resource_difficulty = str(resource.get("difficulty_level") or "").replace('"', "'")
        content = str(resource.get("content") or "")[:3000]

        prompt = f"""## 待审核资源
- 编号：{index}
- 类型：{resource_type}
- 标题：{resource_title}
- 资源难度：{resource_difficulty}

## 内容
{content}

## 学习者信息
- 推荐难度：{difficulty}
- 需要覆盖的关键盲区（critical/high）：
{self._fmt_gaps(critical_gaps)}

## 审核任务
请逐条检查，输出纯 JSON（不要 markdown 代码块包裹）：

{{
    "resource_index": {index},
    "resource_type": "{resource_type}",
    "verdict": "approved|needs_revision",
    "issues": [
        {{
            "severity": "error|warning|info",
            "detail": "问题描述"
        }}
    ]
}}

审核规则：
- 无任何问题 → verdict = "approved", issues = []
- 存在 error → verdict = "needs_revision"
- 仅有 warning 或 info → verdict 可以为 "approved"，但 issues 仍需列出
- 每个 issue 一句话说清楚，不要重复描述同一问题"""

        # LLM 调用 + 异常兜底（单条失败不阻断流水线）
        try:
            result = await self.call_llm_json(prompt)
        except Exception as e:
            self.log(
                f"资源 {index} ({resource_type}) LLM 调用异常 "
                f"({type(e).__name__}: {e})，使用兜底报告"
            )
            return {
                "resource_index": index,
                "resource_type": resource.get("resource_type", ""),
                "verdict": "needs_revision",
                "issues": [
                    {
                        "severity": "error",
                        "detail": f"大模型调用失败（{type(e).__name__}），无法自动审核，需人工复查",
                    }
                ],
            }

        # 防御：确保 LLM 返回值包含契约要求的全部字段
        result.setdefault("resource_index", index)
        result.setdefault("resource_type", resource.get("resource_type", ""))
        result.setdefault("verdict", "needs_revision")
        result.setdefault("issues", [])
        return result

    # ── 工具方法 ──

    def _fmt_gaps(self, gaps: list) -> str:
        """格式化关键盲区列表。最多展示 5 个，超出显式标注。"""
        if not gaps:
            return "（无 — 该学习者没有 critical/high 盲区）"

        lines: list[str] = []
        for g in gaps[:5]:
            priority = g.get("priority", "?")
            topic = g.get("topic", "") or g.get("name", "")
            lines.append(f"  - [{priority}] {topic}")

        if len(gaps) > 5:
            lines.append(f"  （...还有 {len(gaps) - 5} 个盲区未逐一列出）")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 6. 内置测试数据
# ═══════════════════════════════════════════════════════════════

SAMPLE_STATE: dict[str, Any] = {
    "generated_resources": [
        {
            "resource_type": "article",
            "title": "Python 闭包详解",
            "difficulty_level": "intermediate",
            "content": (
                "闭包（Closure）是 Python 中一个重要的概念。"
                "闭包是指在一个外部函数中定义了一个内部函数，内部函数引用了外部函数的变量，"
                "并且外部函数的返回值是内部函数。"
                "闭包可以让函数记住创建时的环境。"
                "示例：def outer(x): def inner(y): return x + y; return inner"
            ),
        },
        {
            "resource_type": "video",
            "title": "深入理解 Python 装饰器",
            "difficulty_level": "advanced",
            "content": (
                "本视频讲解 Python 装饰器的原理和用法。"
                "装饰器本质上是一个接受函数作为参数并返回新函数的可调用对象。"
                "示例代码：def timer(func): def wrapper(*args, **kwargs): "
                "start=time.time(); result=func(*args,**kwargs); "
                "print(time.time()-start); return result; return wrapper"
                "⚠️ 注意：示例中 wrapper 没有使用 @functools.wraps，"
                "这会导致被装饰函数的 __name__ 和 __doc__ 丢失。"
            ),
        },
        {
            "resource_type": "exercise",
            "title": "React Hooks 实战练习",
            "difficulty_level": "advanced",
            "content": (
                "练习 1：使用 useState 管理表单状态。"
                "练习 2：使用 useEffect 进行数据请求。"
                "示例：useEffect(() => { fetchData(); }, [])  // 依赖数组为空"
                "练习 3：自定义 useLocalStorage Hook。"
            ),
        },
        {
            "resource_type": "article",
            "title": "机器学习入门：从线性回归到神经网络",
            "difficulty_level": "beginner",
            "content": (
                "机器学习是人工智能的一个分支，通过数据和算法让计算机自动改进。"
                "监督学习：使用带标签的数据训练模型，如分类、回归任务。"
                "无监督学习：使用无标签数据发现隐藏模式，如聚类、降维。"
                "本文将从线性回归开始，逐步介绍梯度下降、逻辑回归，最终构建简单的神经网络。"
            ),
        },
    ],
    "diagnosis_result": {
        "recommended_difficulty": "intermediate",
        "learner_level": "intermediate",
        "skill_gaps": [
            {
                "priority": "critical",
                "topic": "Python 装饰器与闭包",
                "category": "advanced_syntax",
            },
            {
                "priority": "critical",
                "topic": "React Hooks 最佳实践",
                "category": "frontend",
            },
            {
                "priority": "high",
                "topic": "异步编程 async/await",
                "category": "concurrency",
            },
            {
                "priority": "high",
                "topic": "RESTful API 设计规范",
                "category": "backend",
            },
            {"priority": "medium", "topic": "Git 分支策略", "category": "tooling"},
            {"priority": "low", "topic": "Docker 基础", "category": "devops"},
        ],
    },
    "learner_data": {"name": "测试学习者", "level": "intermediate"},
    "task_id": "demo-001",
}


# ═══════════════════════════════════════════════════════════════
# 7. 命令行入口
# ═══════════════════════════════════════════════════════════════


def print_usage() -> None:
    print(__doc__)


def print_summary(state: dict) -> None:
    """从 state 中提取审核结果并打印汇总。"""
    audit_list = state.get("audit_result", [])
    if not audit_list:
        print("\n  ⚠️ 无审核结果")
        return

    approved = sum(1 for r in audit_list if r.get("verdict") == "approved")
    needs = len(audit_list) - approved
    errors = sum(1 for r in audit_list for i in r.get("issues", []) if i.get("severity") == "error")
    warnings = sum(
        1 for r in audit_list for i in r.get("issues", []) if i.get("severity") == "warning"
    )
    infos = sum(1 for r in audit_list for i in r.get("issues", []) if i.get("severity") == "info")

    print()
    print("=" * 60)
    print("  审核汇总")
    print(f"  ✅ Approved:       {approved}")
    print(f"  🔧 Needs Revision: {needs}")
    print(f"  ❌ Errors:         {errors}")
    print(f"  ⚠️  Warnings:      {warnings}")
    print(f"  💡 Infos:          {infos}")
    print("=" * 60)


async def main() -> None:
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print_usage()
        return

    # ── 真实模式检查 ──
    force_real = "--real" in args
    if force_real and settings.is_demo_mode:
        print("❌ 错误: --real 模式需要设置 LLM_API_KEY 环境变量")
        print('   PowerShell: $env:LLM_API_KEY="your-key"')
        print("   CMD:        set LLM_API_KEY=your-key")
        sys.exit(1)

    # ── 打印配置 ──
    print(settings.display())
    print(f"\n  LLM 模式: {'🎭 演示模式' if settings.is_demo_mode else '🌐 真实调用'}")
    print(f"  待审核资源: {len(SAMPLE_STATE['generated_resources'])} 个")

    # ── 创建 Agent 并通过 BaseAgent.run(state) 调用 ──
    agent = AuditAgent()
    state = await agent.run(SAMPLE_STATE)

    # ── 检查 agent_log 中的错误 ──
    for entry in state.get("agent_log", []):
        if entry.get("level") == "error":
            print(f"\n  ⚠️ agent_log 错误: {entry}")

    # ── 输出 ──
    print_summary(state)

    print()
    print("─" * 60)
    print("  详细审核报告 (JSON)")
    print("─" * 60)
    print(json.dumps(state.get("audit_result", []), ensure_ascii=False, indent=2))

    # 写入文件
    out_path = os.path.join(os.path.dirname(__file__) or ".", "audit_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(state.get("audit_result", []), f, ensure_ascii=False, indent=2)
    print(f"\n📄 报告已保存到: {out_path}")

    # 同时输出 agent_log
    print()
    print("─" * 60)
    print("  agent_log（运行日志）")
    print("─" * 60)
    for entry in state.get("agent_log", []):
        print(
            f"  [{entry.get('stage', '?')}] [{entry.get('level', '?')}] {entry.get('message', '')}"
        )


if __name__ == "__main__":
    asyncio.run(main())

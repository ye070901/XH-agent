"""事件广播模块 — 供编排器调用，向 WebSocket 推送 Agent 状态"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from ..schemas import AgentState, WSMessage


async def broadcast_agent_event(
    task_id: str,
    agent_name: str,
    state: str,
    message: str,
    data: Optional[dict] = None,
    message_type: str = "info",
    broadcast_func=None,
) -> None:
    """编排器在关键节点推送 Agent 状态到 WebSocket。

    参数:
        task_id: 任务唯一标识
        agent_name: Agent 名称（中文，如"学情诊断"）
        state: Agent 状态，AgentState 枚举值
        message: 状态描述信息
        data: 可选的附加数据（agent_log、metrics 等）
        message_type: 消息类型
            - info: 通用状态更新
            - challenge: 审核质询
            - defense: 辩护回应
            - decision: 决策结果
            - error: 错误信息
        broadcast_func: 实际的广播函数，若不传则从 ws 模块导入
    """
    if broadcast_func is None:
        try:
            from ..api.ws import broadcast_agent_event as _func
            broadcast_func = _func
        except ImportError:
            logger.warning("[Broadcast] Cannot import broadcast_func, skipping")
            return

    ws_message = WSMessage(
        task_id=task_id,
        timestamp=datetime.now(),
        agent_name=agent_name,
        agent_state=AgentState(state) if isinstance(state, str) else state,
        message=message,
        message_type=message_type,
        data=data,
    )

    try:
        await broadcast_func(task_id, ws_message.model_dump(mode="json"))
        logger.debug(f"[Broadcast] {agent_name} -> {state}: {message}")
    except Exception as e:
        logger.error(f"[Broadcast] Failed to broadcast: {e}")


def create_broadcast_wrapper(broadcast_func):
    """生成编排器可用的简化广播闭包。

    用法:
        from ..event_broadcast import create_broadcast_wrapper
        broadcast = create_broadcast_wrapper(my_broadcast_func)

        # 在 Agent 流程中调用
        await broadcast(task_id, "学情诊断", "thinking", "正在分析学习者画像...")
    """
    async def wrapper(
        task_id: str,
        agent_name: str,
        state: str,
        message: str,
        data: Optional[dict] = None,
        message_type: str = "info",
    ) -> None:
        await broadcast_agent_event(
            task_id=task_id,
            agent_name=agent_name,
            state=state,
            message=message,
            data=data,
            message_type=message_type,
            broadcast_func=broadcast_func,
        )

    return wrapper

"""WebSocket 端点 — 与 EventBus 配合，将后端事件转发给前端。

架构：
  EventBus (内存 pub/sub) → ws ConnectionManager → WebSocket 客户端

使用方式：
  ws://host/ws/task/{task_id}
  客户端订阅后自动接收该 task_id 的所有事件。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.src.event_broadcast import event_bus

router = APIRouter()


class ConnectionManager:
    """管理活跃 WebSocket 连接（用于连接状态监控）。

    事件推送由 EventBus.subscribe() 负责，本类仅追踪连接数。
    """

    def __init__(self):
        # task_id -> set[WebSocket]
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(task_id, set()).add(websocket)
        logger.info(f"[WS] Connected: task_id={task_id}, total={self.connection_count(task_id)}")

    async def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        self._connections.get(task_id, set()).discard(websocket)
        if self._connections.get(task_id) and not self._connections[task_id]:
            del self._connections[task_id]
        remaining = self.connection_count(task_id)
        logger.info(f"[WS] Disconnected: task_id={task_id}, remaining={remaining}")

    def connection_count(self, task_id: str) -> int:
        return len(self._connections.get(task_id, set()))


# 全局单例
connection_manager = ConnectionManager()


@router.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket 端点：客户端通过此连接接收任务实时状态推送。

    内部订阅 EventBus，将后端事件转发给 WebSocket 客户端。
    """
    await connection_manager.connect(websocket, task_id)

    async def forward_to_ws():
        """从 EventBus 订阅事件并转发到 WebSocket。"""
        try:
            async for event in event_bus.subscribe(task_id):
                payload = dict(event.get("data", {}))
                event_type = str(event.get("event_type", ""))
                status_map = {
                    "agent_start": "running",
                    "agent_done": "done",
                    "agent_error": "error",
                    "debate_round": "done",
                    "workflow_complete": "done",
                }
                payload.setdefault("task_id", task_id)
                payload["event_type"] = event_type
                payload["timestamp"] = event.get("timestamp")
                payload["status"] = status_map.get(event_type, payload.get("status", "running"))
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"[WS] Forward error: {e}")

    # 并行运行：转发事件 + 接收客户端消息
    forward_task = asyncio.create_task(forward_to_ws())
    # 让订阅协程先注册，避免客户端紧接着发起 HTTP 请求时遗漏首个状态事件。
    await asyncio.sleep(0)

    try:
        while True:
            # 接收客户端心跳/命令消息（目前仅用于保持连接）
            data = await websocket.receive_text()
            logger.debug(f"[WS] Client message: {data}")
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected: task_id={task_id}")
    except Exception as e:
        logger.error(f"[WS] Connection error: {e}")
    finally:
        forward_task.cancel()
        await connection_manager.disconnect(websocket, task_id)

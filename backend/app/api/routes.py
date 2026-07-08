"""FastAPI路由 — REST API + WebSocket"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import uuid
import json
import asyncio
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from loguru import logger

from ..workflow.graph import workflow_engine
from ..knowledge.rag import knowledge_base

router = APIRouter(prefix="/api/v1")

# 任务状态存储（生产环境用Redis）
task_store: dict[str, dict] = {}

# WebSocket连接管理
ws_connections: dict[str, list[WebSocket]] = {}


# ═══════════════════════════════════════════
# 学习者
# ═══════════════════════════════════════════

@router.post("/learners")
async def create_learner(data: dict):
    """创建学习者画像"""
    learner_id = uuid.uuid4().hex[:16]
    profile = {
        "learner_id": learner_id,
        "name": data.get("name", ""),
        "education": data.get("education", {}),
        "experience": data.get("experience", {}),
        "pretest_results": data.get("pretest_results", []),
        "created_at": datetime.now().isoformat(),
    }
    return {"learner_id": learner_id, "profile": profile}


@router.get("/learners/{learner_id}")
async def get_learner(learner_id: str):
    """获取学习者画像"""
    return {"learner_id": learner_id, "profile": {}}


# ═══════════════════════════════════════════
# 资源生成（异步）
# ═══════════════════════════════════════════

@router.post("/generate")
async def start_generation(data: dict, background_tasks: BackgroundTasks):
    """触发Agent协同生成资源"""
    task_id = uuid.uuid4().hex[:12]
    learner_data = data.get("learner_data", {})
    resource_types = data.get("resource_types", ["lecture", "guide", "quiz"])

    task_store[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "progress_percent": 0.0,
        "current_agent": "",
        "generated_resources": [],
        "debate_records": [],
        "error_message": None,
    }

    # 异步执行工作流
    background_tasks.add_task(_run_workflow, task_id, learner_data, resource_types)

    return {
        "task_id": task_id,
        "status": "queued",
        "estimated_seconds": 30,
    }


async def _run_workflow(task_id: str, learner_data: dict, resource_types: list[str]):
    """后台执行工作流"""
    try:
        # 更新状态
        task_store[task_id]["status"] = "running"
        await _broadcast(task_id, {
            "task_id": task_id,
            "agent_name": "system",
            "agent_state": "thinking",
            "message": "工作流启动",
        })

        # 执行
        result = workflow_engine.run(task_id, learner_data, resource_types)

        # 更新最终结果
        task_store[task_id].update({
            "status": result.get("status", "completed"),
            "progress_percent": 100.0,
            "generated_resources": result.get("final_resources", []),
            "debate_records": result.get("debate_records", []),
            "learning_path": result.get("learning_path"),
            "current_agent": "",
        })

        await _broadcast(task_id, {
            "task_id": task_id,
            "agent_name": "system",
            "agent_state": "done",
            "message": f"工作流完成, 生成{len(result.get('final_resources', []))}个资源",
        })

    except Exception as e:
        logger.error(f"[API] 工作流失败: {e}")
        task_store[task_id].update({
            "status": "failed",
            "error_message": str(e),
        })
        await _broadcast(task_id, {
            "task_id": task_id,
            "agent_name": "system",
            "agent_state": "error",
            "message": f"工作流失败: {e}",
        })


@router.get("/generate/{task_id}")
async def get_task_status(task_id: str):
    """查询生成任务进度"""
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_store[task_id]


# ═══════════════════════════════════════════
# 资源
# ═══════════════════════════════════════════

@router.get("/resources/{resource_id}")
async def get_resource(resource_id: str):
    """获取单个资源"""
    for task in task_store.values():
        for res in task.get("generated_resources", []):
            if res.get("resource_id") == resource_id:
                return res
    raise HTTPException(status_code=404, detail="资源不存在")


# ═══════════════════════════════════════════
# 答题反馈
# ═══════════════════════════════════════════

@router.post("/quiz/submit")
async def submit_quiz(data: dict):
    """提交答题并获取反馈"""
    correct_rate = data.get("correct_rate", 0.0)
    topic_breakdown = data.get("topic_breakdown", {})

    if correct_rate < 0.5:
        action, reason = "simplify", "正确率低于50%，建议降维解释"
    elif correct_rate > 0.85:
        action, reason = "advance", "正确率超过85%，建议进阶挑战"
    elif any(v < 0.3 for v in topic_breakdown.values()):
        action, reason = "regenerate", "存在知识点全错，建议重新生成该知识点资源"
    else:
        action, reason = "continue", "学习效果良好，继续当前路径"

    return {
        "action": action,
        "reason": reason,
        "correct_rate": correct_rate,
        "suggested_difficulty": "intermediate" if action in ("continue", "advance") else "beginner",
    }


# ═══════════════════════════════════════════
# 学情报告
# ═══════════════════════════════════════════

@router.get("/report/{learner_id}")
async def get_report(learner_id: str):
    """获取学情综合报告"""
    return {
        "learner_id": learner_id,
        "profile": {},
        "knowledge_radar": {},
        "skill_gap_analysis": [],
        "resource_match_curve": [],
        "learning_path": None,
        "generated_at": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════
# 知识库管理
# ═══════════════════════════════════════════

@router.post("/knowledge/upload")
async def upload_document(data: dict):
    """上传领域文档"""
    doc_id = uuid.uuid4().hex[:16]
    title = data.get("title", "未命名文档")
    content = data.get("content", "")

    chunks = await knowledge_base.add_document(doc_id, title, content)

    return {
        "doc_id": doc_id,
        "title": title,
        "chunk_count": len(chunks),
        "status": "indexed",
    }


@router.get("/knowledge/status")
async def get_knowledge_status():
    """知识库索引状态"""
    return {
        "initialized": knowledge_base._initialized,
        "collection": knowledge_base.collection_name,
        "memory_size": len(getattr(knowledge_base, "_memory_store", [])),
    }


# ═══════════════════════════════════════════
# WebSocket — Agent实时状态推送
# ═══════════════════════════════════════════

@router.websocket("/ws/agent/{task_id}")
async def websocket_agent(websocket: WebSocket, task_id: str):
    """WebSocket连接，实时推送Agent决策过程"""
    await websocket.accept()

    if task_id not in ws_connections:
        ws_connections[task_id] = []
    ws_connections[task_id].append(websocket)

    try:
        while True:
            # 保持连接，等待客户端消息（心跳）
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_connections[task_id].remove(websocket)
        if not ws_connections[task_id]:
            del ws_connections[task_id]


async def _broadcast(task_id: str, message: dict):
    """向指定任务的所有WebSocket连接广播消息"""
    connections = ws_connections.get(task_id, [])
    payload = json.dumps({
        **message,
        "type": "agent_update",
        "timestamp": datetime.now().isoformat(),
    }, ensure_ascii=False)

    dead = []
    for ws in connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)

    for ws in dead:
        connections.remove(ws)

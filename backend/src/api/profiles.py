"""Phase 3 学习者画像历史 REST API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..persistence.profile_store import ProfileStore, profile_store
from ..schemas import (
    ProfileCleanupSettings,
    ProfileCleanupSettingsUpdate,
    ProfileListResponse,
    ProfileSnapshotCreate,
    ProfileSnapshotResponse,
)

router = APIRouter(prefix="/api/profiles", tags=["learner-profiles"])


def get_profile_store() -> ProfileStore:
    """FastAPI dependency；测试可覆盖为临时 SQLite。"""

    return profile_store


StoreDependency = Annotated[ProfileStore, Depends(get_profile_store)]


@router.post(
    "",
    response_model=ProfileSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_profile(
    payload: ProfileSnapshotCreate,
    store: StoreDependency,
) -> dict:
    """仅在用户点击“认可，保存画像”后创建一份不可变历史快照。"""

    try:
        return await store.save_profile(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=ProfileListResponse)
async def list_profiles(
    store: StoreDependency,
    learner_id: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """按最近回写/保存时间倒序列出历史画像。"""

    return await store.list_profiles(learner_id=learner_id, limit=limit, offset=offset)


# 静态路由必须声明在 /{profile_id} 之前，避免 "settings" 被当成画像 ID。
@router.get("/settings/cleanup", response_model=ProfileCleanupSettings)
async def get_cleanup_settings(store: StoreDependency) -> dict:
    return await store.get_cleanup_settings()


@router.put("/settings/cleanup", response_model=ProfileCleanupSettings)
async def update_cleanup_settings(
    payload: ProfileCleanupSettingsUpdate,
    store: StoreDependency,
) -> dict:
    return await store.update_cleanup_settings(payload.model_dump(exclude_unset=True))


@router.get("/{profile_id}", response_model=ProfileSnapshotResponse)
async def get_profile(profile_id: str, store: StoreDependency) -> dict:
    item = await store.get_profile(profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return item


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str, store: StoreDependency) -> dict:
    if not await store.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return {"status": "deleted", "profile_id": profile_id}

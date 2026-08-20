"""学习者画像 SQLite 存储与每日自动清理。

同步 sqlite3 操作统一通过 ``asyncio.to_thread`` 执行，避免阻塞 FastAPI
事件循环。每次操作使用短连接并启用 WAL/busy_timeout，适合当前单机演示与
测试环境，且不引入新的数据库依赖。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from ..config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump(mode="json"))
    legacy = getattr(value, "dict", None)
    if callable(legacy):
        return dict(legacy())
    raise TypeError("profile payload must be a mapping or Pydantic model")


def _deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = value
    return result


class ProfileStore:
    """两表 SQLite repository：画像快照 + 清理配置。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        default_max_profiles: int | None = None,
        default_cleanup_time: str | None = None,
        cleanup_enabled: bool | None = None,
    ) -> None:
        self.db_path = Path(db_path or settings.PROFILE_DB_PATH).expanduser().resolve()
        self.default_max_profiles = (
            settings.PROFILE_DEFAULT_MAX_PROFILES
            if default_max_profiles is None
            else default_max_profiles
        )
        self.default_cleanup_time = (
            settings.PROFILE_DEFAULT_CLEANUP_TIME
            if default_cleanup_time is None
            else default_cleanup_time
        )
        self.cleanup_enabled = (
            settings.PROFILE_CLEANUP_ENABLED if cleanup_enabled is None else cleanup_enabled
        )
        self._initialised = False
        self._initialise_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    async def initialize(self) -> None:
        if self._initialised:
            return
        async with self._initialise_lock:
            if self._initialised:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialised = True

    def _initialize_sync(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS learner_profiles (
                    profile_id TEXT PRIMARY KEY,
                    learner_id TEXT NOT NULL,
                    name TEXT,
                    profile_json TEXT NOT NULL,
                    source_task_id TEXT,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_profiles_learner_id
                    ON learner_profiles(learner_id);
                CREATE INDEX IF NOT EXISTS idx_profiles_updated_at
                    ON learner_profiles(updated_at DESC);

                CREATE TABLE IF NOT EXISTS cleanup_config (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    max_profiles INTEGER NOT NULL CHECK(max_profiles > 0),
                    cleanup_time TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO cleanup_config
                    (singleton_id, max_profiles, cleanup_time, enabled, updated_at)
                VALUES (1, ?, ?, ?, ?)
                """,
                (
                    self.default_max_profiles,
                    self.default_cleanup_time,
                    int(self.cleanup_enabled),
                    _utc_now(),
                ),
            )

    async def save_profile(self, payload: Any) -> dict[str, Any]:
        await self.initialize()
        data = _model_dump(payload)
        learner_id = str(data.get("learner_id") or f"learner_{uuid4().hex}").strip()
        profile = data.get("profile")
        if not isinstance(profile, Mapping):
            raise ValueError("profile must be an object")
        record = {
            "profile_id": f"profile_{uuid4().hex}",
            "learner_id": learner_id,
            "name": profile.get("name") or profile.get("learner_name"),
            "profile": dict(profile),
            "source_task_id": data.get("source_task_id"),
            "label": data.get("label"),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        await asyncio.to_thread(self._insert_profile_sync, record)
        return record

    def _insert_profile_sync(self, record: Mapping[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO learner_profiles (
                    profile_id, learner_id, name, profile_json,
                    source_task_id, label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["profile_id"],
                    record["learner_id"],
                    record.get("name"),
                    json.dumps(record["profile"], ensure_ascii=False, separators=(",", ":")),
                    record.get("source_task_id"),
                    record.get("label"),
                    record["created_at"],
                    record["updated_at"],
                ),
            )

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        await self.initialize()
        return await asyncio.to_thread(self._get_profile_sync, profile_id)

    def _get_profile_sync(self, profile_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM learner_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        return self._profile_row(row) if row else None

    async def list_profiles(
        self,
        *,
        learner_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(
            self._list_profiles_sync,
            learner_id,
            limit,
            offset,
        )

    def _list_profiles_sync(
        self,
        learner_id: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        where = " WHERE learner_id = ?" if learner_id else ""
        params: tuple[Any, ...] = (learner_id,) if learner_id else ()
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM learner_profiles{where}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM learner_profiles{where}
                ORDER BY updated_at DESC, created_at DESC, profile_id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return {
            "items": [self._profile_row(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def update_profile(
        self,
        profile_id: str,
        profile_patch: Mapping[str, Any],
        *,
        replace: bool = False,
    ) -> dict[str, Any] | None:
        """供 K1 画像回写调用，并自动刷新 updated_at。"""

        await self.initialize()
        current = await self.get_profile(profile_id)
        if current is None:
            return None
        profile = (
            dict(profile_patch) if replace else _deep_merge(dict(current["profile"]), profile_patch)
        )
        updated_at = _utc_now()
        await asyncio.to_thread(self._update_profile_sync, profile_id, profile, updated_at)
        return await self.get_profile(profile_id)

    def _update_profile_sync(
        self,
        profile_id: str,
        profile: Mapping[str, Any],
        updated_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE learner_profiles
                SET profile_json = ?, name = ?, updated_at = ?
                WHERE profile_id = ?
                """,
                (
                    json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                    profile.get("name") or profile.get("learner_name"),
                    updated_at,
                    profile_id,
                ),
            )

    async def delete_profile(self, profile_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._delete_profile_sync, profile_id)

    def _delete_profile_sync(self, profile_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM learner_profiles WHERE profile_id = ?", (profile_id,)
            )
            return cursor.rowcount > 0

    async def get_cleanup_settings(self) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(self._get_cleanup_settings_sync)

    def _get_cleanup_settings_sync(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT max_profiles, cleanup_time, enabled, updated_at
                FROM cleanup_config
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("cleanup_config row is missing")
        return {
            "max_profiles": row["max_profiles"],
            "cleanup_time": row["cleanup_time"],
            "enabled": bool(row["enabled"]),
            "updated_at": row["updated_at"],
        }

    async def update_cleanup_settings(self, updates: Mapping[str, Any]) -> dict[str, Any]:
        await self.initialize()
        current = await self.get_cleanup_settings()
        max_profiles = (
            current["max_profiles"]
            if updates.get("max_profiles") is None
            else int(updates["max_profiles"])
        )
        cleanup_time = (
            current["cleanup_time"]
            if updates.get("cleanup_time") is None
            else str(updates["cleanup_time"])
        )
        enabled = current["enabled"] if updates.get("enabled") is None else bool(updates["enabled"])
        updated_at = _utc_now()
        await asyncio.to_thread(
            self._update_cleanup_settings_sync,
            max_profiles,
            cleanup_time,
            enabled,
            updated_at,
        )
        if enabled:
            await self.prune_excess(max_profiles=max_profiles)
        return await self.get_cleanup_settings()

    def _update_cleanup_settings_sync(
        self,
        max_profiles: int,
        cleanup_time: str,
        enabled: bool,
        updated_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE cleanup_config
                SET max_profiles = ?, cleanup_time = ?, enabled = ?, updated_at = ?
                WHERE singleton_id = 1
                """,
                (max_profiles, cleanup_time, int(enabled), updated_at),
            )

    async def prune_excess(self, *, max_profiles: int | None = None) -> int:
        await self.initialize()
        if max_profiles is None:
            max_profiles = int((await self.get_cleanup_settings())["max_profiles"])
        return await asyncio.to_thread(self._prune_excess_sync, max_profiles)

    def _prune_excess_sync(self, max_profiles: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM learner_profiles
                WHERE profile_id IN (
                    SELECT profile_id FROM learner_profiles
                    ORDER BY updated_at DESC, created_at DESC, profile_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (max_profiles,),
            )
            deleted = cursor.rowcount if cursor.rowcount >= 0 else 0
        if deleted:
            logger.info(
                "[ProfileStore] 自动清理 {} 条旧画像，保留最新 {} 条",
                deleted,
                max_profiles,
            )
        return deleted

    @staticmethod
    def _profile_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "profile_id": row["profile_id"],
            "learner_id": row["learner_id"],
            "name": row["name"],
            "profile": json.loads(row["profile_json"]),
            "source_task_id": row["source_task_id"],
            "label": row["label"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


class ProfileCleanupService:
    """每天固定时间按 updated_at 删除超限的最旧画像。"""

    def __init__(self, store: ProfileStore, *, poll_seconds: int | None = None) -> None:
        self.store = store
        self.poll_seconds = poll_seconds or settings.PROFILE_CLEANUP_POLL_SECONDS
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_run_date: date | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        await self.store.initialize()
        current = await self.store.get_cleanup_settings()
        if current["enabled"]:
            await self.store.prune_excess(max_profiles=current["max_profiles"])
        self._stop_event = asyncio.Event()
        self._last_run_date = None
        self._task = asyncio.create_task(self._run(), name="profile-cleanup")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except TimeoutError:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                cleanup = await self.store.get_cleanup_settings()
                now = datetime.now()
                scheduled = cleanup["cleanup_time"]
                if (
                    cleanup["enabled"]
                    and now.strftime("%H:%M") >= scheduled
                    and self._last_run_date != now.date()
                ):
                    await self.store.prune_excess(max_profiles=cleanup["max_profiles"])
                    self._last_run_date = now.date()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[ProfileStore] 后台清理失败，将在下个轮询周期重试")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass


profile_store = ProfileStore()
profile_cleanup_service = ProfileCleanupService(profile_store)

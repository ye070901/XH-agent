"""Phase 3 学习者画像持久化与 REST API 测试。"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from collections.abc import Iterator
from itertools import count

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.api.profiles import get_profile_store
from backend.src.api.profiles import router as profiles_router
from backend.src.persistence.profile_store import ProfileStore

profile_store_module = importlib.import_module("backend.src.persistence.profile_store")


@pytest.fixture(autouse=True)
def deterministic_utc_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 时钟精度可使连续保存同时；注入递增时钟避免依赖 sleep。"""

    ticks = count(1)

    def fake_utc_now() -> str:
        return f"2026-08-18T00:00:00.{next(ticks):06d}+00:00"

    monkeypatch.setattr(profile_store_module, "_utc_now", fake_utc_now)


@pytest.fixture
def profile_store(tmp_path) -> ProfileStore:
    """每个测试使用独立 SQLite，不读写项目默认数据库。"""

    return ProfileStore(
        tmp_path / "learner_profiles.db",
        default_max_profiles=100,
        default_cleanup_time="03:00",
        cleanup_enabled=True,
    )


@pytest.fixture
def profile_client(profile_store: ProfileStore) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(profiles_router)
    app.dependency_overrides[get_profile_store] = lambda: profile_store
    with TestClient(app) as client:
        yield client


def _snapshot_payload(
    learner_id: str,
    name: str,
    *,
    level: str = "初级",
) -> dict:
    return {
        "learner_id": learner_id,
        "profile": {
            "name": name,
            "difficulty_level": level,
            "knowledge_map": {
                "机器人坐标系": {
                    "level": "掌握中",
                    "evidence": ["前测答对1题"],
                }
            },
            "skill_gaps": ["安全急停链路"],
            "备注": "需要图示和中文说明",
        },
        "source_task_id": "task-测试-001",
        "label": "首次诊断",
    }


def _create_snapshot(
    client: TestClient,
    learner_id: str,
    name: str,
    *,
    level: str = "初级",
) -> dict:
    response = client.post(
        "/api/profiles",
        json=_snapshot_payload(learner_id, name, level=level),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_chinese_profile_json_survives_api_and_database_reopen(
    profile_client: TestClient,
    profile_store: ProfileStore,
) -> None:
    payload = _snapshot_payload("学习者-甲", "张三")

    created_response = profile_client.post("/api/profiles", json=payload)

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["learner_id"] == "学习者-甲"
    assert created["name"] == "张三"
    assert created["profile"] == payload["profile"]
    assert created["source_task_id"] == "task-测试-001"
    assert created["label"] == "首次诊断"

    # 新建 Store 实例重开同一数据库，证明数据不是仅留在内存中。
    reopened = ProfileStore(profile_store.db_path)
    persisted = asyncio.run(reopened.get_profile(created["profile_id"]))
    assert persisted is not None
    assert persisted["profile"] == payload["profile"]

    # 库内 JSON 保留可读中文，不会将整份画像转为 ASCII \\uXXXX。
    with sqlite3.connect(profile_store.db_path) as connection:
        raw_json = connection.execute(
            "SELECT profile_json FROM learner_profiles WHERE profile_id = ?",
            (created["profile_id"],),
        ).fetchone()[0]
    assert "张三" in raw_json
    assert "安全急停链路" in raw_json
    assert "\\u5f20\\u4e09" not in raw_json


def test_server_generates_learner_id_when_frontend_has_none(
    profile_client: TestClient,
) -> None:
    response = profile_client.post(
        "/api/profiles",
        json={"profile": {"name": "尚未分配编号的学习者"}},
    )

    assert response.status_code == 201
    assert response.json()["learner_id"].startswith("learner_")


def test_list_is_newest_first_and_supports_learner_filter_and_pagination(
    profile_client: TestClient,
) -> None:
    first = _create_snapshot(profile_client, "learner-a", "早期画像")
    second = _create_snapshot(profile_client, "learner-b", "其他学习者")
    latest = _create_snapshot(profile_client, "learner-a", "最新画像", level="中级")

    response = profile_client.get("/api/profiles", params={"limit": 2, "offset": 0})

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert [item["profile_id"] for item in page["items"]] == [
        latest["profile_id"],
        second["profile_id"],
    ]

    filtered = profile_client.get(
        "/api/profiles",
        params={"learner_id": "learner-a", "limit": 10},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert [item["profile_id"] for item in filtered.json()["items"]] == [
        latest["profile_id"],
        first["profile_id"],
    ]


def test_detail_not_found_and_delete_semantics(profile_client: TestClient) -> None:
    created = _create_snapshot(profile_client, "learner-delete", "待删除画像")
    profile_id = created["profile_id"]

    detail = profile_client.get(f"/api/profiles/{profile_id}")
    assert detail.status_code == 200
    assert detail.json() == created

    missing = profile_client.get("/api/profiles/profile-does-not-exist")
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"].lower()

    deleted = profile_client.delete(f"/api/profiles/{profile_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "profile_id": profile_id}
    assert profile_client.get(f"/api/profiles/{profile_id}").status_code == 404
    assert profile_client.delete(f"/api/profiles/{profile_id}").status_code == 404


def test_cleanup_settings_validation_and_immediate_pruning(
    profile_client: TestClient,
) -> None:
    oldest = _create_snapshot(profile_client, "cleanup-1", "画像1")
    middle = _create_snapshot(profile_client, "cleanup-2", "画像2")
    newest = _create_snapshot(profile_client, "cleanup-3", "画像3")

    initial = profile_client.get("/api/profiles/settings/cleanup")
    assert initial.status_code == 200
    assert initial.json()["max_profiles"] == 100
    assert initial.json()["cleanup_time"] == "03:00"
    assert initial.json()["enabled"] is True

    updated = profile_client.put(
        "/api/profiles/settings/cleanup",
        json={"max_profiles": 2, "cleanup_time": "04:30", "enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["max_profiles"] == 2
    assert updated.json()["cleanup_time"] == "04:30"
    assert updated.json()["enabled"] is True

    remaining = profile_client.get("/api/profiles").json()
    assert remaining["total"] == 2
    assert [item["profile_id"] for item in remaining["items"]] == [
        newest["profile_id"],
        middle["profile_id"],
    ]
    assert profile_client.get(f"/api/profiles/{oldest['profile_id']}").status_code == 404

    invalid_time = profile_client.put(
        "/api/profiles/settings/cleanup",
        json={"cleanup_time": "24:01"},
    )
    assert invalid_time.status_code == 422
    invalid_limit = profile_client.put(
        "/api/profiles/settings/cleanup",
        json={"max_profiles": 0},
    )
    assert invalid_limit.status_code == 422


@pytest.mark.asyncio
async def test_k1_internal_update_deep_merges_and_refreshes_updated_at(
    profile_store: ProfileStore,
) -> None:
    original = await profile_store.save_profile(_snapshot_payload("learner-k1", "K1回写对象"))
    other = await profile_store.save_profile(_snapshot_payload("learner-other", "后创建画像"))

    updated = await profile_store.update_profile(
        original["profile_id"],
        {
            "knowledge_map": {
                "机器人坐标系": {
                    "evidence": ["追问答对", "实操验证通过"],
                    "confidence": 0.93,
                }
            },
            "skill_gaps": ["ROS2/Gazebo仿真"],
        },
    )

    assert updated is not None
    assert updated["updated_at"] > original["updated_at"]
    assert updated["profile"]["name"] == "K1回写对象"
    coordinates = updated["profile"]["knowledge_map"]["机器人坐标系"]
    assert coordinates["level"] == "掌握中"
    assert coordinates["confidence"] == 0.93
    assert coordinates["evidence"] == ["追问答对", "实操验证通过"]
    assert updated["profile"]["skill_gaps"] == ["ROS2/Gazebo仿真"]

    listing = await profile_store.list_profiles()
    assert [item["profile_id"] for item in listing["items"]][:2] == [
        original["profile_id"],
        other["profile_id"],
    ]


def _route_keys(app: FastAPI) -> set[tuple[str, str]]:
    """收集全部路由键，递归展开 FastAPI 0.115+ 的惰性 _IncludedRouter。"""
    keys: set[tuple[str, str]] = set()

    def visit(routes) -> None:
        for route in routes:
            nested = getattr(route, "original_router", None)
            if nested is not None:
                visit(nested.routes)
                continue
            for method in getattr(route, "methods", set()):
                keys.add((route.path, method))

    visit(app.routes)
    return keys


@pytest.mark.parametrize(
    "module_name",
    ["main", "backend.src.api.main"],
)
def test_both_fastapi_entries_register_profile_and_pretest_routes(
    module_name: str,
) -> None:
    app = importlib.import_module(module_name).app
    routes = _route_keys(app)

    expected = {
        ("/api/profiles", "POST"),
        ("/api/profiles", "GET"),
        ("/api/profiles/settings/cleanup", "GET"),
        ("/api/profiles/settings/cleanup", "PUT"),
        ("/api/profiles/{profile_id}", "GET"),
        ("/api/profiles/{profile_id}", "DELETE"),
        ("/api/pretests/questions", "GET"),
        ("/api/pretests/score", "POST"),
    }
    assert expected <= routes

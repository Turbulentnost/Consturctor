from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def com_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_com.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_outlook_launch_calendar_list_get_close(com_client: TestClient) -> None:
    launch = com_client.post(
        "/api/v1/tools/com.outlook.launch/invoke",
        json={"payload": {"visible": False}},
    )
    assert launch.status_code == 200
    assert launch.json()["ok"] is True
    session_id = launch.json()["data"]["session_id"]
    assert session_id
    assert launch.json()["data"]["source"] == "stub"

    listing = com_client.post(
        "/api/v1/tools/com.outlook.calendar_list/invoke",
        json={"payload": {"session_id": session_id, "days": 7, "limit": 10}},
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["ok"] is True
    assert body["data"]["count"] >= 1
    events = body["data"]["events"]
    assert events[0]["subject"]
    entry_id = events[0]["entry_id"]

    detail = com_client.post(
        "/api/v1/tools/com.outlook.calendar_get/invoke",
        json={"payload": {"session_id": session_id, "entry_id": entry_id}},
    )
    assert detail.status_code == 200
    assert detail.json()["ok"] is True
    assert detail.json()["data"]["event"]["entry_id"] == entry_id

    closed = com_client.post(
        "/api/v1/tools/com.outlook.close/invoke",
        json={"payload": {"session_id": session_id, "quit": False}},
    )
    assert closed.status_code == 200
    assert closed.json()["ok"] is True


def test_outlook_calendar_list_query_filter(com_client: TestClient) -> None:
    listing = com_client.post(
        "/api/v1/tools/com.outlook.calendar_list/invoke",
        json={"payload": {"days": 7, "query": "планерка"}},
    )
    assert listing.status_code == 200
    data = listing.json()["data"]
    assert data["count"] >= 1
    assert any("планерка" in e["subject"].lower() for e in data["events"])


def test_outlook_calendar_get_missing(com_client: TestClient) -> None:
    response = com_client.post(
        "/api/v1/tools/com.outlook.calendar_get/invoke",
        json={"payload": {"entry_id": "missing-id"}},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "not found" in (response.json().get("error") or "").lower()

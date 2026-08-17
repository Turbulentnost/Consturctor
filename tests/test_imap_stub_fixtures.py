from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def imap_client(monkeypatch):
    # Even with credentials present, USE_STUBS=true must serve fixtures.
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("IMAP_HOST", "mail.example.test")
    monkeypatch.setenv("IMAP_USERNAME", "user")
    monkeypatch.setenv("IMAP_PASSWORD", "pass")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_imap.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_stub_list_unread_omto(imap_client: TestClient) -> None:
    response = imap_client.post(
        "/api/v1/tools/imap.list_unread/invoke",
        json={"payload": {"user": "omto", "limit": 3}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["mode"] == "stub"
    assert data["data"]["uids"] == [8801, 8802, 8803]


def test_stub_search_and_fetch_8801(imap_client: TestClient) -> None:
    search = imap_client.post(
        "/api/v1/tools/imap.search/invoke",
        json={"payload": {"user": "omto", "query": "omto", "limit": 3}},
    )
    assert search.status_code == 200
    assert search.json()["data"]["uids"][0] == 8801

    fetch = imap_client.post(
        "/api/v1/tools/imap.fetch_message/invoke",
        json={"payload": {"uid": 8801, "user": "omto"}},
    )
    assert fetch.status_code == 200
    body = fetch.json()
    assert body["ok"] is True
    assert body["data"]["mode"] == "stub"
    assert "спецификац" in body["data"]["body_text"].lower() or "спецификац" in body["data"]["subject"].lower()


def test_stub_fetch_missing_uid(imap_client: TestClient) -> None:
    response = imap_client.post(
        "/api/v1/tools/imap.fetch_message/invoke",
        json={"payload": {"uid": 1, "user": "omto"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "UID_NOT_FOUND: 1" in (data.get("error") or "")

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def imap_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("IMAP_USERNAME", raising=False)
    monkeypatch.delenv("IMAP_PASSWORD", raising=False)
    module = importlib.import_module("platform_tool_imap.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_imap_search_any_user_not_stub_summary(imap_client: TestClient) -> None:
    response = imap_client.post(
        "/api/v1/tools/imap.search/invoke",
        json={"payload": {"query": "td_ceh", "user": "td_ceh", "limit": 3}},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "stub search" not in data["summary"].lower()
    assert len(data["uids"]) == 3
    assert data["user"] == "td_ceh"


def test_imap_fetch_message_matches_user(imap_client: TestClient) -> None:
    search = imap_client.post(
        "/api/v1/tools/imap.search/invoke",
        json={"payload": {"user": "td_ceh", "limit": 1}},
    ).json()["data"]
    uid = search["uids"][0]
    fetch = imap_client.post(
        "/api/v1/tools/imap.fetch_message/invoke",
        json={"payload": {"uid": uid, "user": "td_ceh"}},
    )
    body = fetch.json()["data"]
    assert "stub subject" not in body["subject"].lower()
    assert "td_ceh" in body["from"].lower() or "td_ceh" in body["subject"].lower()

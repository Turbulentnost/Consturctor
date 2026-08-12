from __future__ import annotations

import importlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def browser_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_browser.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_browser_session_navigate_click_extract_close(browser_client: TestClient) -> None:
    run_id = str(uuid4())

    opened = browser_client.post(
        "/api/v1/tools/browser.open_session/invoke",
        json={"run_id": run_id, "payload": {}},
    )
    assert opened.status_code == 200
    assert opened.json()["ok"] is True

    nav = browser_client.post(
        "/api/v1/tools/browser.navigate/invoke",
        json={"run_id": run_id, "payload": {"url": "https://example.com"}},
    )
    assert nav.status_code == 200
    assert nav.json()["ok"] is True
    assert nav.json()["data"]["title"] == "Stub Page"

    snap = browser_client.post(
        "/api/v1/tools/browser.snapshot/invoke",
        json={"run_id": run_id, "payload": {}},
    )
    assert snap.status_code == 200
    elements = snap.json()["data"]["elements"]
    assert len(elements) >= 1
    ref = elements[0]["ref"]

    click = browser_client.post(
        "/api/v1/tools/browser.click/invoke",
        json={"run_id": run_id, "payload": {"ref": ref}},
    )
    assert click.status_code == 200
    assert click.json()["ok"] is True
    # Same session URL retained (no forced re-goto to blank)
    assert "example.com" in (click.json()["data"].get("url") or "")

    typed = browser_client.post(
        "/api/v1/tools/browser.type/invoke",
        json={"run_id": run_id, "payload": {"selector": "#q", "text": "hello"}},
    )
    assert typed.status_code == 200
    assert typed.json()["ok"] is True

    text = browser_client.post(
        "/api/v1/tools/browser.extract_text/invoke",
        json={"run_id": run_id, "payload": {}},
    )
    assert text.status_code == 200
    assert text.json()["ok"] is True
    assert text.json()["data"].get("text")

    closed = browser_client.post(
        "/api/v1/tools/browser.close_session/invoke",
        json={"run_id": run_id, "payload": {}},
    )
    assert closed.status_code == 200
    assert closed.json()["data"]["closed"] is True

    again = browser_client.post(
        "/api/v1/tools/browser.snapshot/invoke",
        json={"run_id": run_id, "payload": {}},
    )
    assert again.status_code == 200
    assert again.json()["ok"] is False
    assert "SESSION_NOT_FOUND" in (again.json().get("error") or "")


def test_browser_stub_navigate_still_works(browser_client: TestClient) -> None:
    response = browser_client.post(
        "/api/v1/tools/browser.navigate/invoke",
        json={"payload": {"url": "https://example.com"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["title"] == "Stub Page"

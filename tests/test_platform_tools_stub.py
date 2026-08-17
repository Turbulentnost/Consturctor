from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def shell_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_shell.main")
    importlib.reload(module)
    return TestClient(module.app)


@pytest.fixture
def browser_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_browser.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_shell_health(shell_client: TestClient) -> None:
    response = shell_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_shell_stub_invoke(shell_client: TestClient) -> None:
    response = shell_client.post(
        "/api/v1/tools/shell.run/invoke",
        json={"payload": {"command": "echo hello"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "hello" in data["data"]["stdout"]
    assert data["data"]["exit_code"] == 0
    assert "stub stdout" not in data["data"]["stdout"].lower()


def test_shell_compound_command(shell_client: TestClient) -> None:
    response = shell_client.post(
        "/api/v1/tools/shell.run/invoke",
        json={"payload": {"command": "cd incoming || ls"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["exit_code"] == 0


def test_browser_stub_navigate(browser_client: TestClient) -> None:
    response = browser_client.post(
        "/api/v1/tools/browser.navigate/invoke",
        json={"payload": {"url": "https://example.com"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["title"] == "Stub Page"

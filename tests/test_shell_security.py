from __future__ import annotations

import importlib

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
def native_shell_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_shell.native_main")
    importlib.reload(module)
    return TestClient(module.app)


@pytest.mark.parametrize(
    ("command",),
    [
        ("powershell -Command Write-Host hi",),
        ("pwsh -c echo hi",),
        ("echo run.ps1",),
    ],
)
def test_shell_blocks_powershell(shell_client: TestClient, command: str) -> None:
    response = shell_client.post(
        "/api/v1/tools/shell.run/invoke",
        json={"payload": {"command": command}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "forbidden" in (data.get("error") or "").lower()


@pytest.mark.parametrize(
    ("command",),
    [
        ("powershell -Command Write-Host hi",),
        ("pwsh -c echo hi",),
    ],
)
def test_native_shell_blocks_powershell(native_shell_client: TestClient, command: str) -> None:
    response = native_shell_client.post(
        "/api/v1/tools/shell.run/invoke",
        json={"payload": {"command": command}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "forbidden" in (data.get("error") or "").lower()

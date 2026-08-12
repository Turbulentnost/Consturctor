from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def launcher_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSTRUCTOR_ROOT", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / "data" / "filesystem").mkdir(parents=True)
    module = importlib.import_module("platform_desktop_launcher.main")
    importlib.reload(module)
    return TestClient(module.app), module


def test_launcher_health(launcher_client) -> None:
    client, _module = launcher_client
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "platform-desktop-launcher"
    assert "7830" in data["desktop_ports"]


def test_launcher_ensure_already_up(launcher_client, monkeypatch) -> None:
    client, _module = launcher_client
    import platform_desktop_launcher.spawn as spawn_mod

    monkeypatch.setattr(spawn_mod, "port_open", lambda port, host="127.0.0.1", timeout=0.4: True)
    response = client.post("/api/v1/ensure", json={"tool_name": "com.list_apps"})
    assert response.status_code == 200
    assert response.json()["started"] is False

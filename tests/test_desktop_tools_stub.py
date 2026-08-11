from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fs_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_filesystem.main")
    importlib.reload(module)
    return TestClient(module.app)


@pytest.fixture
def com_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_com.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_fs_list_stub(fs_client: TestClient) -> None:
    response = fs_client.post(
        "/api/v1/tools/fs.list/invoke",
        json={"payload": {"path": "."}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["data"]["entries"]) >= 1


def test_fs_read_stub(fs_client: TestClient) -> None:
    response = fs_client.post(
        "/api/v1/tools/fs.read/invoke",
        json={"payload": {"path": "README.txt"}},
    )
    assert response.status_code == 200
    assert "Constructor" in response.json()["data"]["content"]


def test_com_connect_invoke_stub(com_client: TestClient) -> None:
    connect = com_client.post(
        "/api/v1/tools/com.connect/invoke",
        json={"payload": {"app": "onec"}},
    )
    assert connect.status_code == 200
    session_id = connect.json()["data"]["session_id"]
    invoke = com_client.post(
        "/api/v1/tools/com.invoke/invoke",
        json={"payload": {"session_id": session_id, "method": "Connect", "args": []}},
    )
    assert invoke.status_code == 200
    assert invoke.json()["data"]["result"]["stub"] is True


def test_fs_path_traversal_blocked(fs_client: TestClient) -> None:
    module = importlib.import_module("platform_tool_filesystem.main")
    with pytest.raises(ValueError, match="not allowed"):
        module._resolve_allowed("../../etc/passwd")

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


@pytest.fixture
def fs_real_client(monkeypatch, tmp_path):
    allow_root = tmp_path / "workspace"
    allow_root.mkdir()
    monkeypatch.setenv("USE_STUBS", "false")
    monkeypatch.setenv("FS_ROOT_ALLOWLIST", str(allow_root))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_filesystem.main")
    importlib.reload(module)
    return TestClient(module.app), allow_root


def test_fs_list_rejects_path_outside_allowlist(fs_real_client) -> None:
    client, _allow_root = fs_real_client
    response = client.post(
        "/api/v1/tools/fs.list/invoke",
        json={"payload": {"path": "C:\\outside\\secret"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "not allowed" in (data.get("error") or "")


def test_fs_list_allowed_root(fs_real_client) -> None:
    client, allow_root = fs_real_client
    (allow_root / "note.txt").write_text("ok", encoding="utf-8")
    response = client.post(
        "/api/v1/tools/fs.list/invoke",
        json={"payload": {"path": str(allow_root)}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert any(entry["path"].endswith("note.txt") for entry in data["data"]["entries"])

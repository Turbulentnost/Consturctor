from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fs_client(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "out"
    workspace.mkdir()
    output.mkdir()
    monkeypatch.setenv("USE_STUBS", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("FS_ROOT_ALLOWLIST", f"{workspace},{output}")
    module = importlib.import_module("platform_tool_filesystem.main")
    importlib.reload(module)
    return TestClient(module.app), output


def test_build_office_file_custom_xlsx_path(fs_client) -> None:
    client, output = fs_client
    target = output / "custom" / "report.xlsx"
    response = client.post(
        "/api/v1/tools/fs.build_office_file/invoke",
        json={
            "payload": {
                "path": str(target),
                "format": "xlsx",
                "title": "Custom report",
                "rows": [["A", "B"], ["1", "2"]],
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["format"] == "xlsx"
    assert target.is_file()
    assert target.stat().st_size > 0

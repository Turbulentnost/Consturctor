from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from platform_tool_filesystem.agent_build_files import default_test_payloads


@pytest.fixture
def fs_client(monkeypatch, tmp_path: Path):
    allow = tmp_path / "workspace"
    output = tmp_path / "Public" / "Documents"
    allow.mkdir()
    output.mkdir(parents=True)
    monkeypatch.setenv("USE_STUBS", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("AGENT_BUILD_OUTPUT_DIR", str(output))
    monkeypatch.setenv("FS_ROOT_ALLOWLIST", f"{allow},{output}")
    module = importlib.import_module("platform_tool_filesystem.main")
    importlib.reload(module)
    return TestClient(module.app), output


def test_agent_test_files_via_fs_write(fs_client) -> None:
    client, output = fs_client
    docx_payload, xlsx_payload, _folder = default_test_payloads(output_dir=output)

    docx = client.post("/api/v1/tools/fs.write/invoke", json={"payload": docx_payload})
    assert docx.status_code == 200
    assert docx.json()["ok"] is True

    xlsx = client.post("/api/v1/tools/fs.write/invoke", json={"payload": xlsx_payload})
    assert xlsx.status_code == 200
    assert xlsx.json()["ok"] is True

    docx_path = Path(docx_payload["path"])
    xlsx_path = Path(xlsx_payload["path"])
    assert docx_path.is_file()
    assert xlsx_path.is_file()

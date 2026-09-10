from __future__ import annotations

import base64

from app.tools.host import _materialize_downloaded_artifact
from app.tools.server_tools import canonical_server_tool_name


def test_canonical_download_artifact_aliases() -> None:
    assert canonical_server_tool_name("onec.download_artifact") == "onec.download_artifact"
    assert canonical_server_tool_name("onecdownload_artifact") == "onec.download_artifact"
    assert canonical_server_tool_name("onec_download_artifact") == "onec.download_artifact"
    assert canonical_server_tool_name("web_search") == "web_search"


def test_materialize_writes_local_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "tempfile.gettempdir",
        lambda: str(tmp_path),
    )
    payload = b"hello-artifact"
    result = _materialize_downloaded_artifact(
        {
            "filename": "note.txt",
            "file_id": "11111111-1111-1111-1111-111111111111",
            "content_base64": base64.b64encode(payload).decode("ascii"),
        }
    )
    assert result["path"].endswith("note.txt")
    assert result["result_file"] == result["path"]
    assert "content_base64" not in result


def test_materialize_fetches_when_base64_omitted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    def fake_bytes(method, path, timeout=30.0):
        assert method == "GET"
        assert path.endswith("/onec-artifacts/11111111-1111-1111-1111-111111111111")
        return b"from-url"

    monkeypatch.setattr("app.tools.runtime_api.request_bytes", fake_bytes)
    result = _materialize_downloaded_artifact(
        {
            "filename": "scan.pdf",
            "file_id": "11111111-1111-1111-1111-111111111111",
            "content_url": "/api/v1/tools/onec-artifacts/11111111-1111-1111-1111-111111111111",
            "content_omitted": True,
        }
    )
    assert result["path"].endswith("scan.pdf")
    assert open(result["path"], "rb").read() == b"from-url"

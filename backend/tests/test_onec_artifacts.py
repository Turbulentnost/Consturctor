"""Download of 1C attached files (OData / volume / DTW / UNC)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.api.v1.tools import _artifact_invoke_view, _dispatch_server_tool
from app.services.onec_artifacts import (
    ASSIGNMENT_FILES_ENTITY,
    ArtifactError,
    artifact_object_name,
    cached_artifact_download,
    download_artifact_file,
    handle_download_artifact,
    load_artifact_file,
    stub_download_artifact,
)
from app.services.onec_tools import ONEC_TOOLS, invoke_onec
from app.services.local_mcp import list_tools
from app.services.tool_names import resolve_tool_name


def test_resolve_download_artifact_aliases() -> None:
    assert resolve_tool_name("onec.download_artifact", ONEC_TOOLS) == "onec.download_artifact"
    assert resolve_tool_name("onecdownload_artifact", ONEC_TOOLS) == "onec.download_artifact"
    assert resolve_tool_name("onec_download_artifact", ONEC_TOOLS) == "onec.download_artifact"
    assert resolve_tool_name("web_search", ONEC_TOOLS) is None


def test_tool_is_registered() -> None:
    assert "onec.download_artifact" in ONEC_TOOLS
    names = {item["name"] for item in list_tools()}
    assert "onec.download_artifact" in names
    tool = next(item for item in list_tools() if item["name"] == "onec.download_artifact")
    assert tool.get("execution") == "server"
    assert tool.get("entity") == "file"


def test_stub_download_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    result = stub_download_artifact({"file_id": "11111111-1111-1111-1111-111111111111"})
    assert result["source"] == "stub"
    assert result["filename"]
    assert Path(result["saved_path"]).is_file()
    assert base64.b64decode(result["content_base64"]) == b"stub 1C attachment"


def test_invoke_without_file_id() -> None:
    from app.services.onec_tools import OnecToolError, odata_configured

    if odata_configured():
        try:
            invoke_onec("onec.download_artifact", {})
            raise AssertionError("expected OnecToolError")
        except OnecToolError as exc:
            assert "file_id" in str(exc)
        return
    result = invoke_onec("onec.download_artifact", {})
    assert result.get("source") == "stub"


def test_download_uses_odata_base64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = "c1ec90a0-80de-11f1-9843-6cb31113810c"
    payload = b"%PDF-1.4\nfrom-odata"
    row = {
        "Ref_Key": file_id,
        "Description": "report",
        "Расширение": "pdf",
        "ПутьКФайлу": "",
        "ФайлХранилище_Base64Data": base64.b64encode(payload).decode("ascii"),
    }
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.onec_artifacts.odata_json",
        lambda path, timeout=None: (200, row) if ASSIGNMENT_FILES_ENTITY in path else (404, None),
    )
    monkeypatch.setattr(
        "app.services.onec_artifacts.http_bytes",
        lambda url, timeout=None: (_ for _ in ()).throw(AssertionError("dtw must not be called")),
    )

    artifact = download_artifact_file(file_id)

    assert artifact.content == payload
    assert artifact.filename == "report.pdf"
    assert artifact.method == "odata_base64"
    assert artifact.source_entity == ASSIGNMENT_FILES_ENTITY
    assert Path(artifact.saved_path).read_bytes() == payload


def test_download_uses_dtw_and_unwraps_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_id = "c49963b3-7a91-11f1-983b-6cb31113810e"
    pdf = b"%PDF-1.4\nwrapped-pdf"
    envelope = json.dumps(
        {
            "fileName": "1597_260708090522_001.pdf",
            "contentBase64": base64.b64encode(pdf).decode("ascii"),
        }
    ).encode("utf-8")
    row = {
        "Ref_Key": file_id,
        "Description": "1597_260708090522_001",
        "Расширение": "pdf",
        "ПутьКФайлу": "20260708\\1597_260708090522_001.pdf",
        "ФайлХранилище_Base64Data": "",
    }
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.onec_artifacts.odata_json",
        lambda path, timeout=None: (200, row) if "guid'" in path and "Тома" not in path else (404, None),
    )
    monkeypatch.setattr(
        "app.services.onec_artifacts.http_bytes",
        lambda url, timeout=None: (200, envelope) if "/hs/dtw/files/" in url else (404, b""),
    )

    artifact = download_artifact_file(file_id)

    assert artifact.content == pdf
    assert artifact.filename == "1597_260708090522_001.pdf"
    assert artifact.method == "dtw"
    assert artifact.content_type == "application/pdf"


def test_download_prefers_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = "939f6175-8a8b-11f1-9850-6cb31113810e"
    filename = "1648_260716092101_001.pdf"
    cached = b"cached-bytes"
    dest = tmp_path / file_id
    dest.mkdir()
    (dest / filename).write_bytes(cached)
    row = {
        "Ref_Key": file_id,
        "Description": "ДИ",
        "Расширение": "pdf",
        "ПутьКФайлу": f"20260716\\{filename}",
        "ФайлХранилище_Base64Data": "",
    }
    called_dtw = []
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.onec_artifacts.odata_json",
        lambda path, timeout=None: (200, row),
    )
    monkeypatch.setattr(
        "app.services.onec_artifacts.http_bytes",
        lambda url, timeout=None: called_dtw.append(url) or (200, b"unused"),
    )

    artifact = download_artifact_file(file_id)

    assert artifact.content == cached
    assert artifact.method == "cache"
    assert called_dtw == []


def test_download_reads_volume_share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    tom_key = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    volume = tmp_path / "volume"
    rel = "2026\\note.txt"
    (volume / "2026").mkdir(parents=True)
    (volume / rel.replace("\\", "/")).write_bytes(b"from-volume")
    row = {
        "Ref_Key": file_id,
        "Description": "note",
        "Расширение": "txt",
        "ПутьКФайлу": rel,
        "ТипХраненияФайла": "ВТомахНаДиске",
        "Том_Key": tom_key,
        "ФайлХранилище_Base64Data": "",
    }

    def fake_json(path: str, timeout=None):
        if "Catalog_ТомаХраненияФайлов" in path:
            return 200, {"ПолныйПутьWindows": str(volume)}
        if ASSIGNMENT_FILES_ENTITY in path:
            return 200, row
        return 404, None

    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr("app.services.onec_artifacts.odata_json", fake_json)
    monkeypatch.setattr(
        "app.services.onec_artifacts.http_bytes",
        lambda url, timeout=None: (_ for _ in ()).throw(AssertionError("dtw must not be called")),
    )

    artifact = download_artifact_file(file_id)
    assert artifact.content == b"from-volume"
    assert artifact.method == "volume"


def test_download_deleted_file_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    row = {
        "Ref_Key": file_id,
        "Description": "gone",
        "Расширение": "pdf",
        "ПутьКФайлу": "",
        "DeletionMark": True,
        "ФайлХранилище_Base64Data": "",
    }
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.onec_artifacts.odata_json",
        lambda path, timeout=None: (200, row),
    )
    monkeypatch.setattr(
        "app.services.onec_artifacts.http_bytes",
        lambda url, timeout=None: (404, b""),
    )

    with pytest.raises(ArtifactError, match="deleted"):
        download_artifact_file(file_id)


def test_handle_download_returns_base64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    payload = b"hello-file"
    row = {
        "Ref_Key": file_id,
        "Description": "hello",
        "Расширение": "txt",
        "ФайлХранилище_Base64Data": base64.b64encode(payload).decode("ascii"),
    }
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.onec_artifacts.odata_json",
        lambda path, timeout=None: (200, row),
    )

    result = handle_download_artifact({"file_id": file_id})
    assert result["filename"] == "hello.txt"
    assert result["size"] == len(payload)
    assert base64.b64decode(result["content_base64"]) == payload
    assert artifact_object_name(file_id, "hello.txt") == f"{file_id}/hello.txt"
    cached = cached_artifact_download(file_id)
    assert cached is not None
    assert cached.content == payload
    loaded = load_artifact_file(file_id)
    assert loaded.content == payload


def test_artifact_invoke_view_adds_content_url() -> None:
    file_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    view = _artifact_invoke_view(
        {
            "file_id": file_id,
            "filename": "big.bin",
            "content_base64": "A" * 400_000,
        }
    )
    assert view["content_url"] == f"/api/v1/tools/onec-artifacts/{file_id}"
    assert "content_base64" not in view
    assert view["content_omitted"] is True


def test_dispatch_accepts_name_without_dots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    monkeypatch.setattr("app.services.onec_artifacts.artifact_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.api.v1.tools.invoke_onec",
        lambda tool, args, **kwargs: stub_download_artifact(
            {"file_id": file_id, "filename": "note.txt"}
        ),
    )
    auth = type("Auth", (), {"user_id": "u1", "fio": "Test"})()
    payload = _dispatch_server_tool("onecdownload_artifact", {"file_id": file_id}, auth)
    assert payload["ok"] is True
    assert payload["tool"] == "onec.download_artifact"
    assert payload["result"]["filename"] == "note.txt"
    assert payload["result"]["content_url"] == f"/api/v1/tools/onec-artifacts/{file_id}"

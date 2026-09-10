"""Download attached 1C files (porucheniya / protocols).

Same lookup chain as AIAgentBack download_artifact_file:
OData ФайлХранилище_Base64Data, volume share (ВТомахНаДиске +
Catalog_ТомаХраненияФайлов), HTTP hs/dtw/files/{id}, then UNC path.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import BACKEND_ROOT, settings

ASSIGNMENT_FILES_ENTITY = "Catalog_ТД_ПорученияПрисоединенныеФайлы"
PROTOCOL_FILES_ENTITY = "Catalog_ТД_ПротоколПрисоединенныеФайлы"
ARTIFACT_ENTITIES = (ASSIGNMENT_FILES_ENTITY, PROTOCOL_FILES_ENTITY)
VOLUME_STORAGE_CATALOG = "Catalog_ТомаХраненияФайлов"
VOLUME_STORAGE_TYPE = "ВТомахНаДиске"
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_INLINE_BASE64_LIMIT = 256 * 1024
_FALLBACK_TIMEOUT = 15.0
_FILE_HTTP_TIMEOUT = 90.0


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactDownload:
    file_id: str
    filename: str
    content_type: str
    content: bytes
    source_entity: str
    method: str
    saved_path: str = ""


def artifact_cache_dir() -> Path:
    configured = getattr(settings, "onec_artifact_storage_dir", None)
    path = Path(configured) if configured else BACKEND_ROOT / "storage" / "onec_artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_object_name(file_id: str, filename: str) -> str:
    safe_name = Path(filename or file_id or "artifact.bin").name
    return f"{file_id}/{safe_name}"


def _guess_content_type(extension: str, filename: str) -> str:
    ext = extension.strip().lstrip(".").lower()
    if ext:
        guessed = mimetypes.guess_type(f"file.{ext}", strict=False)[0]
        if guessed:
            return guessed
    guessed = mimetypes.guess_type(filename or "", strict=False)[0]
    return guessed or "application/octet-stream"


def _normalize_filename(row: dict[str, Any]) -> str:
    description = str(row.get("Description") or row.get("Subject") or "").strip()
    path_value = str(row.get("ПутьКФайлу") or "").strip().replace("/", "\\")
    extension = str(row.get("Расширение") or "").strip().lstrip(".")
    if path_value:
        filename = path_value.rsplit("\\", 1)[-1]
        if filename:
            return filename
    if description:
        if extension and not description.casefold().endswith(f".{extension.casefold()}"):
            return f"{description}.{extension}"
        return description
    if extension:
        return f"file.{extension}"
    return "artifact.bin"


def _row_meta(row: dict[str, Any]) -> tuple[str, str, str]:
    file_id = str(row.get("Ref_Key") or "").strip()
    filename = _normalize_filename(row)
    extension = str(row.get("Расширение") or "").strip().lstrip(".")
    return file_id, filename, _guess_content_type(extension, filename)


def _decode_base64_bytes(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (ValueError, binascii.Error):
        return None


def _unwrap_dtw_file_payload(content: bytes | None) -> bytes | None:
    if content is None:
        return None
    stripped = content.lstrip()
    if not stripped.startswith(b"{"):
        return content
    try:
        payload = json.loads(stripped.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return content
    if not isinstance(payload, dict) or "contentBase64" not in payload or "fileName" not in payload:
        return content
    return _decode_base64_bytes(payload.get("contentBase64"))


def _read_base64_payload(row: dict[str, Any]) -> bytes | None:
    return _decode_base64_bytes(row.get("ФайлХранилище_Base64Data"))


def _read_via_unc(path_value: str) -> bytes | None:
    if not path_value:
        return None
    unc_path = Path(path_value)
    try:
        if unc_path.exists() and unc_path.is_file():
            return unc_path.read_bytes()
    except OSError:
        return None
    return None


def _odata_auth() -> tuple[str, str] | None:
    from app.services.onec_tools import _odata_auth as _auth

    return _auth()


def _odata_timeout() -> float:
    return float(getattr(settings, "odata_timeout_sec", 60.0) or 60.0)


def odata_json(path: str, timeout: float | None = None) -> tuple[int, Any]:
    from app.services.onec_tools import _odata_url

    auth = _odata_auth()
    if not auth:
        raise ArtifactError("OData credentials not configured")
    if not settings.odata_base_url:
        raise ArtifactError("ODATA_BASE_URL not configured")
    url = _odata_url(path)
    wait = float(timeout) if timeout is not None else _odata_timeout()
    with httpx.Client(timeout=wait, auth=auth) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            return response.status_code, None
        try:
            return response.status_code, response.json()
        except json.JSONDecodeError:
            return response.status_code, None


def http_bytes(url: str, timeout: float | None = None) -> tuple[int, bytes]:
    auth = _odata_auth()
    if not auth:
        raise ArtifactError("OData credentials not configured")
    wait = float(timeout) if timeout is not None else _FILE_HTTP_TIMEOUT
    with httpx.Client(timeout=wait, auth=auth) as client:
        response = client.get(url)
        return response.status_code, response.content or b""


def _find_attachment_row(
    file_id: str,
    *,
    entity: str = "",
) -> tuple[str, dict[str, Any]]:
    candidates: list[str] = []
    named = str(entity or "").strip()
    if named:
        candidates.append(named)
    for item in ARTIFACT_ENTITIES:
        if item not in candidates:
            candidates.append(item)
    last_status = 0
    for name in candidates:
        path = f"{name}(guid'{file_id}')?$format=json"
        status, data = odata_json(path)
        last_status = status
        if status == 404 or data is None:
            continue
        if status >= 400:
            continue
        if isinstance(data, dict) and (data.get("Ref_Key") or data.get("value")):
            row = data
            if isinstance(data.get("value"), list) and data["value"]:
                first = data["value"][0]
                if isinstance(first, dict):
                    row = first
            if isinstance(row, dict):
                return name, row
    if last_status in {401, 402, 403}:
        raise ArtifactError(f"1C OData HTTP {last_status}: access denied")
    raise ArtifactError(f"1C file not found: {file_id}")


def _read_via_volume(row: dict[str, Any]) -> bytes | None:
    if str(row.get("ТипХраненияФайла") or "").strip() != VOLUME_STORAGE_TYPE:
        return None
    tom_key = str(row.get("Том_Key") or "").strip()
    rel_path = str(row.get("ПутьКФайлу") or "").strip()
    if not tom_key or tom_key.startswith(_EMPTY_GUID) or not rel_path:
        return None
    path = (
        f"{VOLUME_STORAGE_CATALOG}(guid'{tom_key}')"
        f"?$select=ПолныйПутьWindows,ПолныйПутьLinux&$format=json"
    )
    status, volume = odata_json(path, timeout=_FALLBACK_TIMEOUT)
    if status >= 400 or not isinstance(volume, dict):
        return None
    base = str(volume.get("ПолныйПутьWindows") or "").strip()
    if not base:
        return None
    full_path = f"{base.rstrip(chr(92) + '/')}\\{rel_path.replace('/', chr(92)).lstrip(chr(92))}"
    return _read_via_unc(full_path)


def _dtw_base_url() -> str:
    base = settings.odata_base_url.rstrip("/")
    marker = "/odata/standard.odata"
    if marker in base:
        return base.split(marker, 1)[0]
    if base.endswith("/odata"):
        return base[: -len("/odata")]
    return base


def _read_via_dtw(file_id: str) -> bytes | None:
    url = f"{_dtw_base_url()}/hs/dtw/files/{file_id}"
    try:
        status, content = http_bytes(url, timeout=_FILE_HTTP_TIMEOUT)
    except Exception:  # noqa: BLE001
        return None
    if status != 200 or not content:
        return None
    return _unwrap_dtw_file_payload(content)


def _cache_path(file_id: str, filename: str) -> Path:
    return artifact_cache_dir() / file_id / Path(filename).name


def cached_artifact_download(file_id: str) -> ArtifactDownload | None:
    normalized = str(file_id or "").strip()
    if not normalized or not _GUID_RE.match(normalized):
        return None
    folder = artifact_cache_dir() / normalized
    if not folder.is_dir():
        return None
    files = sorted(path for path in folder.iterdir() if path.is_file())
    if not files:
        return None
    path = files[0]
    try:
        content = path.read_bytes()
    except OSError:
        return None
    return ArtifactDownload(
        file_id=normalized,
        filename=path.name,
        content_type=_guess_content_type(path.suffix, path.name),
        content=content,
        source_entity="",
        method="cache",
        saved_path=str(path),
    )


def load_artifact_file(file_id: str, *, entity: str = "") -> ArtifactDownload:
    cached = cached_artifact_download(file_id)
    if cached is not None:
        return cached
    return download_artifact_file(file_id, entity=entity)


def _read_cached_bytes(file_id: str, filename: str) -> bytes | None:
    path = _cache_path(file_id, filename)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _write_cached_bytes(file_id: str, filename: str, content: bytes) -> Path:
    path = _cache_path(file_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def download_artifact_file(file_id: str, *, entity: str = "") -> ArtifactDownload:
    normalized = str(file_id or "").strip()
    if not normalized:
        raise ArtifactError("file_id required")
    if not _GUID_RE.match(normalized):
        raise ArtifactError("file_id must be a GUID")

    source_entity, row = _find_attachment_row(normalized, entity=entity)
    file_id_value, filename, content_type = _row_meta(row)
    file_id_value = file_id_value or normalized

    cached = _read_cached_bytes(file_id_value, filename)
    content = _unwrap_dtw_file_payload(cached) if cached is not None else None
    method = "cache" if content is not None else ""
    if content is None:
        content = _read_base64_payload(row)
        method = "odata_base64" if content else method
    if content is None:
        content = _read_via_volume(row)
        method = "volume" if content else method
    if content is None:
        content = _read_via_dtw(file_id_value)
        method = "dtw" if content else method
    if content is None:
        content = _read_via_unc(str(row.get("ПутьКФайлу") or "").strip())
        method = "unc" if content else method

    if content is None:
        if row.get("DeletionMark"):
            raise ArtifactError(
                f"1C file is marked deleted and cannot be downloaded: {filename or normalized}"
            )
        raise ArtifactError(f"Could not read 1C file bytes: {normalized}")

    saved = _write_cached_bytes(file_id_value, filename, content)
    return ArtifactDownload(
        file_id=file_id_value,
        filename=filename,
        content_type=content_type,
        content=content,
        source_entity=source_entity,
        method=method or "odata",
        saved_path=str(saved),
    )


def _payload_from_download(artifact: ArtifactDownload) -> dict[str, Any]:
    size = len(artifact.content)
    result: dict[str, Any] = {
        "summary": (
            f"1C file downloaded: {artifact.filename} ({size} bytes, {artifact.method})"
        ),
        "file_id": artifact.file_id,
        "filename": artifact.filename,
        "content_type": artifact.content_type,
        "size": size,
        "source_entity": artifact.source_entity,
        "method": artifact.method,
        "saved_path": artifact.saved_path,
        "file": artifact.saved_path,
        "path": artifact.saved_path,
        "source": "odata",
    }
    if size <= _INLINE_BASE64_LIMIT:
        result["content_base64"] = base64.b64encode(artifact.content).decode("ascii")
    else:
        result["content_omitted"] = True
        result["summary"] += " (inline bytes omitted, see saved_path)"
    return result


def handle_download_artifact(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    file_id = str(
        payload.get("file_id")
        or payload.get("file_ref_key")
        or payload.get("Ref_Key")
        or ""
    ).strip()
    if not file_id:
        raise ArtifactError("file_id required (GUID from action=files)")
    artifact = download_artifact_file(
        file_id,
        entity=str(payload.get("entity") or "").strip(),
    )
    return _payload_from_download(artifact)


def stub_download_artifact(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    file_id = str(payload.get("file_id") or payload.get("file_ref_key") or "").strip()
    name = str(payload.get("filename") or "stub-artifact.txt")
    content = b"stub 1C attachment"
    fake_id = file_id or "00000000-0000-0000-0000-000000000001"
    saved = _write_cached_bytes(fake_id, name, content)
    artifact = ArtifactDownload(
        file_id=fake_id,
        filename=name,
        content_type="text/plain",
        content=content,
        source_entity=ASSIGNMENT_FILES_ENTITY,
        method="stub",
        saved_path=str(saved),
    )
    result = _payload_from_download(artifact)
    result["source"] = "stub"
    result["summary"] = f"stub 1C file: {name}"
    return result

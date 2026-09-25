"""Download attached 1C files over HTTP only (hs/dtw/files/{id}).

Listing cards may still use OData. Bytes never do.
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
from urllib.parse import unquote

import httpx

from app.config import BACKEND_ROOT, settings

ASSIGNMENT_FILES_ENTITY = "Catalog_ТД_ПорученияПрисоединенныеФайлы"
PROTOCOL_FILES_ENTITY = "Catalog_ТД_ПротоколПрисоединенныеФайлы"
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_INLINE_BASE64_LIMIT = 256 * 1024
_FILE_HTTP_TIMEOUT = 90.0
_FILENAME_HEADER_RE = re.compile(
    r"filename\*?=(?:UTF-8''|\"?)([^\";]+)",
    re.IGNORECASE,
)


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


def _decode_base64_bytes(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (ValueError, binascii.Error):
        return None


def _filename_from_header(disposition: str) -> str:
    match = _FILENAME_HEADER_RE.search(disposition or "")
    if not match:
        return ""
    return Path(unquote(match.group(1).strip().strip('"'))).name


def _filename_from_bytes(file_id: str, content: bytes, hinted: str) -> str:
    name = Path(hinted).name if hinted else ""
    if name:
        return name
    if content.startswith(b"%PDF"):
        return f"{file_id}.pdf"
    if content[:3] == b"\xff\xd8\xff":
        return f"{file_id}.jpg"
    if content.startswith(b"\x89PNG"):
        return f"{file_id}.png"
    if content[:2] == b"PK":
        return f"{file_id}.zip"
    return f"{file_id}.bin"


def _parse_dtw_response(
    content: bytes,
    *,
    disposition: str = "",
) -> tuple[bytes | None, str]:
    hinted = _filename_from_header(disposition)
    stripped = content.lstrip()
    if stripped.startswith(b"{"):
        try:
            payload = json.loads(stripped.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if (
            isinstance(payload, dict)
            and "contentBase64" in payload
            and "fileName" in payload
        ):
            body = _decode_base64_bytes(payload.get("contentBase64"))
            name = Path(str(payload.get("fileName") or hinted)).name
            return body, name
    return content if content else None, hinted


def _http_auth() -> tuple[str, str] | None:
    from app.services.onec_tools import _odata_auth as _auth

    return _auth()


def _dtw_base_url() -> str:
    base = str(getattr(settings, "odata_base_url", "") or "").rstrip("/")
    if not base:
        raise ArtifactError("ODATA_BASE_URL not configured")
    marker = "/odata/standard.odata"
    if marker in base:
        return base.split(marker, 1)[0]
    if base.endswith("/odata"):
        return base[: -len("/odata")]
    return base


def http_bytes(url: str, timeout: float | None = None) -> tuple[int, bytes, str]:
    auth = _http_auth()
    if not auth:
        raise ArtifactError("1C HTTP credentials not configured")
    wait = float(timeout) if timeout is not None else _FILE_HTTP_TIMEOUT
    try:
        with httpx.Client(timeout=wait, auth=auth) as client:
            response = client.get(url)
    except httpx.TimeoutException as exc:
        raise ArtifactError(f"1C HTTP: нет ответа за {int(wait)} с") from exc
    disposition = str(response.headers.get("content-disposition") or "")
    return response.status_code, response.content or b"", disposition


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


def _write_cached_bytes(file_id: str, filename: str, content: bytes) -> Path:
    path = _cache_path(file_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def download_artifact_file(file_id: str, *, entity: str = "") -> ArtifactDownload:
    _ = entity
    normalized = str(file_id or "").strip()
    if not normalized:
        raise ArtifactError("file_id required")
    if not _GUID_RE.match(normalized):
        raise ArtifactError("file_id must be a GUID")

    cached_hit = cached_artifact_download(normalized)
    if cached_hit is not None:
        return cached_hit

    url = f"{_dtw_base_url()}/hs/dtw/files/{normalized}"
    status, raw, disposition = http_bytes(url, timeout=_FILE_HTTP_TIMEOUT)
    if status in {401, 402, 403}:
        raise ArtifactError(f"1C HTTP {status}: access denied")
    if status == 404 or not raw:
        raise ArtifactError(f"1C file not found: {normalized}")
    if status != 200:
        raise ArtifactError(f"1C HTTP {status}: could not download {normalized}")

    content, hinted = _parse_dtw_response(raw, disposition=disposition)
    if content is None:
        raise ArtifactError(f"Could not read 1C file bytes: {normalized}")
    filename = _filename_from_bytes(normalized, content, hinted)
    content_type = _guess_content_type(Path(filename).suffix, filename)
    saved = _write_cached_bytes(normalized, filename, content)
    return ArtifactDownload(
        file_id=normalized,
        filename=filename,
        content_type=content_type,
        content=content,
        source_entity="",
        method="http",
        saved_path=str(saved),
    )


def load_artifact_file(file_id: str, *, entity: str = "") -> ArtifactDownload:
    cached = cached_artifact_download(file_id)
    if cached is not None:
        return cached
    return download_artifact_file(file_id, entity=entity)


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
        "source": "http",
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
    artifact = load_artifact_file(
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

"""1C:Enterprise COM helpers (32-bit client, connection string from env)."""

from __future__ import annotations

import os
import struct
import sys
import uuid
from typing import Any
from urllib.parse import urlparse

_ONEC_PROGIDS = (
    "V83.COMConnector.1",
    "V83.COMConnector",
    "V83c.COMConnector",
)

_APPLICATION_PROGIDS = (
    "V83.Application",
    "V83c.Application",
    "V82.Application",
)


def python_bitness() -> int:
    return struct.calcsize("P") * 8


def is_64bit_python() -> bool:
    return python_bitness() == 64


def _strip_env_value(raw: str) -> str:
    value = (raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _server_ref_from_odata() -> tuple[str, str]:
    base = (os.environ.get("ODATA_BASE_URL") or os.environ.get("ONEC_COM_ODATA_URL") or "").strip()
    if not base:
        return "", "erp_pm"
    parsed = urlparse(base)
    host = parsed.hostname or ""
    parts = [part for part in (parsed.path or "").split("/") if part]
    ref = parts[0] if parts else "erp_pm"
    return host, ref


def build_connection_string(*, override: str = "") -> str:
    explicit = _strip_env_value(override or os.environ.get("ONEC_COM_CONNECTION_STRING") or "")
    if explicit:
        return explicit if explicit.endswith(";") else f"{explicit};"

    server = _strip_env_value(os.environ.get("ONEC_COM_SERVER") or "")
    ref = _strip_env_value(os.environ.get("ONEC_COM_REF") or os.environ.get("ONEC_COM_IB") or "")
    if not server or not ref:
        parsed_server, parsed_ref = _server_ref_from_odata()
        server = server or parsed_server
        ref = ref or parsed_ref

    user = _strip_env_value(
        os.environ.get("ONEC_COM_USER")
        or os.environ.get("ERP_LOGIN")
        or os.environ.get("ONEC_USER")
        or ""
    )
    password = _strip_env_value(
        os.environ.get("ONEC_COM_PASSWORD")
        or os.environ.get("ERP_PASSWORD")
        or os.environ.get("ONEC_PASSWORD")
        or ""
    )

    parts: list[str] = []
    if server:
        parts.append(f'Srvr="{server}"')
    if ref:
        parts.append(f'Ref="{ref}"')
    if user:
        parts.append(f'Usr="{user}"')
    if password:
        parts.append(f'Pwd="{password}"')
    return ";".join(parts) + (";" if parts else "")


def find_python32() -> str | None:
    override = _strip_env_value(os.environ.get("ONEC_COM_PYTHON") or os.environ.get("DESKTOP_HOST_PYTHON") or "")
    if override and os.path.isfile(override):
        return override

    import subprocess

    try:
        listing = subprocess.check_output(["py", "-0p"], text=True, timeout=15, stderr=subprocess.STDOUT)
    except (OSError, subprocess.SubprocessError):
        return None

    candidates: list[str] = []
    for line in listing.splitlines():
        if "-32" not in line.lower():
            continue
        token = line.strip().split()[-1]
        if token.lower().endswith("python.exe") and os.path.isfile(token):
            candidates.append(token)
    if not candidates:
        return None
    # Prefer newest CPython 3.12 32-bit, then any 32-bit.
    for preferred in candidates:
        if "Python312" in preferred or "3.12" in preferred:
            return preferred
    return candidates[0]


def com_bitness_hint() -> str:
    if not is_64bit_python():
        return f"python={python_bitness()}-bit"
    py32 = find_python32()
    if py32:
        return f"host=64-bit, onec-bridge=32-bit ({py32})"
    return (
        "host=64-bit, onec-bridge=missing: install Python 3.12 (32-bit) "
        "and run scripts\\ensure_com_python.cmd"
    )


def connect_application(*, progid: str = "", connection_string: str = "") -> tuple[Any, str, str]:
    """Return (com_object, mode, progid_used). mode: active|connected."""
    import win32com.client

    conn = connection_string or build_connection_string()
    if not conn.strip():
        raise RuntimeError("ONEC_COM_CONNECTION_REQUIRED: set ONEC_COM_SERVER/ERP_LOGIN in infra/.env")

    last_exc: Exception | None = None
    for candidate in _APPLICATION_PROGIDS:
        try:
            obj = win32com.client.GetActiveObject(candidate)
            return obj, "active", candidate
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    connector_progids = [progid] if progid else []
    default = _strip_env_value(os.environ.get("ONEC_COM_PROGID") or "V83.COMConnector")
    connector_progids.extend([default, *_ONEC_PROGIDS])

    seen: set[str] = set()
    ordered: list[str] = []
    for item in connector_progids:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)

    for candidate in ordered:
        try:
            connector = win32com.client.Dispatch(candidate)
            app = connector.Connect(conn)
            return app, "connected", candidate
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    raise RuntimeError(
        f"ONEC_COM_UNAVAILABLE: cannot connect to 1C ERP via COM ({last_exc}). "
        f"{com_bitness_hint()}. "
        "Set ONEC_COM_SERVER to ragent host (without HTTP port)."
    ) from last_exc


def connect_session(*, progid: str = "") -> dict[str, Any]:
    obj, mode, used_progid = connect_application(progid=progid)
    session_id = str(uuid.uuid4())
    return {
        "session_id": session_id,
        "object": obj,
        "app": "onec",
        "progid": used_progid,
        "mode": mode,
        "connection": "configured" if build_connection_string() else "none",
        "python_bitness": python_bitness(),
    }

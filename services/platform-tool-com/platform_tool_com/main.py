from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

_DEFAULT_APPS = {
    "onec": "V83.Application",
    "outlook": "Outlook.Application",
    "excel": "Excel.Application",
}


class ComSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-com"
    api_port: int = 7826
    com_apps: str = ""
    com_timeout_sec: int = 120


settings = ComSettings()
_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}
_stub_sessions: dict[str, dict[str, Any]] = {}


def _parse_apps() -> dict[str, str]:
    raw = (settings.com_apps or os.environ.get("COM_APPS") or "").strip()
    if not raw:
        return dict(_DEFAULT_APPS)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    apps: dict[str, str] = {}
    for part in raw.split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        apps[key.strip()] = value.strip()
    return apps or dict(_DEFAULT_APPS)


def _method_allowlist(app_id: str) -> set[str]:
    env_key = f"COM_METHOD_ALLOWLIST_{app_id}"
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return {
            "Connect",
            "NewObject",
            "Documents",
            "GetObject",
            "Quit",
            "CreateItem",
            "Workbooks",
            "ActiveWorkbook",
        }
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_windows() -> bool:
    return sys.platform == "win32"


def _list_apps(_: ToolInvokeRequest) -> dict[str, Any]:
    apps = _parse_apps()
    return {
        "summary": f"apps={len(apps)}",
        "apps": [{"id": key, "progid": value} for key, value in sorted(apps.items())],
        "platform": sys.platform,
        "com_available": _is_windows(),
    }


def _connect(req: ToolInvokeRequest) -> dict[str, Any]:
    app_id = str(req.payload.get("app", "")).strip().lower()
    apps = _parse_apps()
    if app_id not in apps:
        raise ValueError(f"unknown app: {app_id}")
    progid = str(req.payload.get("progid", "")).strip() or apps[app_id]
    if not _is_windows():
        raise RuntimeError("COM is only available on Windows host")
    with _lock:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        obj = win32com.client.Dispatch(progid)
        session_id = str(uuid.uuid4())
        _sessions[session_id] = {"app": app_id, "progid": progid, "object": obj}
    return {
        "summary": f"connected {app_id}",
        "session_id": session_id,
        "app": app_id,
        "progid": progid,
        "source": "com",
    }


def _invoke(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    method = str(req.payload.get("method", "")).strip()
    if not session_id or not method:
        raise ValueError("session_id and method required")
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            raise ValueError("session not found")
        allowlist = _method_allowlist(str(session["app"]))
        if method not in allowlist:
            raise ValueError(f"method not allowed: {method}")
        obj = session["object"]
        args = req.payload.get("args") or []
        kwargs = req.payload.get("kwargs") or {}
        if not isinstance(args, list):
            raise ValueError("args must be a list")
        if not isinstance(kwargs, dict):
            raise ValueError("kwargs must be an object")
        result = getattr(obj, method)(*args, **kwargs)
        if hasattr(result, "__class__"):
            result_repr = str(result)
        else:
            result_repr = result
    return {
        "summary": f"invoke {method}",
        "session_id": session_id,
        "method": method,
        "result": result_repr,
        "source": "com",
    }


def _release(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    if not session_id:
        raise ValueError("session_id required")
    with _lock:
        session = _sessions.pop(session_id, None)
        if not session:
            raise ValueError("session not found")
        obj = session.get("object")
        if obj is not None and hasattr(obj, "Quit"):
            try:
                obj.Quit()
            except Exception:
                pass
    return {"summary": "released", "session_id": session_id, "source": "com"}


def _stub_connect(req: ToolInvokeRequest) -> dict[str, Any]:
    app_id = str(req.payload.get("app", "onec")).strip().lower()
    apps = _parse_apps()
    if app_id not in apps:
        raise ValueError(f"unknown app: {app_id}")
    session_id = str(uuid.uuid4())
    _stub_sessions[session_id] = {"app": app_id, "progid": apps[app_id], "state": {}}
    return {
        "summary": f"stub connected {app_id}",
        "session_id": session_id,
        "app": app_id,
        "progid": apps[app_id],
        "source": "stub",
    }


def _stub_invoke(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    method = str(req.payload.get("method", "")).strip()
    session = _stub_sessions.get(session_id)
    if not session:
        raise ValueError("session not found")
    allowlist = _method_allowlist(str(session["app"]))
    if method not in allowlist:
        raise ValueError(f"method not allowed: {method}")
    args = req.payload.get("args") or []
    result = {
        "stub": True,
        "app": session["app"],
        "method": method,
        "args": args,
        "message": f"stub COM invoke {session['app']}.{method}",
    }
    return {
        "summary": f"stub invoke {method}",
        "session_id": session_id,
        "method": method,
        "result": result,
        "source": "stub",
    }


def _stub_release(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    if session_id not in _stub_sessions:
        raise ValueError("session not found")
    _stub_sessions.pop(session_id, None)
    return {"summary": "stub released", "session_id": session_id, "source": "stub"}


REAL_HANDLERS = {
    "com.list_apps": _list_apps,
    "com.connect": _connect,
    "com.invoke": _invoke,
    "com.release": _release,
}

STUB_HANDLERS = {
    "com.list_apps": _list_apps,
    "com.connect": _stub_connect,
    "com.invoke": _stub_invoke,
    "com.release": _stub_release,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()

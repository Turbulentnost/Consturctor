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
from platform_tool_com import outlook_calendar
from platform_tool_com.com_runtime import com_call

_DEFAULT_APPS = {
    "onec": "V83.Application",
    "outlook": "Outlook.Application",
    "excel": "Excel.Application",
    "word": "Word.Application",
    "powerpoint": "PowerPoint.Application",
}

_OUTLOOK_DEFAULT_METHODS = {
    "Connect",
    "GetNamespace",
    "CreateItem",
    "Quit",
    "GetDefaultFolder",
    "GetItemFromID",
    "Session",
    "Explorers",
    "ActiveExplorer",
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
_bridge_session_ids: set[str] = set()
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
    if raw:
        return {item.strip() for item in raw.split(",") if item.strip()}
    if app_id == "outlook":
        return set(_OUTLOOK_DEFAULT_METHODS)
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


def _is_windows() -> bool:
    return sys.platform == "win32"


def _onec_status() -> dict[str, Any]:
    from platform_tool_com.onec_com import (
        build_connection_string,
        com_bitness_hint,
        find_python32,
        is_64bit_python,
        python_bitness,
    )
    from platform_tool_com.onec_bridge import should_use_bridge

    conn = build_connection_string()
    return {
        "python_bitness": python_bitness(),
        "bridge": should_use_bridge(),
        "python32": find_python32(),
        "hint": com_bitness_hint(),
        "connection_configured": bool(conn.strip()),
        "needs_32bit_python": is_64bit_python() and find_python32() is None,
    }


def _list_apps(_: ToolInvokeRequest) -> dict[str, Any]:
    apps = _parse_apps()
    payload: dict[str, Any] = {
        "summary": f"apps={len(apps)}",
        "apps": [{"id": key, "progid": value} for key, value in sorted(apps.items())],
        "platform": sys.platform,
        "com_available": _is_windows(),
    }
    if _is_windows():
        payload["onec"] = _onec_status()
    return payload


def _connect_real(app_id: str, progid: str) -> tuple[str, Any]:
    import win32com.client

    obj = win32com.client.Dispatch(progid)
    session_id = str(uuid.uuid4())
    with _lock:
        _sessions[session_id] = {"app": app_id, "progid": progid, "object": obj}
    return session_id, obj


def _connect_onec(progid: str) -> dict[str, Any]:
    from platform_tool_com.onec_bridge import bridge_connect, should_use_bridge
    from platform_tool_com.onec_com import (
        com_bitness_hint,
        connect_session,
        find_python32,
        is_64bit_python,
    )

    if should_use_bridge():
        data = bridge_connect(progid=progid)
        with _lock:
            _bridge_session_ids.add(data["session_id"])
        return {
            "summary": "connected onec (32-bit bridge)",
            "session_id": data["session_id"],
            "app": "onec",
            "progid": data.get("progid") or progid,
            "mode": data.get("mode"),
            "bridge": True,
            "source": "com",
        }

    if is_64bit_python() and not find_python32():
        raise RuntimeError(
            "ONEC_COM_32BIT_PYTHON_REQUIRED: 1C client is 32-bit, host Python is 64-bit. "
            f"{com_bitness_hint()}. Run scripts\\ensure_com_python.cmd and restart desktop host."
        )

    session = connect_session(progid=progid)

    def _store() -> str:
        with _lock:
            _sessions[session["session_id"]] = session
        return session["session_id"]

    session_id = com_call(_store, timeout=90.0)
    return {
        "summary": f"connected onec ({session.get('mode')})",
        "session_id": session_id,
        "app": "onec",
        "progid": session.get("progid") or progid,
        "mode": session.get("mode"),
        "bridge": False,
        "source": "com",
    }


def _connect(req: ToolInvokeRequest) -> dict[str, Any]:
    app_id = str(req.payload.get("app", "")).strip().lower()
    apps = _parse_apps()
    if app_id not in apps:
        raise ValueError(f"unknown app: {app_id}")
    progid = str(req.payload.get("progid", "")).strip() or apps[app_id]
    if not _is_windows():
        raise RuntimeError("COM is only available on Windows host")

    if app_id == "onec":
        return _connect_onec(progid)

    def _do_connect() -> str:
        session_id, _obj = _connect_real(app_id, progid)
        return session_id

    session_id = com_call(_do_connect, timeout=60.0)
    return {
        "summary": f"connected {app_id}",
        "session_id": session_id,
        "app": app_id,
        "progid": progid,
        "source": "com",
    }


def _onec_connect(req: ToolInvokeRequest) -> dict[str, Any]:
    req.payload.setdefault("app", "onec")
    return _connect_onec(str(req.payload.get("progid", "")).strip() or _parse_apps()["onec"])


def _invoke_real(session_id: str, method: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            raise ValueError("session not found")
        allowlist = _method_allowlist(str(session["app"]))
        if method not in allowlist:
            raise ValueError(f"method not allowed: {method}")
        obj = session["object"]
    result = getattr(obj, method)(*args, **kwargs)
    if hasattr(result, "__class__"):
        return str(result)
    return result


def _invoke(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    method = str(req.payload.get("method", "")).strip()
    if not session_id or not method:
        raise ValueError("session_id and method required")
    args = req.payload.get("args") or []
    kwargs = req.payload.get("kwargs") or {}
    if not isinstance(args, list):
        raise ValueError("args must be a list")
    if not isinstance(kwargs, dict):
        raise ValueError("kwargs must be an object")

    with _lock:
        is_bridge = session_id in _bridge_session_ids

    if is_bridge:
        from platform_tool_com.onec_bridge import bridge_invoke

        result_repr = bridge_invoke(session_id, method, args, kwargs)
    else:
        result_repr = com_call(
            _invoke_real,
            session_id,
            method,
            args,
            kwargs,
            timeout=120.0,
        )
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
        is_bridge = session_id in _bridge_session_ids

    if is_bridge:
        from platform_tool_com.onec_bridge import bridge_release

        bridge_release(session_id)
        with _lock:
            _bridge_session_ids.discard(session_id)
    else:

        def _release_real() -> None:
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

        if _is_windows():
            com_call(_release_real, timeout=30.0)
        else:
            _release_real()
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


def _use_stub_outlook() -> bool:
    return bool(settings.use_stubs) or not _is_windows()


def _outlook_launch(req: ToolInvokeRequest) -> dict[str, Any]:
    visible = bool(req.payload.get("visible", True))
    return outlook_calendar.launch_outlook(visible=visible, stub=_use_stub_outlook())


def _outlook_close(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    quit_app = bool(req.payload.get("quit", False))
    return outlook_calendar.close_outlook(session_id, quit_app=quit_app, stub=_use_stub_outlook())


def _outlook_calendar_list(req: ToolInvokeRequest) -> dict[str, Any]:
    return outlook_calendar.calendar_list(
        session_id=str(req.payload.get("session_id", "")).strip(),
        start=req.payload.get("start"),
        end=req.payload.get("end"),
        days=int(req.payload.get("days", 7)),
        limit=int(req.payload.get("limit", 50)),
        query=str(req.payload.get("query", "")),
        include_body=bool(req.payload.get("include_body", False)),
        stub=_use_stub_outlook(),
    )


def _outlook_calendar_get(req: ToolInvokeRequest) -> dict[str, Any]:
    return outlook_calendar.calendar_get(
        entry_id=str(req.payload.get("entry_id", "")).strip(),
        session_id=str(req.payload.get("session_id", "")).strip(),
        include_body=bool(req.payload.get("include_body", True)),
        stub=_use_stub_outlook(),
    )


def _onec_status_handler(_: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "onec com status", "onec": _onec_status(), "source": "com"}


REAL_HANDLERS = {
    "com.list_apps": _list_apps,
    "com.connect": _connect,
    "com.onec.connect": _onec_connect,
    "com.onec.status": _onec_status_handler,
    "com.invoke": _invoke,
    "com.release": _release,
    "com.outlook.launch": _outlook_launch,
    "com.outlook.close": _outlook_close,
    "com.outlook.calendar_list": _outlook_calendar_list,
    "com.outlook.calendar_get": _outlook_calendar_get,
}

STUB_HANDLERS = {
    "com.list_apps": _list_apps,
    "com.connect": _stub_connect,
    "com.invoke": _stub_invoke,
    "com.release": _stub_release,
    "com.outlook.launch": _outlook_launch,
    "com.outlook.close": _outlook_close,
    "com.outlook.calendar_list": _outlook_calendar_list,
    "com.outlook.calendar_get": _outlook_calendar_get,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app
from platform_tool_onec_com.com_runtime import com_call
from platform_tool_onec_com.onec_com import (
    build_connection_string,
    connect_session,
    get_current_user_name,
    query_performer_tasks,
    require_32bit_python,
    service_status,
)

_DEFAULT_METHODS = {
    "Connect",
    "NewObject",
    "Documents",
    "GetObject",
    "Quit",
    "String",
    "EvalExpr",
    "BatchExecute",
}


class OnecComSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-onec-com"
    api_port: int = 7831
    com_timeout_sec: int = 120


settings = OnecComSettings()
_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}


def _load_infra_env() -> None:
    """Load infra/.env into os.environ (cmd start scripts break on Cyrillic values)."""
    root = os.environ.get("CONSTRUCTOR_ROOT", "").strip()
    if not root:
        root = str(Path(__file__).resolve().parents[3])
    env_path = Path(root) / "infra" / ".env"
    if not env_path.is_file():
        return
    keys_from_file = (
        "USE_STUBS",
        "ERP_LOGIN",
        "ERP_PASSWORD",
        "ODATA_BASE_URL",
        "ONEC_COM_SERVER",
        "ONEC_COM_REF",
        "ONEC_COM_USER",
        "ONEC_COM_PASSWORD",
        "ONEC_COM_CONNECTION_STRING",
        "ONEC_COM_PROGID",
    )
    parsed: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    for key in keys_from_file:
        if key in parsed:
            os.environ[key] = parsed[key]


_load_infra_env()


def _is_windows() -> bool:
    return sys.platform == "win32"


def _onec_status(_: ToolInvokeRequest) -> dict[str, Any]:
    payload = service_status()
    payload["summary"] = "onec com service status"
    payload["source"] = "onec-com"
    return payload


def _connect(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")
    progid = str(req.payload.get("progid", "")).strip()

    def _do() -> dict[str, Any]:
        session = connect_session(progid=progid)
        session_id = session["session_id"]
        with _lock:
            _sessions[session_id] = session
        return {
            "summary": f"connected 1C ERP via COM ({session.get('mode')})",
            "session_id": session_id,
            "progid": session.get("progid"),
            "mode": session.get("mode"),
            "connection": session.get("connection"),
            "current_user": session.get("current_user"),
            "python_bitness": session.get("python_bitness"),
            "transport": "com-connector",
            "source": "onec-com",
        }

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _invoke(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    method = str(req.payload.get("method", "")).strip()
    if not session_id or not method:
        raise ValueError("session_id and method required")
    if method not in _DEFAULT_METHODS:
        raise ValueError(f"method not allowed: {method}")
    args = req.payload.get("args") or []
    kwargs = req.payload.get("kwargs") or {}
    if not isinstance(args, list):
        raise ValueError("args must be a list")
    if not isinstance(kwargs, dict):
        raise ValueError("kwargs must be an object")

    def _do() -> Any:
        with _lock:
            session = _sessions.get(session_id)
            if not session:
                raise ValueError("session not found")
            obj = session["object"]
        result = getattr(obj, method)(*args, **kwargs)
        if hasattr(result, "__class__"):
            return str(result)
        return result

    result_repr = com_call(_do, timeout=float(settings.com_timeout_sec))
    return {
        "summary": f"invoke {method}",
        "session_id": session_id,
        "method": method,
        "result": result_repr,
        "source": "onec-com",
    }


def _query_tasks(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    mine_only = bool(req.payload.get("mine_only", True))
    limit = int(req.payload.get("limit") or 30)
    prefer_crm = bool(req.payload.get("prefer_crm", False))

    def _do() -> dict[str, Any]:
        nonlocal session_id
        created = False
        if not session_id:
            session = connect_session()
            session_id = session["session_id"]
            with _lock:
                _sessions[session_id] = session
            created = True

        with _lock:
            stored = _sessions.get(session_id)
            if not stored:
                raise ValueError("session not found")
            app = stored["object"]

        rows, task_source = query_performer_tasks(
            app, mine_only=mine_only, limit=limit, prefer_crm=prefer_crm
        )
        current_user = stored.get("current_user") or get_current_user_name(app)
        return {
            "summary": f"COM ERP tasks for {current_user} ({task_source})",
            "session_id": session_id,
            "current_user": current_user,
            "count": len(rows),
            "tasks": rows,
            "task_source": task_source,
            "mine_only": mine_only,
            "prefer_crm": prefer_crm,
            "session_created": created,
            "transport": "com-connector",
            "source": "onec-com",
        }

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _release(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(req.payload.get("session_id", "")).strip()
    if not session_id:
        raise ValueError("session_id required")

    def _do() -> None:
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

    com_call(_do, timeout=30.0)
    return {"summary": "released", "session_id": session_id, "source": "onec-com"}


def _stub_status(_: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub onec com",
        "ready": False,
        "python_bitness": 0,
        "connection_configured": bool(build_connection_string()),
        "source": "stub",
    }


def _stub_connect(req: ToolInvokeRequest) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    return {
        "summary": "stub connected onec",
        "session_id": session_id,
        "mode": "stub",
        "source": "stub",
    }


def _stub_invoke(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": f"stub invoke {req.payload.get('method')}",
        "session_id": req.payload.get("session_id"),
        "method": req.payload.get("method"),
        "result": {"stub": True},
        "source": "stub",
    }


def _stub_query_tasks(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub COM tasks",
        "session_id": req.payload.get("session_id") or str(uuid.uuid4()),
        "current_user": "stub-user",
        "count": 1,
        "tasks": [
            {
                "number": "00-Л-000000001",
                "description": "stub task",
                "date": "2026-08-12T08:00:00",
                "due_date": "",
                "executor": "stub-user",
            }
        ],
        "mine_only": bool(req.payload.get("mine_only", True)),
        "transport": "com-connector",
        "source": "stub",
    }


def _stub_release(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub released", "session_id": req.payload.get("session_id"), "source": "stub"}


REAL_HANDLERS = {
    "onec.com.status": _onec_status,
    "onec.com.connect": _connect,
    "onec.com.invoke": _invoke,
    "onec.com.query_tasks": _query_tasks,
    "onec.com.release": _release,
}

STUB_HANDLERS = {
    "onec.com.status": _stub_status,
    "onec.com.connect": _stub_connect,
    "onec.com.invoke": _stub_invoke,
    "onec.com.query_tasks": _stub_query_tasks,
    "onec.com.release": _stub_release,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    if _is_windows() and not settings.use_stubs:
        try:
            require_32bit_python()
        except RuntimeError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
    run_app(app, settings)


if __name__ == "__main__":
    main()

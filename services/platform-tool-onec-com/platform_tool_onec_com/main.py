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
    execute_query,
    get_current_user_name,
    get_task_details,
    list_assignment_sources,
    query_docflow_assignments,
    query_performer_tasks,
    query_tasks_period,
    query_work_items,
    require_32bit_python,
    search_metadata,
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
    com_timeout_sec: int = 300


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


def _open_session(session_id: str) -> tuple[str, Any, dict[str, Any], bool]:
    created = False
    sid = session_id.strip()
    if not sid:
        session = connect_session()
        sid = session["session_id"]
        with _lock:
            _sessions[sid] = session
        created = True
    with _lock:
        stored = _sessions.get(sid)
        if not stored:
            raise ValueError("session not found")
        app = stored["object"]
    return sid, app, stored, created


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


def _query_docflow_assignments(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    fio = str(req.payload.get("fio", "") or req.payload.get("user", "")).strip()
    limit = int(req.payload.get("limit") or 100)
    only_open = bool(req.payload.get("only_open", True))

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

        current_user = stored.get("current_user") or get_current_user_name(app)
        actor = fio or current_user
        rows = query_docflow_assignments(
            app,
            user_name=actor,
            limit=limit,
            only_open=only_open,
        )
        return {
            "summary": f"COM docflow assignments for {actor} ({len(rows)} items)",
            "session_id": session_id,
            "current_user": current_user,
            "fio": actor,
            "count": len(rows),
            "tasks": rows,
            "task_source": "td_docflow",
            "only_open": only_open,
            "session_created": created,
            "transport": "com-connector",
            "source": "td-docflow",
        }

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _execute_query(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    query_text = str(req.payload.get("query_text") or req.payload.get("query") or "").strip()
    parameters = req.payload.get("parameters") or {}
    limit = int(req.payload.get("limit") or 200)
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")

    def _do() -> dict[str, Any]:
        sid, app, stored, created = _open_session(session_id)
        result = execute_query(app, query_text, parameters=parameters, limit=limit)
        current_user = stored.get("current_user") or get_current_user_name(app)
        result.update(
            {
                "summary": f"COM query ({result.get('count', 0)} rows)",
                "session_id": sid,
                "current_user": current_user,
                "session_created": created,
                "transport": "com-connector",
                "source": "onec-com",
            }
        )
        return result

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _metadata_search(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    pattern = str(req.payload.get("pattern") or req.payload.get("query") or "").strip()
    kinds_raw = req.payload.get("kinds")
    kinds = [str(item) for item in kinds_raw] if isinstance(kinds_raw, list) else None
    limit = int(req.payload.get("limit") or 50)

    def _do() -> dict[str, Any]:
        sid, app, stored, created = _open_session(session_id)
        hits = search_metadata(app, pattern=pattern, kinds=kinds, limit=limit)
        current_user = stored.get("current_user") or get_current_user_name(app)
        return {
            "summary": f"COM metadata search ({len(hits)} hits)",
            "session_id": sid,
            "current_user": current_user,
            "pattern": pattern,
            "count": len(hits),
            "items": hits,
            "session_created": created,
            "transport": "com-connector",
            "source": "onec-com",
        }

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _list_assignment_sources(_: ToolInvokeRequest) -> dict[str, Any]:
    sources = list_assignment_sources()
    return {
        "summary": f"{len(sources)} assignment sources",
        "count": len(sources),
        "sources": sources,
        "source": "onec-com",
    }


def _query_work_items(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    fio = str(req.payload.get("fio", "") or req.payload.get("user", "")).strip()
    scope = str(req.payload.get("scope") or "all").strip()
    limit = int(req.payload.get("limit") or 100)
    only_open = bool(req.payload.get("only_open", True))

    def _do() -> dict[str, Any]:
        sid, app, stored, created = _open_session(session_id)
        current_user = stored.get("current_user") or get_current_user_name(app)
        actor = fio or current_user
        payload = query_work_items(
            app,
            user_name=actor,
            scope=scope,
            limit=limit,
            only_open=only_open,
        )
        payload.update(
            {
                "summary": f"COM work items ({scope}) for {actor}: {payload.get('count', 0)}",
                "session_id": sid,
                "current_user": current_user,
                "session_created": created,
                "transport": "com-connector",
                "source": "onec-com",
            }
        )
        return payload

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _query_assignments(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    date_from = str(req.payload.get("date_from", "")).strip()
    date_to = str(req.payload.get("date_to", "")).strip()
    mine_only = bool(req.payload.get("mine_only", True))
    limit = int(req.payload.get("limit") or 100)

    if not date_from or not date_to:
        from datetime import date, datetime, timedelta

        today = date.today()
        week_start = today - timedelta(days=today.weekday() + 7)
        week_end = week_start + timedelta(days=7)
        date_from = datetime.combine(week_start, datetime.min.time()).date().isoformat()
        date_to = datetime.combine(week_end, datetime.min.time()).date().isoformat()

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

        rows = query_tasks_period(
            app,
            date_from=date_from,
            date_to=date_to,
            mine_only=mine_only,
            limit=limit,
        )
        current_user = stored.get("current_user") or get_current_user_name(app)
        return {
            "summary": f"COM assignments {date_from}..{date_to} for {current_user}",
            "session_id": session_id,
            "current_user": current_user,
            "date_from": date_from,
            "date_to": date_to,
            "count": len(rows),
            "assignments": rows,
            "mine_only": mine_only,
            "session_created": created,
            "transport": "com-connector",
            "source": "onec-com",
        }

    return com_call(_do, timeout=float(settings.com_timeout_sec))


def _task_details(req: ToolInvokeRequest) -> dict[str, Any]:
    if not _is_windows():
        raise RuntimeError("onec.com is only available on Windows")

    session_id = str(req.payload.get("session_id", "")).strip()
    number = str(req.payload.get("number", "")).strip()
    if not number:
        raise ValueError("number required")

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

        details = get_task_details(app, number=number)
        details.update(
            {
                "summary": f"task details {number}",
                "session_id": session_id,
                "session_created": created,
                "transport": "com-connector",
                "source": "onec-com",
            }
        )
        return details

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


def _stub_execute_query(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub COM query",
        "columns": ["Number", "Description"],
        "rows": [{"Number": "stub-1", "Description": "stub row"}],
        "count": 1,
        "total": 1,
        "query": str(req.payload.get("query_text") or "")[:120],
        "source": "stub",
    }


def _stub_metadata_search(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub metadata search",
        "pattern": str(req.payload.get("pattern") or ""),
        "count": 1,
        "items": [{"kind": "Documents", "name": "ТД_Поручения", "synonym": "Поручения (ТД)"}],
        "source": "stub",
    }


def _stub_list_assignment_sources(_: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub assignment sources",
        "count": 2,
        "sources": [
            {"id": "docflow_protocol", "title": "stub docflow protocol"},
            {"id": "erp_performer_tasks", "title": "stub erp tasks"},
        ],
        "source": "stub",
    }


def _stub_query_work_items(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub work items",
        "fio": "stub-user",
        "scope": str(req.payload.get("scope") or "all"),
        "count": 1,
        "tasks": [
            {
                "number": "stub-1",
                "title": "stub work item",
                "due_at": "",
                "source": "td_задачи_протоколов",
            }
        ],
        "sources": ["td_задачи_протоколов"],
        "source": "stub",
    }


def _stub_release(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub released", "session_id": req.payload.get("session_id"), "source": "stub"}


REAL_HANDLERS = {
    "onec.com.status": _onec_status,
    "onec.com.connect": _connect,
    "onec.com.invoke": _invoke,
    "onec.com.query_tasks": _query_tasks,
    "onec.com.query_docflow_assignments": _query_docflow_assignments,
    "onec.com.query_assignments": _query_assignments,
    "onec.com.execute_query": _execute_query,
    "onec.com.metadata_search": _metadata_search,
    "onec.com.list_assignment_sources": _list_assignment_sources,
    "onec.com.query_work_items": _query_work_items,
    "onec.com.task_details": _task_details,
    "onec.com.release": _release,
}

STUB_HANDLERS = {
    "onec.com.status": _stub_status,
    "onec.com.connect": _stub_connect,
    "onec.com.invoke": _stub_invoke,
    "onec.com.query_tasks": _stub_query_tasks,
    "onec.com.execute_query": _stub_execute_query,
    "onec.com.metadata_search": _stub_metadata_search,
    "onec.com.list_assignment_sources": _stub_list_assignment_sources,
    "onec.com.query_work_items": _stub_query_work_items,
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

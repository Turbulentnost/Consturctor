"""32-bit JSON-line worker for 1C COM (spawned from 64-bit desktop host)."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from platform_tool_com.onec_com import connect_session

_sessions: dict[str, dict[str, Any]] = {}


def _ok(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({"ok": True, **payload}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(message: str) -> None:
    sys.stdout.write(json.dumps({"ok": False, "error": message}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle_connect(req: dict[str, Any]) -> None:
    progid = str(req.get("progid") or "").strip()
    session = connect_session(progid=progid)
    session_id = session["session_id"]
    _sessions[session_id] = session
    _ok(
        {
            "session_id": session_id,
            "mode": session["mode"],
            "progid": session["progid"],
            "connection": session["connection"],
            "python_bitness": session["python_bitness"],
        }
    )


def _handle_invoke(req: dict[str, Any]) -> None:
    session_id = str(req.get("session_id") or "").strip()
    method = str(req.get("method") or "").strip()
    session = _sessions.get(session_id)
    if not session:
        raise ValueError("session not found")
    args = req.get("args") or []
    kwargs = req.get("kwargs") or {}
    if not isinstance(args, list):
        raise ValueError("args must be a list")
    if not isinstance(kwargs, dict):
        raise ValueError("kwargs must be an object")
    obj = session["object"]
    result = getattr(obj, method)(*args, **kwargs)
    if hasattr(result, "__class__"):
        result = str(result)
    _ok({"result": result, "session_id": session_id, "method": method})


def _handle_release(req: dict[str, Any]) -> None:
    session_id = str(req.get("session_id") or "").strip()
    session = _sessions.pop(session_id, None)
    if not session:
        raise ValueError("session not found")
    obj = session.get("object")
    if obj is not None and hasattr(obj, "Quit"):
        try:
            obj.Quit()
        except Exception:
            pass
    _ok({"session_id": session_id, "released": True})


def _handle_ping(_: dict[str, Any]) -> None:
    from platform_tool_com.onec_com import python_bitness

    _ok({"pong": True, "python_bitness": python_bitness()})


_HANDLERS = {
    "ping": _handle_ping,
    "connect": _handle_connect,
    "invoke": _handle_invoke,
    "release": _handle_release,
}


def main() -> None:
    sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            op = str(req.get("op") or "").strip()
            handler = _HANDLERS.get(op)
            if handler is None:
                raise ValueError(f"unknown op: {op}")
            handler(req)
        except Exception as exc:  # noqa: BLE001
            _err(f"{exc}\n{traceback.format_exc(limit=2)}")


if __name__ == "__main__":
    main()

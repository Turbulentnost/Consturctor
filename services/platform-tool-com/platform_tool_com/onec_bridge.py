"""Route 1C COM calls through a 32-bit worker when host Python is 64-bit."""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any

from platform_tool_com.onec_com import find_python32, is_64bit_python

_lock = threading.Lock()
_worker: subprocess.Popen[str] | None = None
_python32: str | None = None


def _require_python32() -> str:
    global _python32
    if _python32:
        return _python32
    path = find_python32()
    if not path:
        raise RuntimeError(
            "ONEC_COM_32BIT_PYTHON_REQUIRED: 1C client is 32-bit. "
            "Install Python 3.12 (32-bit) + pywin32: scripts\\ensure_com_python.cmd"
        )
    _python32 = path
    return path


def _ensure_worker() -> subprocess.Popen[str]:
    global _worker
    if _worker is not None and _worker.poll() is None:
        return _worker

    python = _require_python32()
    _worker = subprocess.Popen(
        [python, "-m", "platform_tool_com.onec_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    _rpc({"op": "ping"})
    return _worker


def _rpc(payload: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    with _lock:
        proc = _ensure_worker()
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            err = (proc.stderr.read(4000) if proc.stderr else "") or "onec worker stopped"
            raise RuntimeError(f"ONEC_COM_WORKER_FAILED: {err}")
        data = json.loads(line)
        if not data.get("ok"):
            raise RuntimeError(str(data.get("error") or "onec worker error"))
        return data


def bridge_connect(*, progid: str = "") -> dict[str, Any]:
    req = {"op": "connect"}
    if progid:
        req["progid"] = progid
    data = _rpc(req)
    return {
        "session_id": data["session_id"],
        "mode": data.get("mode"),
        "progid": data.get("progid"),
        "bridge": True,
    }


def bridge_invoke(session_id: str, method: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
    data = _rpc(
        {
            "op": "invoke",
            "session_id": session_id,
            "method": method,
            "args": args,
            "kwargs": kwargs,
        }
    )
    return data.get("result")


def bridge_release(session_id: str) -> None:
    _rpc({"op": "release", "session_id": session_id})


def should_use_bridge() -> bool:
    return is_64bit_python() and find_python32() is not None

"""Run a published agent on the server, without the Orchestrator app.

The backend starts the same agent_sidecar the app uses (Cursor SDK, the same
tools and limits) and plays the app's part on its stdin/stdout. The sidecar
records the run history and uploads result files through the regular API,
so the run looks like any other scheduled run.

Nobody is there to confirm anything: write confirmations are declined and
agent questions get an answer telling it to decide by its instructions.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
SIDECAR = _REPO_ROOT / "orchestrator" / "desktop-electron" / "pybridge" / "agent_sidecar.py"
DESKTOP_ROOT = _REPO_ROOT / "desktop"
ENTRY = Path(__file__).with_name("headless_agent_sidecar.py")
LOG_DIR = _REPO_ROOT / "backend" / "logs"

RUN_TIMEOUT_S = 3 * 3600
# Tools give up after 10 minutes at most, so this long a silence means the run hung.
SILENCE_TIMEOUT_S = 20 * 60
STALL_RETRIES = 1
_READY_TIMEOUT_S = 120
_SHUTDOWN_WAIT_S = 30
HEADLESS_ANSWER = (
    "Это плановый запуск на сервере, человека рядом нет. "
    "Реши сам по инструкции и продолжай без вопросов."
)

_running: set[str] = set()
_running_lock = threading.Lock()


class HeadlessRunError(RuntimeError):
    pass


class HeadlessRunStalled(HeadlessRunError):
    pass


def _node() -> str:
    return (os.environ.get("CONSTRUCTOR_NODE") or "").strip() or shutil.which("node") or ""


def unavailable_reason() -> str:
    """Empty when this backend can run agents itself; otherwise what is missing."""
    if not SIDECAR.is_file():
        return f"нет {SIDECAR}"
    if not (DESKTOP_ROOT / "sdk-agent" / "node_modules").is_dir():
        return "нет desktop/sdk-agent/node_modules (npm install)"
    if not _node():
        return "не найден node"
    if not (os.environ.get("CURSOR_API_KEY") or settings.cursor_api_key):
        return "нет CURSOR_API_KEY"
    return ""


def is_running(workflow_id: str) -> bool:
    with _running_lock:
        return workflow_id in _running


def _backend_url() -> str:
    port = (os.environ.get("PORT") or "").strip() or str(settings.api_port)
    return f"http://127.0.0.1:{port}"


def _user_token(user_id: str) -> tuple[str, str]:
    from app.core.jwt import create_access_token
    from app.db.session import SessionLocal
    from app.models.user import AppUser
    from app.services.sessions import SERVER_CLIENT

    db = SessionLocal()
    try:
        user = db.get(AppUser, user_id)
        if user is None:
            raise HeadlessRunError(f"Пользователь {user_id} не найден")
        fio = user.fio or ""
        token = create_access_token(
            user_id=user.id,
            fio=fio,
            department=user.department or "",
            position=user.position or "",
            client=SERVER_CLIENT,
        )
        return token, fio
    finally:
        db.close()


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # Without an owner the sidecar does not reap SDK runners of the user's app on this machine.
    env.pop("CONSTRUCTOR_SDK_OWNER", None)
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(DESKTOP_ROOT),
            "CONSTRUCTOR_DESKTOP_ROOT": str(DESKTOP_ROOT),
            "CONSTRUCTOR_SIDECAR_SOURCE": str(SIDECAR),
            "CONSTRUCTOR_INSTANCE": "server",
            "CONSTRUCTOR_NODE": _node(),
            # OpenBLAS starts its thread pool while numpy loads; see _preload_native_modules in the sidecar.
            "OPENBLAS_NUM_THREADS": "1",
        }
    )
    if not env.get("CURSOR_API_KEY") and settings.cursor_api_key:
        env["CURSOR_API_KEY"] = settings.cursor_api_key
    return env


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
            timeout=30,
        )
    if proc.poll() is None:
        proc.kill()


def run_headless(
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    trigger_id: str = "",
    evidence: str = "",
    timeout_s: float = RUN_TIMEOUT_S,
) -> dict[str, Any]:
    """Run one agent task to the end. Blocks; call it from a background thread."""
    reason = unavailable_reason()
    if reason:
        raise HeadlessRunError(f"Сервер не может запустить агента: {reason}")
    with _running_lock:
        if workflow_id in _running:
            raise HeadlessRunError("Этот агент уже выполняется на сервере")
        _running.add(workflow_id)
    try:
        attempt = 0
        while True:
            try:
                return _run(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    message=message,
                    trigger_id=trigger_id,
                    evidence=evidence,
                    timeout_s=timeout_s,
                )
            except HeadlessRunStalled as exc:
                if attempt >= STALL_RETRIES:
                    raise
                attempt += 1
                logger.warning("Headless run of %s hung (%s), starting again", workflow_id, exc)
    finally:
        with _running_lock:
            _running.discard(workflow_id)


def _run(
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    trigger_id: str,
    evidence: str,
    timeout_s: float,
) -> dict[str, Any]:
    token, fio = _user_token(user_id)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"headless-{workflow_id[:8]}-{stamp}.log"
    run_id = f"server-{uuid4()}"
    with log_path.open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(ENTRY)],
            cwd=str(DESKTOP_ROOT),
            env=_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def read() -> None:
            assert proc.stdout is not None
            for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    lines.put(data)
            lines.put(None)

        threading.Thread(target=read, name=f"headless-read-{run_id}", daemon=True).start()

        def send(command: dict[str, Any]) -> None:
            if proc.stdin is None or proc.poll() is not None:
                return
            proc.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            proc.stdin.flush()

        logger.info("Headless run %s: workflow=%s user=%s log=%s", run_id, workflow_id, user_id, log_path)
        try:
            _wait_ready(lines)
            send({"type": "configure", "backendUrl": _backend_url(), "token": token, "login": fio, "fio": fio})
            send(
                {
                    "type": "run",
                    "id": run_id,
                    "workflowId": workflow_id,
                    "message": message,
                    "source": "trigger",
                    "triggerId": trigger_id,
                    "evidence": evidence,
                    "filePaths": [],
                }
            )
            outcome = _serve(lines, send, run_id=run_id, deadline=time.monotonic() + timeout_s)
            if outcome is None:
                send({"type": "cancel", "id": run_id, "workflowId": workflow_id})
                raise HeadlessRunError(f"Запуск не уложился в {int(timeout_s // 60)} мин и остановлен")
            if outcome.get("type") == "stalled":
                send({"type": "cancel", "id": run_id, "workflowId": workflow_id})
                _kill_tree(proc)
                raise HeadlessRunStalled(
                    f"агент молчал {int(SILENCE_TIMEOUT_S // 60)} мин и был остановлен (лог {log_path.name})"
                )
            if outcome.get("type") == "error":
                raise HeadlessRunError(str(outcome.get("message") or "Агент завершился с ошибкой"))
            status = str(outcome.get("status") or "ok")
            logger.info("Headless run %s finished: status=%s run=%s", run_id, status, outcome.get("runRef"))
            return {
                "ok": status == "ok",
                "status": status,
                "run_ref": str(outcome.get("runRef") or ""),
                "answer": str(outcome.get("answer") or ""),
                "log": str(log_path),
            }
        finally:
            send({"type": "shutdown"})
            try:
                proc.wait(timeout=_SHUTDOWN_WAIT_S)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)


def _wait_ready(lines: queue.Queue[dict[str, Any] | None]) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            data = lines.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            break
        if data is None:
            raise HeadlessRunError("Процесс агента завершился при старте (см. лог headless-*.log)")
        if data.get("type") == "ready":
            return
    raise HeadlessRunError("Процесс агента не ответил при старте")


def _serve(
    lines: queue.Queue[dict[str, Any] | None],
    send,
    *,
    run_id: str,
    deadline: float,
    silence_s: float = SILENCE_TIMEOUT_S,
) -> dict[str, Any] | None:
    """Answer the sidecar like the app would, until this run's result or error."""
    last_line = time.monotonic()
    while True:
        now = time.monotonic()
        left = deadline - now
        if left <= 0:
            return None
        if now - last_line >= silence_s:
            return {"type": "stalled"}
        try:
            data = lines.get(timeout=max(0.05, min(left, silence_s - (now - last_line), 60.0)))
        except queue.Empty:
            continue
        last_line = time.monotonic()
        if data is None:
            return {"type": "error", "message": "Процесс агента завершился, не вернув результат"}
        kind = str(data.get("type") or "")
        request_id = str(data.get("requestId") or "")
        if kind == "hitl" and request_id:
            logger.warning("Headless run %s: declined write %s", run_id, data.get("tool"))
            send({"type": "hitl", "requestId": request_id, "approved": False})
        elif kind == "question" and request_id:
            send({"type": "answer", "requestId": request_id, "answer": HEADLESS_ANSWER})
        elif kind in {"result", "error"} and str(data.get("runId") or "") == run_id:
            return data

"""Запуск процесса конфигурации: одна JSON-строка запроса в stdin, построчный JSON событий из stdout."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from app import tool_settings
from app.config import settings
from app.platform.approvals import approvals
from app.platform.attachments import Attachment
from app.platform.configs import PlatformConfig
from app.platform.metrics import Sampler
from app.platform.questions import questions
from app.platform.sessions import store

logger = logging.getLogger(__name__)

CANCEL_GRACE_SECONDS = 5.0
_STDERR_TAIL_LINES = 40
_SECRET_ENV = ("CURSOR_API_KEY", "CONSTRUCTOR_USER_PASSWORD")
# Эти события раннера порождает сам Cursor SDK, раннер уже записал их в журнал как sdk→runner.
_FROM_SDK = {"assistant", "thinking", "tool_call", "usage"}


class ConfigNotRunnable(RuntimeError):
    pass


class _Turn:
    def __init__(
        self, process: subprocess.Popen[bytes], turn: int, on_done: Callable[[], None] | None
    ) -> None:
        self.process = process
        self.turn = turn
        self.on_done = on_done
        self.stderr: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self.lock = threading.Lock()


_turns: dict[str, _Turn] = {}
_turns_lock = threading.Lock()


def _active_turns() -> list[tuple[str, int, int]]:
    with _turns_lock:
        return [
            (session_id, turn.process.pid, turn.turn)
            for session_id, turn in _turns.items()
            if turn.process.poll() is None
        ]


sampler = Sampler(_active_turns)


def _command(config: PlatformConfig) -> list[str]:
    head, *rest = config.entry
    if head == "python":
        executable = sys.executable
    else:
        executable = shutil.which(head) or head
    folder = Path(config.path)
    args = [str(folder / part) if (folder / part).is_file() else part for part in rest]
    return [executable, *args]


def _environment(session_id: str) -> dict[str, str]:
    tool_settings.ensure_applied()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # MCP-сервер конфигурации ставит по ним вопросы человеку (ask_user).
    env["TURBOTESTER_API_URL"] = f"http://127.0.0.1:{settings.api_port}"
    env["TURBOTESTER_SESSION_ID"] = session_id
    session = store.get(session_id)
    if session is not None and session.test_tool:
        env["TURBOTESTER_TEST_TOOL"] = session.test_tool
    if settings.cursor_api_key:
        env["CURSOR_API_KEY"] = settings.cursor_api_key
    if settings.constructor_desktop_dir:
        env["CONSTRUCTOR_DESKTOP_DIR"] = settings.constructor_desktop_dir
    env["CONSTRUCTOR_API_URL"] = settings.constructor_api_url
    env["CONSTRUCTOR_USER_FIO"] = settings.constructor_user_fio
    env["CONSTRUCTOR_USER_PASSWORD"] = settings.constructor_user_password
    return env


def wait_idle(session_id: str, timeout: float = 15.0) -> bool:
    """Ход уже закончен, но раннер ещё закрывает агента: дождаться выхода процесса."""
    with _turns_lock:
        turn = _turns.get(session_id)
    if turn is None:
        return True
    try:
        turn.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def start_turn(
    session_id: str,
    config: PlatformConfig,
    prompt: str,
    title: str,
    attachments: list[Attachment] | None = None,
    *,
    mode: Literal["agent", "plan"] = "agent",
    label: str = "",
    shown: str | None = None,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Запустить ход. on_done вызывается после выхода процесса — в нём можно начать следующий ход."""
    if not config.runnable:
        raise ConfigNotRunnable(config.error or f"У конфигурации {config.title} нет entry в config.json")
    store.note_launch(session_id, model=config.model, entry=list(config.entry), config_path=config.path)
    files = list(attachments or [])
    session = store.begin_turn(session_id, prompt, files, label=label, planning=mode == "plan", shown=shown)
    workspace = store.workspace(session_id)
    request = {
        "type": "run",
        "sessionId": session_id,
        "mode": mode,
        "prompt": prompt,
        "attachments": [
            {"name": item.name, "path": str(workspace / item.path), "mime": item.mime, "image": item.image}
            for item in files
        ],
        "title": title,
        "model": config.model,
        "modelParams": [{"id": item.id, "value": item.value} for item in config.model_params],
        "cwd": str(workspace),
        "resumeAgentId": session.sdk_agent_id,
        "python": sys.executable,
        "storeDir": str(store.sdk_store_dir(config.id)),
    }
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    command = _command(config)
    environment = _environment(session_id)
    try:
        process = subprocess.Popen(
            command,
            cwd=config.path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            creationflags=flags,
        )
    except OSError as exc:
        store.release(session_id)
        store.finish(session_id, "error", f"Не удалось запустить {config.entry[0]}: {exc}")
        return
    store.trace(
        session_id,
        "platform→runner",
        "запуск процесса",
        text=f"PID {process.pid}: {' '.join(command)}",
        data={
            "command": command,
            "cwd": config.path,
            "env": {
                key: ("***" if key in _SECRET_ENV and environment.get(key) else environment.get(key, ""))
                for key in ("CURSOR_API_KEY", "CONSTRUCTOR_DESKTOP_DIR", "CONSTRUCTOR_API_URL",
                            "CONSTRUCTOR_USER_FIO", "CONSTRUCTOR_USER_PASSWORD", "TURBOTESTER_TEST_TOOL")
                if key in environment
            },
        },
    )
    turn = _Turn(process, session.turns, on_done)
    with _turns_lock:
        _turns[session_id] = turn
    assert process.stdin is not None
    process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    process.stdin.flush()
    store.trace(session_id, "platform→runner", "stdin: запрос запуска", text=prompt, data=request)
    sampler.ensure_started()
    threading.Thread(target=_read_stderr, args=(session_id, turn), daemon=True).start()
    threading.Thread(
        target=_read_stdout, args=(session_id, turn), daemon=True, name=f"platform-out-{session_id}"
    ).start()


def cancel_turn(session_id: str) -> bool:
    with _turns_lock:
        turn = _turns.get(session_id)
    if turn is None or turn.process.poll() is not None:
        return False
    try:
        with turn.lock:
            assert turn.process.stdin is not None
            turn.process.stdin.write(b'{"type":"cancel"}\n')
            turn.process.stdin.flush()
        store.trace(session_id, "platform→runner", "stdin: отмена", data={"type": "cancel"})
    except OSError:
        pass
    threading.Timer(CANCEL_GRACE_SECONDS, _kill, args=(session_id, turn)).start()
    return True


def _kill(session_id: str, turn: _Turn) -> None:
    if turn.process.poll() is not None:
        return
    if sys.platform == "win32":
        # MCP-сервер — дочерний процесс раннера; без /T он переживёт отмену.
        subprocess.run(
            ["taskkill", "/PID", str(turn.process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        turn.process.kill()
    store.release(session_id)
    store.finish(session_id, "cancelled")


def _read_stderr(session_id: str, turn: _Turn) -> None:
    assert turn.process.stderr is not None
    for raw in turn.process.stderr:
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            turn.stderr.append(line)
            store.trace(session_id, "runner stderr", "stderr", text=f"{line}\n", merge=True)


def _route(session_id: str, event: dict[str, object]) -> None:
    kind = str(event.get("type") or "")
    if kind == "trace":
        store.trace(
            session_id,
            str(event.get("dir") or "runner"),
            str(event.get("kind") or ""),
            text=str(event.get("text") or ""),
            data=event.get("data"),
            merge=bool(event.get("merge")),
        )
        return
    if kind == "usage" and isinstance(event.get("usage"), dict):
        store.set_usage(session_id, event["usage"])  # type: ignore[arg-type]
    if kind == "status" and isinstance(event.get("tools"), list):
        store.set_tools(session_id, event["tools"])  # type: ignore[arg-type]
    if kind not in _FROM_SDK:
        store.trace(session_id, "runner→platform", kind, text=str(event.get("text") or ""), data=event)
    store.apply(session_id, event)


def _read_stdout(session_id: str, turn: _Turn) -> None:
    assert turn.process.stdout is not None
    for raw in turn.process.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            turn.stderr.append(line)
            store.trace(session_id, "runner stderr", "stdout (не JSON)", text=f"{line}\n", merge=True)
            continue
        if not isinstance(event, dict):
            continue
        # Если поток упадёт, stdout раннера никто не читает: канал переполнится и агент встанет.
        try:
            _route(session_id, event)
        except Exception:
            logger.exception("platform: событие раннера %s не обработано", event.get("type"))
    code = turn.process.wait()
    questions.cancel(session_id)
    for dropped in approvals.cancel(session_id):
        store.settle_approval(session_id, dropped.id, "cancelled")
    store.trace(session_id, "runner→platform", "процесс завершён", text=f"код выхода {code}")
    try:
        assert turn.process.stdin is not None
        turn.process.stdin.close()
    except OSError:
        pass
    tail = "\n".join(list(turn.stderr)[-8:])
    message = f"Процесс конфигурации завершился с кодом {code}" + (f":\n{tail}" if tail else "")
    if code:
        store.release(session_id)
    store.finish(session_id, "error" if code else "finished", message if code else "")
    with _turns_lock:
        if _turns.get(session_id) is turn:
            del _turns[session_id]
    if turn.on_done is None:
        return
    try:
        turn.on_done()
    except Exception as exc:
        logger.exception("platform follow-up failed for %s", session_id)
        store.release(session_id)
        store.finish(session_id, "error", f"Не удалось продолжить запуск: {exc}")

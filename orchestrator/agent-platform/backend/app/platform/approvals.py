"""Разрешения человека на действия агента — как подтверждение команд в Cursor.

Хук preToolUse конфигурации (approval_hook.py) пересылает сюда каждый вызов инструмента.
Чтение, поиск и прочие безопасные действия проходят сразу. Команды терминала, кроме явно
читающих, запись и удаление файлов, вызовы MCP с побочным действием ждут решения человека:
экран сессии показывает запрос вместо поля ввода, хук держит инструмент, пока человек не
разрешит или не отклонит его.

Хук ждёт ответа порциями по WAIT_SECONDS (HTTP-запрос не висит вечно) и сдаётся через
MAX_WAIT_SECONDS — тогда действие отклоняется.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

WAIT_SECONDS = 50.0
MAX_WAIT_SECONDS = 30 * 60
PREVIEW_CHARS = 6000

Kind = Literal["shell", "write", "delete", "mcp"]
Outcome = Literal["waiting", "allowed", "denied", "cancelled", "expired"]

# Инструменты, которые только читают окружение или общаются с человеком.
_SAFE_TOOLS = {
    "read", "grep", "glob", "ls", "semsearch", "codebasesearch", "readlints", "websearch", "webfetch",
    "task", "updatetodos", "readtodos", "todowrite", "createplan", "switchmode", "await", "askquestion",
}
_WRITE_TOOLS = {"write", "edit", "strreplace", "multiedit", "editnotebook", "applyagentdiff", "applypatch"}
_DELETE_TOOLS = {"delete"}
_SHELL_TOOLS = {"shell", "terminal", "runterminalcmd"}
# MCP-инструменты платформы, которые ничего не меняют: вопросы человеку и справка о пользователе.
_SAFE_MCP = ("ask_user", "ask_choice", "wait_answer", "users.current", "users_current")

_READ_COMMANDS = {
    "ls", "dir", "gci", "get-childitem", "cat", "type", "gc", "get-content", "select-string", "sls",
    "findstr", "rg", "grep", "pwd", "get-location", "gl", "echo", "write-output", "write-host",
    "measure-object", "measure", "select-object", "select", "sort-object", "sort", "where-object", "where",
    "format-list", "fl", "format-table", "ft", "test-path", "get-item", "gi", "get-itemproperty",
    "get-date", "whoami", "hostname", "get-command", "gcm", "resolve-path", "split-path", "join-path",
    "out-string", "get-filehash", "head", "tail", "wc", "tree", "get-process", "get-psdrive",
    "group-object", "convertfrom-json", "convertto-json", "get-help", "get-host", "get-culture",
}
_GIT_READ = {"status", "log", "diff", "show", "branch", "rev-parse", "ls-files", "remote", "blame"}
_MUTATING = re.compile(
    r"(?i)(?:^|[\s;|&({])(?:(?:remove|set|new|move|copy|rename|clear|add|start|stop|invoke)-\w+|"
    r"out-file|tee-object|(?:del|erase|rm|rmdir|rd|mkdir|md|ni|mv|cp|ren|iex|sc|ac)(?=\s|$))"
)
_SEGMENTS = re.compile(r"\|\||&&|[|;\n]")


def _first_words(segment: str) -> list[str]:
    return segment.strip().lstrip("(&.").strip().lower().split()


def read_only_command(command: str) -> bool:
    """Команда только читает: каждое звено цепочки — читающая команда, без перенаправлений в файл."""
    text = command.strip()
    if not text or ">" in text or _MUTATING.search(text):
        return False
    for segment in _SEGMENTS.split(text):
        words = _first_words(segment)
        if not words:
            continue
        head = words[0].strip("'\"")
        if head == "git":
            if len(words) < 2 or words[1] not in _GIT_READ:
                return False
        elif head not in _READ_COMMANDS:
            return False
    return True


class ApprovalRequest(BaseModel):
    id: str
    kind: Kind
    tool: str
    title: str
    # Команда терминала, путь файла или имя MCP-инструмента — то, что человек одобряет.
    subject: str
    preview: str = ""
    # Подпись «Разрешать … до конца запуска» и ключ, по которому запоминаем это решение.
    remember_label: str
    remember_key: str
    asked_at: str


def _clip(text: str) -> str:
    return text if len(text) <= PREVIEW_CHARS else f"{text[:PREVIEW_CHARS]}\n…"


def _mcp_name(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    raw = tool_name.strip()
    if raw.lower().startswith("mcp"):
        name = re.sub(r"(?i)^mcp\s*[:_-]?\s*", "", raw)
        return str(tool_input.get("toolName") or tool_input.get("name") or name or raw)
    return None


def _catalog_tool(mcp: str) -> Any:
    """Карточка инструмента TurboTester по имени MCP: users__current ↔ users.current, с префиксом сервера или без."""
    from app.tools.registry import get_tool

    name = re.split(r"[:/]", mcp)[-1].strip()
    name = re.sub(r"(?i)^(custom-user-tools|turbotester|constructor)[-_.]+", "", name)
    return get_tool(name.replace("__", ".")) or get_tool(name)


def classify(tool_name: str, tool_input: dict[str, Any]) -> ApprovalRequest | None:
    """Нужно ли спрашивать человека. None — действие безопасное, разрешаем сразу."""
    key = re.sub(r"[\s_-]", "", tool_name).lower()
    stamp = datetime.now(UTC).isoformat()
    if key in _SAFE_TOOLS:
        return None
    if key in _SHELL_TOOLS:
        command = str(tool_input.get("command") or "").strip()
        if read_only_command(command):
            return None
        head = (_first_words(command) or ["команда"])[0].strip("'\"")
        return ApprovalRequest(
            id=uuid4().hex, kind="shell", tool=tool_name, title="Выполнить команду в терминале",
            subject=_clip(command), remember_label=f"Разрешать «{head}» до конца запуска",
            remember_key=f"shell:{head}", asked_at=stamp,
        )
    if key in _WRITE_TOOLS or key in _DELETE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("target_file") or "")
        name = PureWindowsPath(path).name or path or "файл"
        deleting = key in _DELETE_TOOLS
        content = tool_input.get("content")
        if content is None:
            content = tool_input.get("new_string") or tool_input.get("contents") or ""
        return ApprovalRequest(
            id=uuid4().hex, kind="delete" if deleting else "write", tool=tool_name,
            title=f"Удалить файл {name}" if deleting else f"Записать файл {name}",
            subject=path, preview="" if deleting else _clip(str(content)),
            remember_label="Разрешать удаление файлов до конца запуска" if deleting
            else "Разрешать запись файлов до конца запуска",
            remember_key="delete" if deleting else "write", asked_at=stamp,
        )
    mcp = _mcp_name(tool_name, tool_input)
    if mcp is not None:
        if any(safe in mcp.lower() or safe in json.dumps(tool_input, ensure_ascii=False) for safe in _SAFE_MCP):
            return None
        spec = _catalog_tool(mcp)
        if spec is not None and spec.side_effect == "read" and not spec.requires_approval:
            return None
        if spec is not None:
            mcp = spec.name
        args = tool_input.get("arguments", tool_input.get("args", tool_input))
        return ApprovalRequest(
            id=uuid4().hex, kind="mcp", tool=tool_name,
            title=f"Вызвать инструмент {spec.title or mcp}" if spec is not None else f"Вызвать инструмент {mcp}",
            subject=mcp, preview=_clip(json.dumps(args, ensure_ascii=False, indent=2)),
            remember_label=f"Разрешать «{mcp}» до конца запуска", remember_key=f"mcp:{mcp}", asked_at=stamp,
        )
    return None


class ApprovalError(ValueError):
    pass


@dataclass
class _Entry:
    session_id: str
    request: ApprovalRequest
    started: float
    outcome: Outcome = "waiting"


class ApprovalBoard:
    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._entries: dict[str, _Entry] = {}
        # Что человек разрешил до конца запуска: session_id → ключи remember_key.
        self._remembered: dict[str, set[str]] = {}

    def remembered(self, session_id: str, request: ApprovalRequest) -> bool:
        with self._changed:
            return request.remember_key in self._remembered.get(session_id, set())

    def ask(self, session_id: str, request: ApprovalRequest) -> ApprovalRequest:
        with self._changed:
            self._entries[request.id] = _Entry(session_id, request, time.monotonic())
            self._changed.notify_all()
        return request

    def pending(self, session_id: str) -> ApprovalRequest | None:
        with self._changed:
            for entry in self._entries.values():
                if entry.session_id == session_id and entry.outcome == "waiting":
                    return entry.request
        return None

    def wait(self, session_id: str, approval_id: str, timeout: float) -> tuple[Outcome, bool]:
        """Ждать решения до timeout секунд: (исход, истекло ли ожидание именно сейчас)."""
        deadline = time.monotonic() + max(0.0, min(timeout, WAIT_SECONDS))
        with self._changed:
            entry = self._entries.get(approval_id)
            if entry is None or entry.session_id != session_id:
                raise KeyError(approval_id)
            expired_now = False
            while entry.outcome == "waiting":
                if time.monotonic() - entry.started >= MAX_WAIT_SECONDS:
                    entry.outcome = "expired"
                    expired_now = True
                    self._changed.notify_all()
                    break
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._changed.wait(left)
            return entry.outcome, expired_now

    def decide(self, session_id: str, approval_id: str, *, allow: bool, remember: bool = False) -> ApprovalRequest:
        with self._changed:
            entry = self._entries.get(approval_id)
            if entry is None or entry.session_id != session_id:
                raise KeyError(approval_id)
            if entry.outcome != "waiting":
                raise ApprovalError("По этому запросу уже решили или агент перестал ждать")
            entry.outcome = "allowed" if allow else "denied"
            if allow and remember:
                self._remembered.setdefault(session_id, set()).add(entry.request.remember_key)
            self._changed.notify_all()
            return entry.request

    def cancel(self, session_id: str) -> list[ApprovalRequest]:
        """Снять ожидающие запросы (запуск остановлен). Возвращает снятые."""
        with self._changed:
            dropped = []
            for entry in self._entries.values():
                if entry.session_id == session_id and entry.outcome == "waiting":
                    entry.outcome = "cancelled"
                    dropped.append(entry.request)
            for key in [key for key, entry in self._entries.items() if entry.session_id == session_id]:
                if self._entries[key].outcome != "waiting":
                    del self._entries[key]
            self._remembered.pop(session_id, None)
            self._changed.notify_all()
            return dropped


def hook_reply(outcome: Outcome) -> dict[str, Any]:
    """Ответ для хука: решение и, при отказе, пояснение агенту."""
    if outcome == "allowed":
        return {"status": "allowed", "permission": "allow"}
    if outcome == "waiting":
        return {"status": "waiting"}
    reason = {
        "denied": "Человек отклонил это действие. Не повторяй его; если без него задачу не решить — объясни и спроси, как быть.",
        "expired": f"Человек не ответил на запрос разрешения за {MAX_WAIT_SECONDS // 60} минут — действие отклонено.",
        "cancelled": "Запуск останавливают — действие отменено.",
    }[outcome]
    return {"status": outcome, "permission": "deny", "agent_message": reason}


approvals = ApprovalBoard()

"""MCP stdio-сервер тестировщика инструментов: один инструмент каталога TurboTester и вопросы человеку.

Тестируемый инструмент — TURBOTESTER_TEST_TOOL: карточка и вызов идут через API TurboTester
(TURBOTESTER_API_URL: GET /api/v1/tools/{name}, POST /api/v1/tools/{name}/invoke).
Если инструмент меняет данные (side_effect не read или requires_approval), каждый вызов сначала
ставится человеку вопросом «Разрешить / Отклонить» на экране сессии и выполняется только
после «Разрешить» — проверка здесь, в коде, а не в промпте.

MCP-клиент Cursor SDK ждёт ответа инструмента не дольше 60 с, поэтому ожидание разрешения и
долгий вызов идут порциями: ответ status=waiting_permission / running значит «вызови wait_call».
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

PROTOCOL_OUT = sys.stdout.buffer
sys.stdout = sys.stderr

MAX_TEXT_CHARS = 60_000
WAIT_S = 50.0
ALLOW = "Разрешить"
DENY = "Отклонить"
WAIT_CALL = "wait_call"
ASK_USER = "ask_user"
WAIT_ANSWER = "wait_answer"
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
_SIDE_EFFECTS = {
    "read": "только читает данные",
    "create_draft": "создаёт черновик",
    "write": "изменяет данные",
    "dangerous": "выполняет опасное действие",
}

_send_lock = threading.Lock()
_calls_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-call")
# Прокси системы не нужны: API платформы на этом же компьютере.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SERVICE_TOOLS: list[dict[str, Any]] = [
    {
        "name": WAIT_CALL,
        "description": (
            "Продолжить ждать вызов тестируемого инструмента: разрешение человека "
            "(status=waiting_permission) или результат долгого вызова (status=running). "
            "Вызывай с call_id, пока статус не изменится, ничего не делая между вызовами."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": {"type": "string"}},
            "required": ["call_id"],
        },
    },
    {
        "name": ASK_USER,
        "description": (
            "Спросить человека и дождаться ответа: например, настоящие данные для проверочного вызова "
            "(идентификатор, адрес, номер документа), которых нет в карточке. До 4 вопросов за раз, "
            "у каждого 2–6 коротких вариантов; человек может выбрать вариант или написать свой ответ. "
            "Если в ответе status=waiting — сразу вызови wait_answer с question_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Короткий заголовок: о чём вопрос"},
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "prompt": {"type": "string", "description": "Вопрос целиком, понятный без контекста"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                                    "required": ["id", "label"],
                                },
                            },
                            "allow_multiple": {"type": "boolean"},
                        },
                        "required": ["id", "prompt", "options"],
                    },
                },
            },
            "required": ["questions"],
        },
    },
    {
        "name": WAIT_ANSWER,
        "description": "Продолжить ждать ответ человека на вопрос ask_user. Вызывай, пока status=waiting.",
        "inputSchema": {
            "type": "object",
            "properties": {"question_id": {"type": "string"}},
            "required": ["question_id"],
        },
    },
]


def _log(text: str) -> None:
    print(f"[tool-tester-mcp] {text}", file=sys.stderr, flush=True)


def _mcp_name(name: str) -> str:
    return _NAME_RE.sub("_", name.replace(".", "__"))[:64]


def _api() -> str:
    base = os.environ.get("TURBOTESTER_API_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("Платформа не передала TURBOTESTER_API_URL")
    return base


def _http(method: str, path: str, payload: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{_api()}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with _opener.open(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw).get("detail")
        except (ValueError, AttributeError):
            detail = raw.decode("utf-8", errors="replace")
        return exc.code, {"detail": detail or exc.reason}


def _questions_path(suffix: str = "") -> str:
    session_id = os.environ.get("TURBOTESTER_SESSION_ID", "")
    if not session_id:
        raise RuntimeError("Платформа не передала TURBOTESTER_SESSION_ID — спросить некого")
    return f"/api/v1/platform/sessions/{session_id}/questions{suffix}"


# -- тестируемый инструмент ---------------------------------------------------
@dataclass
class Tool:
    name: str
    exposed: str
    spec: dict[str, Any]

    @property
    def guarded(self) -> bool:
        return self.spec.get("side_effect", "read") != "read" or bool(self.spec.get("requires_approval"))

    def mcp(self) -> dict[str, Any]:
        schema = self.spec.get("input_schema")
        note = (
            " Перед выполнением платформа спрашивает разрешение человека: при status=waiting_permission "
            "сразу вызови wait_call с call_id."
            if self.guarded
            else ""
        )
        return {
            "name": self.exposed,
            "description": f"[Тестируемый инструмент TurboTester: {self.name}] {self.spec.get('description') or ''}{note}",
            "inputSchema": schema if isinstance(schema, dict) and schema.get("type") == "object" else {"type": "object", "properties": {}},
        }


def _load_tool() -> Tool | None:
    name = os.environ.get("TURBOTESTER_TEST_TOOL", "").strip()
    if not name:
        _log("TURBOTESTER_TEST_TOOL не задан")
        return None
    status, body = _http("GET", f"/api/v1/tools/{urllib.parse.quote(name, safe='')}", timeout=20)
    if status != 200 or not isinstance(body, dict):
        _log(f"карточка {name} не получена: HTTP {status} {body}")
        return None
    return Tool(name=name, exposed=_mcp_name(name), spec=body)


@dataclass
class Call:
    id: str
    arguments: dict[str, Any]
    question_id: str = ""
    future: Any = None


_calls: dict[str, Call] = {}


def _invoke(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
    timeout = float(tool.spec.get("timeout_seconds") or 90) + 30
    status, body = _http(
        "POST",
        f"/api/v1/tools/{urllib.parse.quote(tool.name, safe='')}/invoke",
        {"arguments": arguments, "agent_id": "turbotest"},
        timeout=timeout,
    )
    if status >= 400 or not isinstance(body, dict):
        return {"ok": False, "error": f"Платформа вернула HTTP {status}: {body}"}
    return body


def _ask_permission(tool: Tool, call: Call) -> None:
    title = tool.spec.get("title") or tool.name
    effect = _SIDE_EFFECTS.get(str(tool.spec.get("side_effect")), str(tool.spec.get("side_effect")))
    approval = " и требует подтверждения" if tool.spec.get("requires_approval") else ""
    prompt = (
        f"Тестировщик хочет вызвать «{title}» ({tool.name}) — инструмент {effect}{approval}. "
        "Вызов выполнится по-настоящему. Аргументы:\n"
        f"{json.dumps(call.arguments, ensure_ascii=False, indent=2)}"
    )
    status, body = _http(
        "POST",
        _questions_path(),
        {
            "title": f"Разрешить вызов {tool.name}?",
            "questions": [
                {
                    "id": "permission",
                    "prompt": prompt,
                    "options": [{"id": "allow", "label": ALLOW}, {"id": "deny", "label": DENY}],
                }
            ],
        },
        timeout=20,
    )
    if status >= 400 or not isinstance(body, dict) or "id" not in body:
        raise RuntimeError(f"Не удалось спросить разрешение: HTTP {status} {body}")
    call.question_id = str(body["id"])


def _denied(reason: str, comment: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "denied",
        "reason": reason,
        "next_step": (
            "Вызов не выполнен. Не повторяй его с теми же аргументами; учти причину и комментарий "
            "человека и продолжай проверку без этого вызова."
        ),
    }
    if comment:
        result["comment"] = comment
    return result


def _decision(body: dict[str, Any]) -> tuple[bool, str]:
    answers = body.get("answers") if isinstance(body.get("answers"), list) else []
    allowed = any(ALLOW in (item.get("selected") or []) for item in answers)
    comment = "; ".join(str(item.get("text") or "").strip() for item in answers if item.get("text"))
    return allowed, comment


def _advance(tool: Tool, call: Call) -> tuple[dict[str, Any], bool]:
    """Продвинуть вызов в пределах одной порции ожидания: (ответ агенту, это ошибка инструмента)."""
    deadline = time.monotonic() + WAIT_S
    if call.question_id and call.future is None:
        status, body = _http("GET", _questions_path(f"/{call.question_id}?wait={WAIT_S:.0f}"), timeout=WAIT_S + 10)
        if status == 404:
            return _finish(call, _denied("Вопрос снят: запуск останавливают.")), False
        outcome = body.get("status") if isinstance(body, dict) else ""
        if outcome == "waiting":
            return {
                "status": "waiting_permission",
                "call_id": call.id,
                "next_step": "Человек ещё не ответил. Сразу вызови wait_call с этим call_id — больше ничего не делай.",
            }, False
        if outcome != "answered":
            reason = {"skipped": "Человек пропустил вопрос.", "expired": "Человек не ответил вовремя."}.get(
                str(outcome), "Вопрос снят."
            )
            return _finish(call, _denied(reason)), False
        allowed, comment = _decision(body)
        if not allowed:
            return _finish(call, _denied("Человек отклонил вызов.", comment)), False
        call.future = _executor.submit(_invoke, tool, call.arguments)
    if call.future is None:
        call.future = _executor.submit(_invoke, tool, call.arguments)
    try:
        result = call.future.result(timeout=max(1.0, deadline - time.monotonic()))
    except FutureTimeout:
        return {
            "status": "running",
            "call_id": call.id,
            "next_step": "Инструмент ещё выполняется. Сразу вызови wait_call с этим call_id — больше ничего не делай.",
        }, False
    if call.question_id:
        result = {**result, "permission": "разрешено человеком"}
    return _finish(call, result), not bool(result.get("ok", True))


def _finish(call: Call, result: dict[str, Any]) -> dict[str, Any]:
    with _calls_lock:
        _calls.pop(call.id, None)
    return result


def _start_call(tool: Tool, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    call = Call(id=uuid4().hex, arguments=arguments)
    with _calls_lock:
        _calls[call.id] = call
    if tool.guarded:
        _ask_permission(tool, call)
    return _advance(tool, call)


def _wait_call(tool: Tool, call_id: str) -> tuple[dict[str, Any], bool]:
    with _calls_lock:
        call = _calls.get(call_id)
    if call is None:
        return {"status": "unknown", "next_step": "Такого ожидающего вызова нет: он уже завершён или не начинался."}, True
    return _advance(tool, call)


# -- вопросы человеку ---------------------------------------------------------
def _wait_answer(question_id: str) -> dict[str, Any]:
    status, body = _http("GET", _questions_path(f"/{question_id}?wait={WAIT_S:.0f}"), timeout=WAIT_S + 10)
    if status == 404:
        return {"status": "cancelled", "next_step": "Вопрос снят. Продолжай с разумными допущениями."}
    if status >= 400:
        raise RuntimeError(f"Платформа отклонила вопрос: {body}")
    return body


def _ask(arguments: dict[str, Any]) -> dict[str, Any]:
    status, body = _http(
        "POST",
        _questions_path(),
        {"title": arguments.get("title") or "", "questions": arguments.get("questions") or []},
        timeout=20,
    )
    if status >= 400 or not isinstance(body, dict):
        raise RuntimeError(f"Платформа отклонила вопрос: {body}")
    return _wait_answer(str(body["id"])) if "id" in body else body


# -- протокол -----------------------------------------------------------------
def _result_text(result: Any) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= MAX_TEXT_CHARS:
        return text
    folder = Path(os.environ.get("TURBOTESTER_SESSION_DIR") or os.getcwd()) / "tool_results"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"result_{len(list(folder.iterdir())) + 1}.json"
    target.write_text(text, encoding="utf-8")
    return json.dumps(
        {
            "result_file": str(target),
            "size_chars": len(text),
            "preview": text[:4000],
            "next_step": "Полный ответ в result_file. Читай его частями встроенным Read.",
        },
        ensure_ascii=False,
    )


def _send(payload: dict[str, Any]) -> None:
    with _send_lock:
        PROTOCOL_OUT.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        PROTOCOL_OUT.flush()


def _reply(request_id: Any, text: str, is_error: bool = False) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}})


def _handle_call(request_id: Any, tool: Tool | None, exposed: str, arguments: dict[str, Any]) -> None:
    def run() -> None:
        try:
            if exposed == ASK_USER:
                _reply(request_id, json.dumps(_ask(arguments), ensure_ascii=False))
            elif exposed == WAIT_ANSWER:
                _reply(request_id, json.dumps(_wait_answer(str(arguments.get("question_id") or "")), ensure_ascii=False))
            elif tool is not None and exposed == WAIT_CALL:
                result, failed = _wait_call(tool, str(arguments.get("call_id") or ""))
                _reply(request_id, _result_text(result), failed)
            elif tool is not None and exposed == tool.exposed:
                result, failed = _start_call(tool, arguments)
                _reply(request_id, _result_text(result), failed)
            else:
                _reply(request_id, f"Неизвестный инструмент: {exposed}", True)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            _reply(request_id, str(exc) or exc.__class__.__name__, True)

    threading.Thread(target=run, name=f"call-{exposed}", daemon=True).start()


def main() -> int:
    try:
        tool = _load_tool()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _log(f"карточка инструмента не загружена: {exc}")
        tool = None
    tools = ([tool.mcp(), SERVICE_TOOLS[0]] if tool else []) + SERVICE_TOOLS[1:]
    _log(f"тестируемый инструмент: {tool.name if tool else 'нет'}; защищён разрешением: {bool(tool and tool.guarded)}")

    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        method = str(message.get("method") or "")
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}

        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "tester", "version": "1.0.0"},
                    },
                }
            )
        elif method.startswith("notifications/"):
            continue
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}})
        elif method == "tools/call":
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            _handle_call(request_id, tool, str(params.get("name") or ""), arguments)
        elif request_id is not None:
            _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

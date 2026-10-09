"""MCP stdio-сервер конфигураций 1 и 2: реализованные инструменты TurboTester, кроме EXCLUDED_TOOLS.

Протокол MCP stdio: одна JSON-RPC строка на сообщение.
Каталог и исполнение — backend TurboTester (TURBOTESTER_API_URL): тот же каталог, что на вкладке
«Инструменты» (GET /api/v1/tools), и тот же вызов, что ручной запуск оттуда
(POST /api/v1/tools/{name}/invoke). Настройки окружения (вкладка «Настройки»), вход в Constructor
под «Пользователем агентов» и таймауты инструментов — на стороне backend. agent_id вызова —
id сессии: файловые инструменты работают в папке сессии.

Свои инструменты платформы — ask_user и ask_choice: вопрос человеку ставится в TurboTester
(TURBOTESTER_SESSION_ID) и показывается на экране сессии. Вызов ждёт ответа сам, сколько нужно:
раннер отдаёт инструменты агенту как customTools, а у них SDK не ограничивает длительность.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

PROTOCOL_OUT = sys.stdout.buffer
# Канал протокола должен оставаться чистым: случайный print уходит в stderr.
sys.stdout = sys.stderr

MAX_TEXT_CHARS = 60_000
CATALOG_TIMEOUT_S = 30.0
# Сверх таймаута инструмента: backend сам обрывает вызов по timeout_seconds и отвечает ошибкой.
CALL_SLACK_S = 30.0
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
_send_lock = threading.Lock()

# Ответ человека ждём порциями внутри одного вызова: HTTP-запрос к платформе не висит дольше ANSWER_WAIT_S.
ANSWER_WAIT_S = 50.0
ASK_USER = "ask_user"
ASK_CHOICE = "ask_choice"
ASK_TOOLS: list[dict[str, Any]] = [
    {
        "name": ASK_USER,
        "description": (
            "Задать человеку уточняющие вопросы и дождаться ответа — и при составлении плана, и при работе. "
            "Встроенный askQuestion в этом запуске не работает: если инструкция просит спросить через "
            "askQuestion, спрашивай этим инструментом. Спрашивай, когда без ответа придётся угадывать "
            "(какие данные взять, кому отправить, объём, критерий успеха, выбор между вариантами); "
            "мелочи решай сам. Все нужные сейчас вопросы — в одном вызове (до 4), у каждого 2–6 "
            "коротких вариантов; человек может выбрать вариант или написать свой ответ. "
            "Вызов сам ждёт ответа человека, сколько потребуется, — повторять его не нужно."
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
                            "allow_multiple": {"type": "boolean", "description": "Можно выбрать несколько вариантов"},
                        },
                        "required": ["id", "prompt", "options"],
                    },
                },
            },
            "required": ["questions"],
        },
    },
    {
        "name": ASK_CHOICE,
        "description": (
            "Попросить человека выбрать ответ из готового списка. type=radio — ровно один вариант, "
            "type=checkbox — один или несколько. Список может быть длинным (до 1000 строк): человек "
            "ищет по нему и прокручивает, поэтому отдавай все варианты сразу, без страниц. Простые "
            "варианты — options (строки). Записи с полями — columns (заголовки) и rows (ячейки "
            "в том же порядке), например номер, дата, тема, руководитель. Своего ответа текстом "
            "человек дать не может — для открытых вопросов есть ask_user. В ответе answers[0].selected — "
            "выбранные строки, selected_ids — их номера (o1, o2… по порядку). Один вариант — не выбор: "
            "тогда спроси ask_user, делать ли это (если всё же передашь один, человек ответит «да / нет»). "
            "Вызов сам ждёт ответа человека, сколько потребуется, — повторять его не нужно."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Короткий заголовок: о чём выбор"},
                "question": {"type": "string", "description": "Вопрос целиком, понятный без контекста"},
                "type": {
                    "type": "string",
                    "enum": ["radio", "checkbox"],
                    "description": "radio — выбрать один вариант, checkbox — несколько",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Простые варианты по порядку; их id — o1, o2, … Не вместе с rows",
                },
                "columns": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {"type": "string"},
                    "description": "Заголовки колонок для rows, например [\"Номер\", \"Дата\", \"Тема\", \"Руководитель\"]",
                },
                "rows": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                    "description": "Варианты-строки: ячейки в порядке columns; их id — o1, o2, …",
                },
            },
            "required": ["question", "type"],
        },
    },
]

# Инструменты каталога, которые агенту Cursor SDK не отдаём: их заменяют встроенные (Shell, запись
# файлов, Glob, WebSearch) или они рассчитаны на агентов Constructor, а не на сессии платформы.
EXCLUDED_TOOLS = {
    "code.write_python",
    "code.run_python",
    "workspace.powershell_run",
    "excel.list_files",
    "get_current_date",
    "agent.wait",
    "agent.schedule",
    "agent.schedule.cancel",
    "web_search",
    "browser.search_web",
}

_SIDE_EFFECTS = {
    "create_draft": "создаёт черновик или файл",
    "write": "меняет данные во внешней системе",
    "dangerous": "необратимое действие",
}


def _log(text: str) -> None:
    print(f"[turbotester-mcp] {text}", file=sys.stderr, flush=True)


def _api_base() -> str:
    base = os.environ.get("TURBOTESTER_API_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError("Платформа не передала TURBOTESTER_API_URL")
    return base


def _session_id() -> str:
    return os.environ.get("TURBOTESTER_SESSION_ID", "").strip()


def _mcp_name(name: str) -> str:
    return _NAME_RE.sub("_", name.replace(".", "__"))[:64]


def _schema(raw: Any) -> dict[str, Any]:
    """agent_id подставляет платформа: агенту его заполнять не нужно."""
    schema = dict(raw) if isinstance(raw, dict) else {"type": "object", "properties": {}}
    properties = schema.get("properties")
    if isinstance(properties, dict) and "agent_id" in properties:
        schema["properties"] = {key: value for key, value in properties.items() if key != "agent_id"}
        if isinstance(schema.get("required"), list):
            schema["required"] = [key for key in schema["required"] if key != "agent_id"]
    return schema


def _description(spec: dict[str, Any]) -> str:
    text = str(spec.get("description") or spec.get("summary") or spec.get("name") or "").strip()
    effect = _SIDE_EFFECTS.get(str(spec.get("side_effect") or ""))
    return f"{text}\n\nПобочное действие: {effect}." if effect else text


def _load_tools() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    import httpx

    with httpx.Client(timeout=CATALOG_TIMEOUT_S, trust_env=False) as client:
        response = client.get(f"{_api_base()}/api/v1/tools")
    response.raise_for_status()
    tools: list[dict[str, Any]] = []
    specs: dict[str, dict[str, Any]] = {}
    for spec in response.json().get("items") or []:
        original = str(spec.get("name") or "").strip()
        exposed = _mcp_name(original)
        if not original or not spec.get("available") or exposed in specs or exposed in {ASK_USER, ASK_CHOICE}:
            continue
        if original in EXCLUDED_TOOLS:
            continue
        specs[exposed] = spec
        tools.append({"name": exposed, "description": _description(spec), "inputSchema": _schema(spec.get("input_schema"))})
    return tools, specs


def _result_text(result: Any) -> str:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
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


def _invoke(spec: dict[str, Any], arguments: dict[str, Any]) -> tuple[bool, str]:
    import httpx

    name = str(spec["name"])
    payload: dict[str, Any] = {"arguments": arguments}
    if _session_id():
        payload["agent_id"] = _session_id()
    timeout = float(spec.get("timeout_seconds") or 90) + CALL_SLACK_S
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.post(f"{_api_base()}/api/v1/tools/{name}/invoke", json=payload)
    if response.status_code >= 400:
        return False, f"Платформа не выполнила {name}: HTTP {response.status_code} {response.text[:500]}"
    body = response.json()
    if body.get("ok"):
        return True, _result_text(body.get("result"))
    return False, str(body.get("error") or f"{name} завершился ошибкой")


def _platform(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx

    session_id = _session_id()
    if not session_id:
        raise RuntimeError("Платформа не передала TURBOTESTER_SESSION_ID — спросить некого")
    url = f"{_api_base()}/api/v1/platform/sessions/{session_id}/questions{path}"
    with httpx.Client(timeout=ANSWER_WAIT_S + 8, trust_env=False) as client:
        response = client.request(method, url, json=payload)
    if response.status_code == 404:
        return {"status": "cancelled", "next_step": "Вопрос снят. Продолжай с разумными допущениями."}
    if response.status_code >= 400:
        detail = response.json().get("detail") if "json" in response.headers.get("content-type", "") else response.text
        raise RuntimeError(f"Платформа отклонила вопрос: {detail}")
    return response.json()


def _ask_and_wait(title: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
    question = _platform("POST", "", {"title": title or "", "questions": items})
    if "id" not in question:
        return question
    while True:
        result = _platform("GET", f"/{question['id']}?wait={ANSWER_WAIT_S}")
        if result.get("status") != "waiting":
            return result


def _ask(arguments: dict[str, Any]) -> dict[str, Any]:
    return _ask_and_wait(arguments.get("title"), arguments.get("questions") or [])


def _ask_choice(arguments: dict[str, Any]) -> dict[str, Any]:
    kind = str(arguments.get("type") or "").strip().lower()
    if kind not in ("radio", "checkbox"):
        raise RuntimeError("type должен быть radio (один вариант) или checkbox (несколько)")
    columns = [str(column).strip() for column in arguments.get("columns") or []]
    rows = arguments.get("rows") or []
    if rows:
        if not columns:
            raise RuntimeError("Для rows нужны заголовки columns")
        options = [
            {"id": f"o{number}", "cells": [str(cell) for cell in (row if isinstance(row, list) else [row])]}
            for number, row in enumerate(rows, start=1)
        ]
    else:
        labels = [str(item).strip() for item in arguments.get("options") or [] if str(item).strip()]
        options = [{"id": f"o{number}", "label": label} for number, label in enumerate(labels, start=1)]
        columns = []
    item = {
        "id": "q1",
        "prompt": str(arguments.get("question") or ""),
        "options": options,
        "choice": kind,
        "columns": columns,
    }
    return _ask_and_wait(arguments.get("title"), [item])


def _call_in_background(request_id: Any, exposed: str, arguments: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
    """Каждый вызов — в своём потоке: цикл протокола отвечает на ping, инструменты идут параллельно."""

    def run() -> None:
        try:
            if exposed == ASK_USER:
                ok, text = True, json.dumps(_ask(arguments), ensure_ascii=False)
            elif exposed == ASK_CHOICE:
                ok, text = True, json.dumps(_ask_choice(arguments), ensure_ascii=False)
            elif exposed in specs:
                ok, text = _invoke(specs[exposed], arguments)
            else:
                ok, text = False, f"Неизвестный инструмент: {exposed}"
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            ok, text = False, str(exc) or exc.__class__.__name__
        _reply(request_id, {"content": [{"type": "text", "text": text}], "isError": not ok})

    threading.Thread(target=run, name=f"call-{exposed}", daemon=True).start()


def _send(payload: dict[str, Any]) -> None:
    with _send_lock:
        PROTOCOL_OUT.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        PROTOCOL_OUT.flush()


def _reply(request_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _fail(request_id: Any, text: str, code: int = -32000) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}})


def main() -> int:
    try:
        tools, specs = _load_tools()
        _log(f"инструментов TurboTester: {len(tools)}")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        tools, specs = [], {}
        _log(f"каталог инструментов не загружен: {exc}")
    tools = [*ASK_TOOLS, *tools]

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
            _reply(
                request_id,
                {
                    "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "turbotester", "version": "1.0.0"},
                },
            )
        elif method.startswith("notifications/"):
            continue
        elif method == "ping":
            _reply(request_id, {})
        elif method == "tools/list":
            _reply(request_id, {"tools": tools})
        elif method == "tools/call":
            exposed = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            _call_in_background(request_id, exposed, arguments, specs)
        elif request_id is not None:
            _fail(request_id, f"Unknown method: {method}", code=-32601)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Хук preToolUse Cursor SDK: спрашивает человека в TurboTester, можно ли выполнить действие агента.

Раннер кладёт в рабочую папку сессии .cursor/hooks.json с этим скриптом. SDK запускает его
перед каждым вызовом инструмента и передаёт в stdin JSON: tool_name, tool_input.

Решает платформа (POST /sessions/{id}/approvals): безопасное разрешает сразу, остальное
показывает человеку. Пока человек думает, скрипт ждёт порциями (GET …?wait=50) — инструмент
агента всё это время стоит. Нет связи с платформой — действие запрещается.

Запуск: python approval_hook.py <хост:порт API> <id сессии>
Адрес без «http://»: SDK читает hooks.json как JSON с комментариями и обрезает строку на «//».
"""

from __future__ import annotations

import codecs
import json
import sys
import time
import urllib.error
import urllib.request

WAIT_SECONDS = 50
GIVE_UP_SECONDS = 31 * 60
# Прокси из окружения не нужен и ломает запросы к 127.0.0.1.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _raw_byte(error: UnicodeError) -> tuple[bytes, int]:
    if not isinstance(error, UnicodeEncodeError):
        raise error
    chunk = error.object[error.start : error.end]
    if any(ord(char) > 0xFF for char in chunk):
        raise error
    return bytes(ord(char) for char in chunk), error.end


codecs.register_error("turbotester-raw-byte", _raw_byte)


def _repair(text: str) -> str:
    """Windows PowerShell читает файл с данными хука как ANSI (cp1251), хотя SDK пишет его в UTF-8.

    Кириллица приходит «РџСЂРё…»; обратное перекодирование возвращает исходный текст, а настоящий
    русский текст через него не проходит (это не UTF-8) и остаётся как есть.
    """
    try:
        return text.encode("cp1251", errors="turbotester-raw-byte").decode("utf-8")
    except UnicodeError:
        return text


def _call(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    request.add_header("Content-Type", "application/json")
    with _opener.open(request, timeout=WAIT_SECONDS + 30) as response:
        return json.loads(response.read().decode("utf-8"))


def _decide(api: str, session_id: str, hook_input: dict) -> dict:
    base = f"{api.rstrip('/')}/api/v1/platform/sessions/{session_id}/approvals"
    reply = _call(base, {"tool_name": hook_input.get("tool_name", ""), "tool_input": hook_input.get("tool_input") or {}})
    approval_id = reply.get("id", "")
    deadline = time.monotonic() + GIVE_UP_SECONDS
    while reply.get("status") == "waiting" and time.monotonic() < deadline:
        reply = _call(f"{base}/{approval_id}?wait={WAIT_SECONDS}")
    if reply.get("status") == "waiting":
        return {"permission": "deny", "agent_message": "Человек не ответил на запрос разрешения — действие отклонено."}
    decision = {"permission": reply.get("permission", "deny")}
    if reply.get("agent_message"):
        decision["agent_message"] = reply["agent_message"]
    return decision


def main() -> None:
    api, session_id = sys.argv[1], sys.argv[2]
    if "://" not in api:
        api = f"http://{api}"
    raw = _repair(sys.stdin.buffer.read().decode("utf-8-sig", errors="replace"))
    hook_input = json.loads(raw or "{}")
    try:
        decision = _decide(api, session_id, hook_input)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        decision = {
            "permission": "deny",
            "agent_message": f"Платформа TurboTester недоступна, разрешение не получено: {exc}",
        }
    # Только ASCII: PowerShell пересобирает вывод хука в кодировке консоли.
    sys.stdout.write(json.dumps(decision))
    sys.stdout.flush()


if __name__ == "__main__":
    main()

"""Короткая проверка свободного условия триггера через LLM + desktop tools."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.agent_passport import llm as passport_llm
from app.services.triggers.service import get_trigger
from app.services.workflows.cursor_tools import (
    extract_tool_calls,
    invoke_creation_tool,
    tools_prompt_block,
)

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5
_JSON_RE = re.compile(r"\{[^{}]*\"matched\"[^{}]*\}", re.DOTALL)

SYSTEM = (
    "Ты проверяешь, выполняется ли условие для запуска агента Constructor прямо сейчас. "
    "Не выполняй рабочую задачу агента. Не вызывай agent.schedule. "
    "Если нужны данные с компьютера пользователя — вызови инструмент блоком:\n"
    "```constructor_tool\n"
    '{"name": "outlook.search_mail", "arguments": {"query": "..."}}\n'
    "```\n"
    "Когда данных достаточно, верни ТОЛЬКО JSON без markdown:\n"
    '{"matched": true, "changed": "что именно изменилось", "evidence": "на каких данных это видно"}\n'
    "matched=true только если условие уже истинно в этот момент.\n"
    "Если matched=true, поле changed обязательно и должно назвать конкретное изменение: "
    "объект (проект, задача, письмо, файл), идентификатор/название, какое поле, было → стало. "
    "Пример: «В проекте «Дашборды» (file_id 344) срок вехи сдвинулся с 12.08 на 19.08». "
    "Запрещены общие фразы: «условие выполнено», «данные обновились», «что-то изменилось»."
)


def check_trigger_condition(
    db: Session,
    *,
    user_id: str,
    trigger_id: str,
    emit: Callable[[dict], None],
    workflow_id: str = "",
) -> dict[str, Any]:
    row = get_trigger(db, user_id=user_id, trigger_id=trigger_id)
    condition = (row.condition_text or "").strip()
    if not condition:
        return {"matched": True, "evidence": "Нет условия — срабатывание по времени"}
    emit({"type": "status", "text": "Проверяю условие триггера…"})
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM + "\n\n" + tools_prompt_block()},
        {
            "role": "user",
            "content": (
                f"Условие:\n{condition}\n\n"
                f"Агент: {row.workflow_id}\n"
                "Проверь, выполняется ли оно сейчас. "
                "Если да — в changed напиши, что именно изменилось, с названиями и id."
            ),
        },
    ]
    last_text = ""
    for _round in range(MAX_ROUNDS):
        try:
            last_text = passport_llm._chat_completions(messages, timeout=60.0, max_tokens=800)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trigger check LLM failed: %s", exc)
            return {"matched": False, "evidence": f"Не удалось проверить условие: {exc}"}
        calls = extract_tool_calls(last_text)
        parsed = _parse_verdict(last_text)
        if parsed is not None and not calls:
            return parsed
        if not calls:
            if parsed is not None:
                return parsed
            return {"matched": False, "evidence": (last_text or "Условие не подтверждено")[:400]}
        results: list[str] = []
        for call in calls[:3]:
            name = str(call.get("name") or "")
            if name.startswith("agent.schedule"):
                results.append(f"{name}: запрещён во время проверки условия")
                continue
            emit({"type": "status", "text": f"Проверяю через {name}…"})
            try:
                result = invoke_creation_tool(
                    tool=name,
                    arguments=call.get("arguments") or {},
                    on_event=_adapt_emit(emit),
                    workflow_id=workflow_id or row.workflow_id,
                )
                results.append(f"{name}: {json.dumps(result, ensure_ascii=False, default=str)[:1500]}")
            except Exception as exc:  # noqa: BLE001
                results.append(f"{name}: ошибка {exc}")
        messages.append({"role": "assistant", "content": last_text})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Результаты инструментов:\n"
                    + "\n".join(results)
                    + "\n\nВерни JSON matched/changed/evidence. "
                    "В changed напиши, что именно изменилось (объект, id, было → стало)."
                ),
            }
        )
    parsed = _parse_verdict(last_text)
    if parsed is not None:
        return parsed
    return {"matched": False, "evidence": "Проверка не успела подтвердить условие"}


def _adapt_emit(emit: Callable[[dict], None]):
    def on_event(event_type: str, text: str = "", extra: dict | None = None) -> None:
        payload = {"type": event_type}
        if text:
            payload["text"] = text
        if extra:
            payload.update(extra)
        emit(payload)

    return on_event


def _parse_verdict(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        candidates.insert(0, fence.group(1))
    match = _JSON_RE.search(raw)
    if match:
        candidates.insert(0, match.group(0))
    for item in candidates:
        try:
            data = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "matched" in data:
            changed = str(data.get("changed") or data.get("change") or "").strip()
            evidence = str(data.get("evidence") or "").strip()
            detail = changed or evidence
            return {
                "matched": bool(data.get("matched")),
                "changed": changed[:1500],
                "evidence": detail[:1500],
            }
    return None

"""Закрытие (подтверждение) задачи протокола в 1С.

Задачи протоколов лежат в независимом регистре сведений
``InformationRegister_ТД_ЗадачиПротоколов`` и пишутся POST-ом всего среза записи
(так же, как их создаёт ``create_protocol.post_protocol_task``). Чтобы закрыть
задачу, перечитываем её текущий срез и POST-им обратно с выставленными
``Выполнена``/``Подтверждена`` и датой исполнения — остальные ресурсы сохраняем,
иначе независимый регистр обнулит их при перезаписи.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.vendors.aiagentback.tools.onec.connection import CONFIG, ODataConfig, create_session
from app.vendors.aiagentback.tools.onec.get_meetings import entity_url
from app.vendors.aiagentback.tools.onec.get_porucheniya import (
    PROTOCOL_DOCUMENT,
    PROTOCOL_TASKS_REGISTER,
    fetch_register_rows_for_protocol_keys,
    is_empty_key,
)

# Поля-срезы, которые 1С возвращает при GET, но не принимает при POST записи
# независимого регистра (служебные / вычисляемые). Их убираем из тела.
_NON_WRITABLE_FIELDS = frozenset(
    {
        "Recorder",
        "Recorder_Key",
        "Recorder_Type",
        "Регистратор",
        "Регистратор_Key",
        "Регистратор_Type",
        "Active",
        "Активность",
        "LineNumber",
        "НомерСтроки",
    }
)


def _now_1c() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _match_task_row(
    rows: list[dict[str, Any]],
    *,
    task_id: str | None,
    item_number: str | int | None,
) -> dict[str, Any] | None:
    """Find the register slice for a task by its stable id, else by item number."""
    normalized_id = str(task_id or "").strip()
    if normalized_id:
        for row in rows:
            if str(row.get("ИдентификаторЗадачи") or "").strip() == normalized_id:
                return row
    # task_key фронта для задач протокола = ИдентификаторЗадачи, а если его нет —
    # НомерПунктаПротокола. Поэтому task_id тоже пробуем как номер пункта.
    candidate_numbers = [
        str(value or "").strip()
        for value in (item_number, task_id)
        if str(value or "").strip()
    ]
    for number in candidate_numbers:
        for row in rows:
            if str(row.get("НомерПунктаПротокола") or "").strip() == number:
                return row
    return None


def _build_confirm_body(row: dict[str, Any]) -> dict[str, Any]:
    """Copy the existing slice and mark it done + confirmed, preserving resources."""
    body: dict[str, Any] = {
        key: value for key, value in row.items() if key not in _NON_WRITABLE_FIELDS
    }
    # Гарантируем тип измерения-ссылки на протокол (нужен 1С при записи среза).
    if body.get("Протокол_Key") and not body.get("Протокол_Type"):
        body["Протокол_Type"] = f"StandardODATA.{PROTOCOL_DOCUMENT}"
    body["Выполнена"] = True
    body["Подтверждена"] = True
    if not str(body.get("ДатаИсполнения") or "").strip():
        body["ДатаИсполнения"] = _now_1c()
    # Некоторые конфигурации хранят дату подтверждения отдельно — заполняем,
    # только если поле реально присутствует в срезе (не выдумываем схему).
    if "ДатаПодтверждения" in body and not str(body.get("ДатаПодтверждения") or "").strip():
        body["ДатаПодтверждения"] = _now_1c()
    return body


def confirm_protocol_task(
    *,
    protocol_ref: str,
    task_id: str | None = None,
    item_number: str | int | None = None,
    config: ODataConfig = CONFIG,
) -> dict[str, Any]:
    """Mark a protocol task as done+confirmed in 1С and return a short result.

    Raises ``LookupError`` if the task slice is not found and ``RuntimeError`` on
    a failed 1С write.
    """
    normalized_ref = (protocol_ref or "").strip()
    if is_empty_key(normalized_ref):
        raise ValueError("Не указан Ref_Key протокола для закрытия задачи")
    if not str(task_id or "").strip() and not str(item_number or "").strip():
        raise ValueError("Не указан идентификатор или номер пункта задачи протокола")

    session = create_session(config)
    rows = fetch_register_rows_for_protocol_keys(session, config, {normalized_ref})
    row = _match_task_row(rows, task_id=task_id, item_number=item_number)
    if row is None:
        raise LookupError(
            "Задача протокола не найдена в 1С: "
            f"protocol={normalized_ref}, task_id={task_id}, item={item_number}"
        )

    body = _build_confirm_body(row)
    response = session.post(
        f"{entity_url(config.url, PROTOCOL_TASKS_REGISTER)}?$format=json",
        json=body,
        timeout=config.timeout,
    )
    if not response.ok:
        raise RuntimeError(
            "Ошибка закрытия задачи протокола в 1С: "
            f"HTTP {response.status_code}: {response.text[:1000]}"
        )
    return {
        "protocol_ref": normalized_ref,
        "task_id": str(row.get("ИдентификаторЗадачи") or "").strip() or None,
        "item_number": row.get("НомерПунктаПротокола"),
        "completed": True,
        "confirmed": True,
        "completed_date": body.get("ДатаИсполнения"),
    }

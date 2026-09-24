"""Create Document_ТД_Протокол (meeting protocol) in 1C ERP via OData.

Mirrors the form Документ.ТД_Протокол.Форма.ФормаСписка / ФормаДокумента:
- header: Тема совещания (Catalog_ТД_ТемыСовещаний), Руководитель / Проверяющий /
  Подготовил (Catalog_Пользователи), Подразделение, Проект, Кабинет, Гриф доступа,
  Вид совещания, дата + время начала/окончания, отчётный период;
- «Присутствующие» -> ПрисутствующиеНаСовещании (Участник_Key = Catalog_ФизическиеЛица);
- «Повестка совещания» -> ПовесткаСовещания (Вопрос, Ответственный_Key = физлицо);
- «Решения» -> Решения (ТекстРешения, ДатаНачала, ДатаОкончания);
- «Поставленные задачи» -> ПеременныеЗадачиПротокола (Задача, Ответственный_Key = физлицо,
  Автор_Key = пользователь, ДатаПостановкиЗадачи, срок в ДатаФактическогоИсполнения).

Field / catalog mapping discovered live from $metadata and existing protocols
(see scripts/_probe_td_protocol_result.json). The document is created as a draft
(Posted=false, Статус=«Подготовлен») so that the secretary reviews it in 1C.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

from app.services.erp_assignments import (
    PROBE_MARK,
    _parse_day,
    build_probe_topic,
    delete_probe_document,
    is_probe_topic,
    pick_user_row,
)

PROTOCOL_ENTITY = "Document_ТД_Протокол"
THEME_ENTITY = "Catalog_ТД_ТемыСовещаний"
PERSON_ENTITY = "Catalog_ФизическиеЛица"
USER_ENTITY = "Catalog_Пользователи"
ROOM_ENTITY = "Catalog_CRM_Помещения"
ACCESS_ENTITY = "Catalog_ТД_ГрифыДоступа"
PROJECT_ENTITY = "Catalog_Проекты"
DEPARTMENT_ENTITY = "Catalog_СтруктураПредприятия"

DEFAULT_ACCESS_LABEL = "Общий"
DEFAULT_MEETING_TYPE = "Отчетное"
DRAFT_STATUS = "Подготовлен"
TOOL_NAME = "onec.meeting_protocol_write"

_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_UNDEFINED_TYPE = "StandardODATA.Undefined"
_EMPTY_DATE = "0001-01-01T00:00:00"
_MAX_ROWS = 200


class ProtocolWriteError(RuntimeError):
    pass


# --------------------------------------------------------------------------- OData


def _odata_get(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _fetch_odata_list

    return _fetch_odata_list(args)


def _odata_post(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_post

    return _odata_post(args)


def _odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_patch

    return _odata_patch(args)


def _escape(value: str) -> str:
    return str(value or "").replace("'", "''")


def _looks_like_guid(value: Any) -> bool:
    text = str(value or "").strip()
    return len(text) == 36 and text.count("-") == 4 and not text.startswith(_EMPTY_GUID)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (result.get("value") or []) if isinstance(row, dict)]


def _search_by_description(entity: str, query: str, *, select: str = "") -> dict[str, Any] | None:
    text = _clean(query)
    if not text:
        return None
    args: dict[str, Any] = {
        "entity": entity,
        "top": 20,
        "filter": f"substringof('{_escape(text)}', Description) and DeletionMark eq false",
    }
    if select:
        args["select"] = select
    rows = _rows(_odata_get(args))
    chosen = pick_user_row(rows, text)
    if chosen is None and rows:
        # substring match on a shorter form (e.g. «Иванов И.» or first two words)
        words = text.split()
        if len(words) >= 2:
            shorter = " ".join(words[:2])
            chosen = pick_user_row(rows, shorter)
    return chosen


# --------------------------------------------------------------------------- resolvers
# Module-level so tests can monkeypatch them without touching OData.


def resolve_user_card(query: str) -> dict[str, Any]:
    """Catalog_Пользователи row: ref_key, fio, person_key, department_key."""
    text = _clean(query)
    if not text:
        raise ProtocolWriteError("Нужно ФИО пользователя 1С")
    if _looks_like_guid(text):
        rows = _rows(_odata_get({"entity": USER_ENTITY, "ref_key": text, "top": 1}))
        row = rows[0] if rows else {"Ref_Key": text, "Description": text}
    else:
        row = _search_by_description(USER_ENTITY, text)
        if row is None:
            raise ProtocolWriteError(f"Пользователь 1С не найден: {text}")
    return {
        "ref_key": str(row.get("Ref_Key") or ""),
        "fio": str(row.get("Description") or text),
        "person_key": str(row.get("ФизическоеЛицо_Key") or ""),
        "department_key": str(row.get("Подразделение_Key") or ""),
    }


def resolve_person(query: str) -> dict[str, str]:
    """Catalog_ФизическиеЛица ref by FIO. Falls back through Catalog_Пользователи."""
    text = _clean(query)
    if not text:
        raise ProtocolWriteError("Нужно ФИО участника")
    if _looks_like_guid(text):
        return {"ref_key": text, "fio": text}
    row = _search_by_description(PERSON_ENTITY, text, select="Ref_Key,Description,Code")
    if row is not None and _looks_like_guid(row.get("Ref_Key")):
        return {"ref_key": str(row["Ref_Key"]), "fio": str(row.get("Description") or text)}
    user = _search_by_description(USER_ENTITY, text)
    if user is not None and _looks_like_guid(user.get("ФизическоеЛицо_Key")):
        return {
            "ref_key": str(user["ФизическоеЛицо_Key"]),
            "fio": str(user.get("Description") or text),
        }
    raise ProtocolWriteError(f"Физическое лицо 1С не найдено: {text}")


def resolve_theme(query: str) -> dict[str, Any] | None:
    text = _clean(query)
    if not text:
        return None
    if _looks_like_guid(text):
        rows = _rows(_odata_get({"entity": THEME_ENTITY, "ref_key": text, "top": 1}))
        return rows[0] if rows else None
    return _search_by_description(THEME_ENTITY, text)


def resolve_ref(entity: str, query: str) -> str:
    text = _clean(query)
    if not text:
        return ""
    if _looks_like_guid(text):
        return text
    row = _search_by_description(entity, text, select="Ref_Key,Description")
    return str(row.get("Ref_Key") or "") if row else ""


# --------------------------------------------------------------------------- helpers


def _first(args: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = args.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _day_value(raw: Any, *, end: bool = False) -> str:
    text = _clean(raw)
    if not text:
        return ""
    try:
        parsed = _parse_day(text, end=end)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolWriteError(f"Непонятная дата: {text}") from exc
    if parsed is None:
        return ""
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def _time_value(raw: Any) -> str:
    """«10:30» / «10.30» / ISO datetime -> 0001-01-01T10:30:00 (1C time-only)."""
    text = _clean(raw)
    if not text:
        return ""
    if "T" in text and len(text) >= 16:
        text = text.split("T", 1)[1][:5]
    text = text.replace(".", ":").replace("-", ":")
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError) as exc:
        raise ProtocolWriteError(f"Непонятное время: {raw}") from exc
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ProtocolWriteError(f"Непонятное время: {raw}")
    return f"0001-01-01T{hour:02d}:{minute:02d}:00"


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [line for line in (part.strip() for part in value.splitlines()) if line]
    return [value]


def _text_of(item: Any, *keys: str) -> str:
    if isinstance(item, dict):
        for key in keys:
            value = _clean(item.get(key))
            if value:
                return value
        return ""
    return _clean(item)


def _field_of(item: Any, *keys: str) -> str:
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = _clean(item.get(key))
        if value:
            return value
    return ""


# --------------------------------------------------------------------------- body


def build_protocol_create_body(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_onec_ref: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (odata_body, meta). meta lists resolved names and what could not be resolved."""
    unresolved: list[str] = []
    meta: dict[str, Any] = {"unresolved": unresolved}

    topic = _clean(_first(args, "topic", "theme", "subject", "ТемаСовещания"))
    theme_key = _clean(_first(args, "theme_key", "ТемаСовещания_Key"))
    theme: dict[str, Any] | None = None
    if theme_key and _looks_like_guid(theme_key):
        theme = resolve_theme(theme_key)
    elif topic:
        theme = resolve_theme(topic)
    if theme:
        theme_key = str(theme.get("Ref_Key") or "")
        meta["theme"] = str(theme.get("Description") or topic)
    else:
        theme_key = ""
        if topic:
            unresolved.append(f"тема совещания «{topic}» (нет в Catalog_ТД_ТемыСовещаний)")

    meeting_day = _day_value(_first(args, "date", "meeting_date", "Дата", "ДатаСовещания"))
    if not meeting_day:
        meeting_day = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    day_only = meeting_day[:10] + "T00:00:00"

    # ----- people
    leader_query = _clean(_first(args, "leader", "head", "Руководитель"))
    leader: dict[str, Any] | None = None
    if leader_query:
        leader = resolve_user_card(leader_query)
    elif theme and _looks_like_guid(theme.get("Руководитель_Key")):
        leader = resolve_user_card(str(theme["Руководитель_Key"]))
    elif actor_onec_ref and _looks_like_guid(actor_onec_ref):
        leader = resolve_user_card(actor_onec_ref)
    elif actor_fio:
        leader = resolve_user_card(actor_fio)
    if leader is None:
        raise ProtocolWriteError("Нужен руководитель совещания (leader) — ФИО пользователя 1С")
    meta["leader"] = leader["fio"]

    responsible_query = _clean(
        _first(args, "responsible", "reviewer", "checker", "Проверяющий", "Ответственный")
    )
    if responsible_query:
        responsible = resolve_user_card(responsible_query)
    elif theme and _looks_like_guid(theme.get("Проверяющий_Key")):
        responsible = resolve_user_card(str(theme["Проверяющий_Key"]))
    else:
        responsible = leader
    meta["responsible"] = responsible["fio"]

    prepared_query = _clean(_first(args, "prepared_by", "secretary", "Подготовил"))
    if prepared_query:
        prepared = resolve_user_card(prepared_query)
    elif actor_onec_ref and _looks_like_guid(actor_onec_ref):
        prepared = resolve_user_card(actor_onec_ref)
    elif actor_fio:
        try:
            prepared = resolve_user_card(actor_fio)
        except ProtocolWriteError:
            prepared = leader
    else:
        prepared = leader
    meta["prepared_by"] = prepared["fio"]

    # ----- references
    department_key = _clean(_first(args, "department_key", "Подразделение_Key"))
    department_query = _clean(_first(args, "department", "Подразделение"))
    if not department_key and department_query:
        department_key = resolve_ref(DEPARTMENT_ENTITY, department_query)
        if not department_key:
            unresolved.append(f"подразделение «{department_query}»")
    if not department_key and theme and _looks_like_guid(theme.get("Подразделение_Key")):
        department_key = str(theme["Подразделение_Key"])
    if not department_key:
        department_key = leader.get("department_key") or ""

    project_key = _clean(_first(args, "project_key", "Проект_Key"))
    project_query = _clean(_first(args, "project", "Проект"))
    if not project_key and project_query:
        project_key = resolve_ref(PROJECT_ENTITY, project_query)
        if not project_key:
            unresolved.append(f"проект «{project_query}»")
    if not project_key and theme and _looks_like_guid(theme.get("Проект_Key")):
        project_key = str(theme["Проект_Key"])

    room_key = _clean(_first(args, "room_key", "Кабинет_Key"))
    room_query = _clean(_first(args, "room", "location", "place", "Кабинет"))
    if not room_key and room_query:
        room_key = resolve_ref(ROOM_ENTITY, room_query)
        if not room_key:
            unresolved.append(f"кабинет «{room_query}»")
    if not room_key and theme and _looks_like_guid(theme.get("Кабинет_Key")):
        room_key = str(theme["Кабинет_Key"])

    access_query = _clean(_first(args, "access", "ГрифДоступа")) or DEFAULT_ACCESS_LABEL
    access_key = _clean(_first(args, "access_key", "ГрифДоступа_Key")) or resolve_ref(
        ACCESS_ENTITY, access_query
    )

    meeting_type = _clean(_first(args, "meeting_type", "ВидСовещания"))
    if not meeting_type and theme:
        meeting_type = _clean(theme.get("ВидСовещания"))
    meeting_type = meeting_type or DEFAULT_MEETING_TYPE

    # ----- participants
    participants_in = _as_list(_first(args, "participants", "attendees", "Присутствующие"))
    participants: list[dict[str, Any]] = []
    participant_names: list[str] = []
    seen_person_keys: set[str] = set()
    for item in participants_in[:_MAX_ROWS]:
        name = _text_of(item, "name", "fio", "person", "ФИО")
        key = _field_of(item, "person_key", "ref_key", "Участник_Key")
        if not name and not key:
            continue
        try:
            person = {"ref_key": key, "fio": name} if _looks_like_guid(key) else resolve_person(name)
        except ProtocolWriteError:
            unresolved.append(f"участник «{name}»")
            continue
        if person["ref_key"] in seen_person_keys:
            continue
        seen_person_keys.add(person["ref_key"])
        participants.append(
            {"LineNumber": str(len(participants) + 1), "Участник_Key": person["ref_key"]}
        )
        participant_names.append(person["fio"])

    # ----- agenda
    agenda_rows: list[dict[str, Any]] = []
    for item in _as_list(_first(args, "agenda", "questions", "Повестка"))[:_MAX_ROWS]:
        question = _text_of(item, "question", "text", "title", "Вопрос")
        if not question:
            continue
        row: dict[str, Any] = {
            "LineNumber": str(len(agenda_rows) + 1),
            "Вопрос": question,
            "Вопрос_Type": "Edm.String",
            "ОтметкаОНаличииПриложений": "",
        }
        owner = _field_of(item, "responsible", "executor", "owner", "Ответственный")
        if owner:
            try:
                row["Ответственный_Key"] = resolve_person(owner)["ref_key"]
            except ProtocolWriteError:
                unresolved.append(f"ответственный по вопросу «{owner}»")
        agenda_rows.append(row)

    # ----- decisions
    decision_rows: list[dict[str, Any]] = []
    for item in _as_list(_first(args, "decisions", "Решения"))[:_MAX_ROWS]:
        text = _text_of(item, "text", "decision", "title", "ТекстРешения")
        if not text:
            continue
        row = {
            "LineNumber": str(len(decision_rows) + 1),
            "ТекстРешения": text,
            "ДокументОснование": "",
            "ДокументОснование_Type": _UNDEFINED_TYPE,
            "РезультатРешения": "",
            "Отправлено": False,
            "ДатаНачала": day_only,
            "Отменено": False,
            "НаличиеАртефакта": False,
        }
        due = _day_value(_field_of(item, "due", "deadline", "ДатаОкончания"), end=True)
        if due:
            row["ДатаОкончания"] = due
        decision_rows.append(row)

    # ----- tasks («Поставленные задачи»)
    task_rows: list[dict[str, Any]] = []
    for item in _as_list(_first(args, "tasks", "assignments", "Задачи", "Поручения"))[:_MAX_ROWS]:
        text = _text_of(item, "text", "task", "title", "Задача", "what")
        if not text:
            continue
        row = {
            "LineNumber": str(len(task_rows) + 1),
            "НомерПунктаПротокола": str(_field_of(item, "item", "point", "НомерПунктаПротокола") or len(task_rows) + 1),
            "Задача": text,
            "Автор_Key": leader["ref_key"],
            "ДатаПостановкиЗадачи": day_only,
            "Отправлена": False,
            "Примечание": _field_of(item, "note", "comment", "Примечание"),
            "ПроцессID": "",
            "Приоритет": _field_of(item, "priority", "Приоритет"),
        }
        executor = _field_of(item, "executor", "responsible", "who", "assignee", "Ответственный")
        if executor:
            try:
                row["Ответственный_Key"] = resolve_person(executor)["ref_key"]
            except ProtocolWriteError:
                unresolved.append(f"исполнитель задачи «{executor}»")
        due = _day_value(_field_of(item, "due", "deadline", "term", "Срок"), end=True)
        if due:
            row["ДатаФактическогоИсполнения"] = due
        task_rows.append(row)

    comment = _clean(_first(args, "comment", "Комментарий"))
    if unresolved:
        note = "Не сопоставлено с 1С: " + "; ".join(unresolved)
        comment = f"{comment}\n{note}".strip() if comment else note

    body: dict[str, Any] = {
        "Date": meeting_day,
        "ДатаСоздания": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "Posted": False,
        "DeletionMark": False,
        "Статус": _clean(_first(args, "status", "Статус")) or DRAFT_STATUS,
        "ВидСовещания": meeting_type,
        "Руководитель_Key": leader["ref_key"],
        "Ответственный_Key": responsible["ref_key"],
        "Подготовил_Key": prepared["ref_key"],
        "Комментарий": comment,
        "КраткийСоставДокумента": "; ".join(participant_names)[:1000],
        "ЗадачиРазосланы": False,
        "ДокументОснование": "",
        "ДокументОснование_Type": _UNDEFINED_TYPE,
        "ПрисутствующиеНаСовещании": participants,
        "ПовесткаСовещания": agenda_rows,
        "Решения": decision_rows,
        "ПеременныеЗадачиПротокола": task_rows,
    }
    if theme_key:
        body["ТемаСовещания_Key"] = theme_key
    if department_key:
        body["Подразделение_Key"] = department_key
    if project_key:
        body["Проект_Key"] = project_key
    if room_key:
        body["Кабинет_Key"] = room_key
    if access_key:
        body["ГрифДоступа_Key"] = access_key
    start = _time_value(_first(args, "time_start", "start", "ВремяНачалаСовещания"))
    end = _time_value(_first(args, "time_end", "end", "ВремяОкончанияСовещания"))
    if start:
        body["ВремяНачалаСовещания"] = start
    if end:
        body["ВремяОкончанияСовещания"] = end
    next_day = _day_value(_first(args, "next_meeting_date", "ДатаСледующегоСовещания"))
    if next_day:
        body["ДатаСледующегоСовещания"] = next_day
    period_from = _day_value(_first(args, "report_period_from", "ОтчетныйПериодДатаНачала"))
    period_to = _day_value(_first(args, "report_period_to", "ОтчетныйПериодДатаОкончания"))
    body["ОтчетныйПериодДатаНачала"] = period_from or day_only
    body["ОтчетныйПериодДатаОкончания"] = period_to or period_from or day_only

    meta.update(
        {
            "participants": participant_names,
            "agenda_count": len(agenda_rows),
            "decisions_count": len(decision_rows),
            "tasks_count": len(task_rows),
            "meeting_type": meeting_type,
        }
    )
    return body, meta


# --------------------------------------------------------------------------- read back


def _iso_day(value: Any) -> str:
    text = _clean(value)
    if not text or text.startswith("0001-01-01"):
        return ""
    return text[:10]


def _iso_clock(value: Any) -> str:
    text = _clean(value)
    if "T" not in text:
        return ""
    clock = text.split("T", 1)[1][:5]
    return clock if len(clock) == 5 and clock[2] == ":" else ""


def _description_of(entity: str, key: Any, cache: dict[str, str]) -> str:
    guid = _clean(key)
    if not _looks_like_guid(guid):
        return ""
    cache_key = f"{entity}:{guid}"
    if cache_key in cache:
        return cache[cache_key]
    name = ""
    try:
        rows = _rows(_odata_get({"entity": entity, "ref_key": guid, "top": 1}))
        if rows:
            name = _clean(rows[0].get("Description") or rows[0].get("Наименование"))
    except Exception:  # noqa: BLE001
        name = ""
    cache[cache_key] = name
    return name


def _protocol_rows(card: dict[str, Any], section: str) -> list[dict[str, Any]]:
    rows = card.get(section)
    if not isinstance(rows, list):
        parts = card.get("tabular_parts")
        if isinstance(parts, dict):
            rows = parts.get(f"{PROTOCOL_ENTITY}_{section}") or parts.get(section)
    if not isinstance(rows, list):
        return []
    ordered = [row for row in rows if isinstance(row, dict)]
    ordered.sort(key=lambda row: int(str(row.get("LineNumber") or "0") or 0))
    return ordered


def read_protocol_card(ref_key: str) -> dict[str, Any]:
    guid = _clean(ref_key)
    if not _looks_like_guid(guid):
        raise ProtocolWriteError("ref_key протокола должен быть GUID")
    rows = _rows(_odata_get({"entity": PROTOCOL_ENTITY, "ref_key": guid, "top": 1}))
    if not rows:
        raise ProtocolWriteError(f"Протокол {guid} не найден в 1С")
    return rows[0]


def read_protocol_form(ref_key: str) -> dict[str, Any]:
    """Document_ТД_Протокол → form fields (names instead of GUIDs) for the desktop editor."""
    card = read_protocol_card(ref_key)
    cache: dict[str, str] = {}

    def user_fio(key: Any) -> str:
        return _description_of(USER_ENTITY, key, cache)

    def person_fio(key: Any) -> str:
        return _description_of(PERSON_ENTITY, key, cache)

    theme_key = _clean(card.get("ТемаСовещания_Key"))
    theme_name = ""
    theme_obj = card.get("ТемаСовещания")
    if isinstance(theme_obj, dict):
        theme_name = _clean(theme_obj.get("Description"))
    elif isinstance(theme_obj, str) and not _looks_like_guid(theme_obj):
        theme_name = _clean(theme_obj)
    if not theme_name:
        theme_name = _description_of(THEME_ENTITY, theme_key, cache)

    participants = [
        person_fio(row.get("Участник_Key"))
        for row in _protocol_rows(card, "ПрисутствующиеНаСовещании")
    ]
    agenda = [
        {
            "question": _clean(row.get("Вопрос")),
            "responsible": person_fio(row.get("Ответственный_Key")),
        }
        for row in _protocol_rows(card, "ПовесткаСовещания")
        if _clean(row.get("Вопрос"))
    ]
    decisions = [
        {
            "text": _clean(row.get("ТекстРешения")),
            "due": _iso_day(row.get("ДатаОкончания")),
        }
        for row in _protocol_rows(card, "Решения")
        if _clean(row.get("ТекстРешения"))
    ]
    tasks = [
        {
            "text": _clean(row.get("Задача")),
            "executor": person_fio(row.get("Ответственный_Key")),
            "due": _iso_day(row.get("ДатаФактическогоИсполнения")),
            "priority": _clean(row.get("Приоритет")),
            "note": _clean(row.get("Примечание")),
            "item": _clean(row.get("НомерПунктаПротокола")),
        }
        for row in _protocol_rows(card, "ПеременныеЗадачиПротокола")
        if _clean(row.get("Задача"))
    ]

    status = _clean(card.get("Статус"))
    posted = bool(card.get("Posted"))
    form = {
        "topic": theme_name,
        "theme_key": theme_key if _looks_like_guid(theme_key) else "",
        "date": _iso_day(card.get("Date")),
        "time_start": _iso_clock(card.get("ВремяНачалаСовещания")),
        "time_end": _iso_clock(card.get("ВремяОкончанияСовещания")),
        "room": _description_of(ROOM_ENTITY, card.get("Кабинет_Key"), cache),
        "next_meeting_date": _iso_day(card.get("ДатаСледующегоСовещания")),
        "leader": user_fio(card.get("Руководитель_Key")),
        "responsible": user_fio(card.get("Ответственный_Key")),
        "prepared_by": user_fio(card.get("Подготовил_Key")),
        "meeting_type": _clean(card.get("ВидСовещания")),
        "report_period_from": _iso_day(card.get("ОтчетныйПериодДатаНачала")),
        "report_period_to": _iso_day(card.get("ОтчетныйПериодДатаОкончания")),
        "access": _description_of(ACCESS_ENTITY, card.get("ГрифДоступа_Key"), cache),
        "department": _description_of(DEPARTMENT_ENTITY, card.get("Подразделение_Key"), cache),
        "project": _description_of(PROJECT_ENTITY, card.get("Проект_Key"), cache),
        "participants": [name for name in participants if name],
        "agenda": agenda,
        "decisions": decisions,
        "tasks": tasks,
        "comment": _clean(card.get("Комментарий")),
    }
    return {
        "ref_key": _clean(card.get("Ref_Key")) or _clean(ref_key),
        "number": _clean(card.get("Number")),
        "date": _clean(card.get("Date")),
        "status": status,
        "posted": posted,
        "editable": (not posted) and status in ("", DRAFT_STATUS),
        "entity": PROTOCOL_ENTITY,
        "form": form,
    }


# --------------------------------------------------------------------------- handlers

_CREATE_ONLY_FIELDS = ("ДатаСоздания", "Posted", "DeletionMark", "Статус", "Подготовил_Key")


def build_protocol_update_body(
    args: dict[str, Any],
    card: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_onec_ref: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """PATCH body for an existing draft: same mapping as create, minus creation-only fields."""
    body, meta = build_protocol_create_body(
        args, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref
    )
    for field in _CREATE_ONLY_FIELDS:
        body.pop(field, None)
    old_comment = str(card.get("Комментарий") or "")
    markers = re.findall(r"outlook:\S+", old_comment)
    new_comment = str(body.get("Комментарий") or "")
    for marker in markers:
        if marker not in new_comment:
            new_comment = f"{new_comment}\n{marker}".strip()
    body["Комментарий"] = new_comment
    return body, meta


def _ref_from_write(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if not data:
        data = result
    ref_key = str(
        data.get("Ref_Key") or result.get("erp_document_id") or result.get("ref_key") or ""
    ).strip()
    number = str(data.get("Number") or result.get("number") or "").strip()
    return ref_key, number


def handle_protocol_write(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    actor_onec_ref: str = "",
    **_: Any,
) -> dict[str, Any]:
    _ = actor_user_id
    action = _clean(args.get("action") or "create").casefold()
    if action == "probe":
        return probe_protocol_write(args, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref)
    if action == "update":
        return _update_protocol(args, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref)
    if action != "create":
        raise ProtocolWriteError("action: create | update | probe")
    body, meta = build_protocol_create_body(
        args, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref
    )
    if not (body["ПовесткаСовещания"] or body["Решения"] or body["ПеременныеЗадачиПротокола"]):
        raise ProtocolWriteError(
            "Протокол пуст: нужна хотя бы повестка, решения или задачи (agenda / decisions / tasks)"
        )
    result = _odata_post({"entity": PROTOCOL_ENTITY, "body": body})
    ref_key, number = _ref_from_write(result)
    summary = f"Создан протокол {number or ref_key} в 1С (черновик, статус «{body['Статус']}»)"
    if meta["unresolved"]:
        summary += f"; не сопоставлено: {len(meta['unresolved'])}"
    return {
        "summary": summary,
        "entity": PROTOCOL_ENTITY,
        "number": number,
        "ref_key": ref_key,
        "erp_document_id": ref_key,
        "status": body["Статус"],
        "posted": False,
        "meta": meta,
        "unresolved": meta["unresolved"],
        "body": body,
        "source": "odata",
    }


def _update_protocol(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_onec_ref: str = "",
) -> dict[str, Any]:
    ref_key = _clean(_first(args, "ref_key", "Ref_Key", "erp_document_id"))
    if not _looks_like_guid(ref_key):
        raise ProtocolWriteError("Для action=update нужен ref_key протокола (GUID)")
    card = read_protocol_card(ref_key)
    status = _clean(card.get("Статус"))
    if bool(card.get("Posted")) or status not in ("", DRAFT_STATUS):
        raise ProtocolWriteError(
            f"Протокол {card.get('Number') or ref_key} уже проведён (статус «{status or 'проведён'}») — "
            "правки только в 1С"
        )
    body, meta = build_protocol_update_body(
        args, card, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref
    )
    if not (body["ПовесткаСовещания"] or body["Решения"] or body["ПеременныеЗадачиПротокола"]):
        raise ProtocolWriteError(
            "Протокол пуст: нужна хотя бы повестка, решения или задачи (agenda / decisions / tasks)"
        )
    _odata_patch({"entity": PROTOCOL_ENTITY, "ref_key": ref_key, "body": body})
    number = _clean(card.get("Number"))
    summary = f"Обновлён протокол {number or ref_key} в 1С (черновик, статус «{status or DRAFT_STATUS}»)"
    if meta["unresolved"]:
        summary += f"; не сопоставлено: {len(meta['unresolved'])}"
    return {
        "summary": summary,
        "entity": PROTOCOL_ENTITY,
        "number": number,
        "ref_key": ref_key,
        "erp_document_id": ref_key,
        "status": status or DRAFT_STATUS,
        "posted": False,
        "updated": True,
        "meta": meta,
        "unresolved": meta["unresolved"],
        "body": body,
        "source": "odata",
    }


def stub_protocol_write(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = _clean(args.get("action") or "create").casefold()
    if action == "probe":
        return {
            "ok": True,
            "cleaned": True,
            "source": "stub",
            "summary": "stub write probe: create protocol -> verify -> delete",
            "recipe": protocol_write_recipe(source="stub"),
            "test_left": False,
        }
    tasks = _as_list(_first(args, "tasks", "assignments") or [])
    if action == "update":
        return {
            "summary": "stub: протокол в 1С не обновлён (OData не настроена)",
            "entity": PROTOCOL_ENTITY,
            "number": "ПРОТОКОЛ-STUB-001",
            "ref_key": _clean(args.get("ref_key")) or "00000000-0000-0000-0000-000000000002",
            "status": DRAFT_STATUS,
            "posted": False,
            "updated": False,
            "meta": {"tasks_count": len(tasks), "unresolved": []},
            "unresolved": [],
            "source": "stub",
        }
    return {
        "summary": "stub: протокол в 1С не создан (OData не настроена)",
        "entity": PROTOCOL_ENTITY,
        "number": "ПРОТОКОЛ-STUB-001",
        "ref_key": "00000000-0000-0000-0000-000000000002",
        "status": DRAFT_STATUS,
        "posted": False,
        "meta": {"tasks_count": len(tasks), "unresolved": []},
        "unresolved": [],
        "source": "stub",
    }


def protocol_write_recipe(*, source: str = "odata") -> dict[str, Any]:
    return {
        "entity": PROTOCOL_ENTITY,
        "tool": TOOL_NAME,
        "create": {
            "action": "create",
            "via": "odata_post",
            "fields": [
                "Date",
                "ТемаСовещания_Key",
                "Руководитель_Key",
                "Ответственный_Key",
                "Подготовил_Key",
                "ВидСовещания",
                "ПрисутствующиеНаСовещании",
                "ПовесткаСовещания",
                "Решения",
                "ПеременныеЗадачиПротокола",
            ],
        },
        "update": {
            "action": "update",
            "via": "odata_patch",
            "fields": ["ref_key", "header без ДатаСоздания/Posted/Статус/Подготовил_Key", "табличные части целиком"],
            "guard": "только Posted=false и Статус «Подготовлен»",
        },
        "delete": {"via": "odata_delete"},
        "source": source,
    }


def probe_protocol_write(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_onec_ref: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Create a CONSTRUCTOR_PROBE protocol, read it back, delete it. Never leaves data."""
    from app.services.onec_tools import odata_configured

    if not odata_configured():
        return stub_protocol_write({**args, "action": "probe"})
    workflow_id = _clean(args.get("workflow_id") or args.get("agent_id"))
    mark = build_probe_topic(workflow_id)
    leader = _clean(args.get("leader") or args.get("customer") or actor_fio)
    if not leader and not actor_onec_ref:
        raise ProtocolWriteError("Для пробы нужен leader (ФИО пользователя 1С) или ФИО сессии")
    probe_args: dict[str, Any] = {
        "topic": _clean(args.get("topic")),
        "leader": leader,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time_start": "10:00",
        "time_end": "10:30",
        "participants": [leader] if leader else [],
        "agenda": [f"{mark}: тестовый вопрос повестки"],
        "decisions": [{"text": f"{mark}: тестовое решение", "due": datetime.now().strftime("%Y-%m-%d")}],
        "tasks": [
            {
                "text": f"{mark}: тестовая задача",
                "executor": leader,
                "due": datetime.now().strftime("%Y-%m-%d"),
            }
        ],
        "comment": mark,
    }
    created_key = ""
    try:
        body, meta = build_protocol_create_body(
            probe_args, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref
        )
        created = _odata_post({"entity": PROTOCOL_ENTITY, "body": body})
        created_key, number = _ref_from_write(created)
        if not created_key:
            raise ProtocolWriteError("Create не вернул Ref_Key")
        check = _rows(_odata_get({"entity": PROTOCOL_ENTITY, "ref_key": created_key, "top": 1}))
        row = check[0] if check else {}
        if not is_probe_topic(str(row.get("Комментарий") or "")):
            raise ProtocolWriteError("Create вернул чужую карточку, не тест")
        verified = {
            "number": number or str(row.get("Number") or ""),
            "status": str(row.get("Статус") or ""),
            "participants": len(row.get("ПрисутствующиеНаСовещании") or []),
            "agenda": len(row.get("ПовесткаСовещания") or []),
            "decisions": len(row.get("Решения") or []),
            "tasks": len(row.get("ПеременныеЗадачиПротокола") or []),
        }
        # update: change agenda text, add a second decision, read back
        updated_question = _clean(f"{mark}: изменённый вопрос повестки")
        update_args = {
            **probe_args,
            "ref_key": created_key,
            "agenda": [updated_question],
            "decisions": [
                *probe_args["decisions"],
                {"text": f"{mark}: второе решение", "due": datetime.now().strftime("%Y-%m-%d")},
            ],
        }
        _update_protocol(update_args, actor_fio=actor_fio, actor_onec_ref=actor_onec_ref)
        after = read_protocol_card(created_key)
        agenda_after = _protocol_rows(after, "ПовесткаСовещания")
        decisions_after = _protocol_rows(after, "Решения")
        if not agenda_after or _clean(agenda_after[0].get("Вопрос")) != updated_question:
            raise ProtocolWriteError("Update не изменил повестку")
        if len(decisions_after) != 2:
            raise ProtocolWriteError(f"Update не заменил решения (строк: {len(decisions_after)})")
        if not is_probe_topic(_clean(after.get("Комментарий"))):
            raise ProtocolWriteError("Update потерял метку пробы в комментарии")
        verified["update"] = {
            "agenda_after": len(agenda_after),
            "decisions_after": len(decisions_after),
        }
        form = read_protocol_form(created_key)["form"]
        verified["read_form"] = {
            "leader": form["leader"],
            "agenda": len(form["agenda"]),
            "decisions": len(form["decisions"]),
            "tasks": len(form["tasks"]),
        }
        delete_probe_document(PROTOCOL_ENTITY, created_key)
        recipe = protocol_write_recipe()
        return {
            "ok": True,
            "cleaned": True,
            "source": "odata",
            "summary": (
                f"Write probe ok: created protocol {verified['number'] or created_key}, "
                f"sections verified, updated via PATCH, read back, deleted"
            ),
            "recipe": recipe,
            "verified": verified,
            "meta": meta,
            "test_number": verified["number"],
            "test_ref_key": created_key,
            "test_left": False,
            **recipe,
        }
    except Exception as exc:  # noqa: BLE001
        cleaned = False
        if created_key:
            try:
                delete_probe_document(PROTOCOL_ENTITY, created_key)
                cleaned = True
            except Exception:  # noqa: BLE001
                cleaned = False
        return {
            "ok": False,
            "cleaned": cleaned or not created_key,
            "test_left": bool(created_key) and not cleaned,
            "source": "odata",
            "summary": f"Write probe failed: {exc}",
            "error": str(exc),
            "recipe": protocol_write_recipe(),
        }


def sweep_probe_protocols(*, limit: int = 50) -> int:
    """Remove leftover CONSTRUCTOR_PROBE protocols (Комментарий carries the mark)."""
    try:
        rows = _rows(
            _odata_get(
                {
                    "entity": PROTOCOL_ENTITY,
                    "top": max(1, min(limit, 50)),
                    "filter": f"substringof('{PROBE_MARK}', Комментарий)",
                }
            )
        )
    except Exception:  # noqa: BLE001
        return 0
    removed = 0
    for row in rows:
        if not is_probe_topic(str(row.get("Комментарий") or "")):
            continue
        try:
            delete_probe_document(PROTOCOL_ENTITY, str(row.get("Ref_Key") or ""))
            removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed

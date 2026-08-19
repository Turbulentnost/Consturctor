"""Только чтение служебных записок на организацию совещаний. Без записи в 1С."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

_PREFERRED_DOCS = ("ТД_СлужебнаяЗаписка", "СлужебнаяЗаписка")
_THEME_HINTS = ("тема", "содерж", "назнач", "вид", "коммент", "описан", "текст")
_PERSON_HINTS = (
    "кому",
    "адрес",
    "получат",
    "соглас",
    "направл",
    "исполнит",
    "ответств",
    "помощн",
    "сотрудник",
    "пользовател",
    "фио",
)
_WRITE_MARKERS = re.compile(
    r"(^|[^0-9a-zа-яё_])(записать|удалить|провести|установить|изменить)([^0-9a-zа-яё_]|$)"
)
_DEFAULT_ADDRESSEE = "Ильченко Екатерина Александровна"
_EMPTY_1C = (
    "0001-01-01",
    "01.01.0001",
    "01.01.1",
    "00000000-0000-0000-0000-000000000000",
)
# Реквизиты блока «Организация совещания» в Документ.ТД_СлужебнаяЗаписка.
MEETING_FIELDS = (
    ("ТемаСовещания", "MeetingTopic", "string"),
    ("МестоПроведенияСовещания", "Place", "ref"),
    ("ЖелаемаяДатаПроведенияСовещания", "DesiredDate", "date"),
    ("ВремяНачалаСовещания", "StartTime", "time"),
    ("ВремяОкончанияСовещания", "EndTime", "time"),
    ("ДатаПроведенияСовещания", "MeetingDate", "date"),
    ("ВидСовещания", "MeetingKind", "string"),
    ("НаУровнеПСД", "PsdLevel", "bool"),
    ("РуководительСовещания", "Leader", "ref"),
    ("Приоритет", "Priority", "ref"),
    ("ЦельПланаСовещания", "Purpose", "string"),
    ("Расписание", "Schedule", "ref"),
)
MEETING_FIELD_NAMES = tuple(name for name, _alias, _kind in MEETING_FIELDS)


def parse_note_period(input_data: dict[str, Any] | None) -> tuple[date, date]:
    """Вернуть закрытый период: один день или date_from…date_to."""
    args = input_data if isinstance(input_data, dict) else {}
    one = _parse_day(args.get("date"))
    start = _parse_day(args.get("date_from") or args.get("from"))
    end = _parse_day(args.get("date_to") or args.get("to"))
    if one and not start and not end:
        return one, one
    if start and not end:
        return start, start
    if end and not start:
        return end, end
    if start and end:
        if end < start:
            start, end = end, start
        return start, end
    today = date.today()
    return today, today


def person_needles(fio: str) -> list[str]:
    text = " ".join(str(fio or "").split())
    if not text:
        text = _DEFAULT_ADDRESSEE
    parts = [part for part in text.replace(".", " ").split() if len(part) >= 3]
    needles: list[str] = []
    for item in (text, *parts[:2]):
        if item and item not in needles:
            needles.append(item)
    return needles


def like_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace('"', '""')
        .replace("%", "[%]")
        .replace("_", "[_]")
    )


def onec_datetime(day: date, *, end_of_day: bool = False) -> str:
    if end_of_day:
        return f"ДАТАВРЕМЯ({day.year}, {day.month}, {day.day}, 23, 59, 59)"
    return f"ДАТАВРЕМЯ({day.year}, {day.month}, {day.day}, 0, 0, 0)"


def assert_select_only(query_text: str) -> str:
    text = str(query_text or "")
    folded = text.casefold()
    if "выбрать" not in folded:
        raise ValueError("Разрешён только запрос ВЫБРАТЬ")
    match = _WRITE_MARKERS.search(folded)
    if match:
        raise ValueError(f"Запрос 1С содержит запрещённую операцию: {match.group(2)}")
    return text


def pick_document_name(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    by_name = {str(item.get("name") or ""): item for item in candidates if item.get("name")}
    for name in _PREFERRED_DOCS:
        if name in by_name:
            return by_name[name]
    for item in candidates:
        label = f"{item.get('name') or ''} {item.get('synonym') or ''}".casefold()
        if "служебн" in label and "записк" in label:
            return item
    return candidates[0]


def classify_fields(requisites: list[str]) -> tuple[list[str], list[str]]:
    theme: list[str] = []
    person: list[str] = []
    for raw in requisites:
        name = str(raw or "").strip()
        if not name:
            continue
        low = name.casefold()
        if any(hint in low for hint in _THEME_HINTS) and name not in theme:
            theme.append(name)
        if any(hint in low for hint in _PERSON_HINTS) and name not in person:
            person.append(name)
    if "ТемаСлужебнойЗаписки" not in theme:
        theme.insert(0, "ТемаСлужебнойЗаписки")
    return theme, person


def build_meeting_notes_query(
    *,
    document_name: str,
    requisites: list[str],
    date_from: date,
    date_to: date,
    fio: str,
    limit: int,
) -> tuple[str, list[str], list[str]]:
    """Собрать только SELECT по служебным запискам. Ничего не меняет в 1С."""
    meta_name = str(document_name or "").strip() or "ТД_СлужебнаяЗаписка"
    theme_fields, person_fields = classify_fields(requisites)
    limit = max(1, min(200, int(limit or 50)))
    select_fields = ["Ссылка", "Номер", "Дата"]
    for name in (*theme_fields, *person_fields, "Комментарий", *MEETING_FIELD_NAMES):
        if name and name not in select_fields:
            select_fields.append(name)
    select_clause = ",\n        ".join(f"Д.{name} КАК {_alias(name)}" for name in select_fields[:24])
    conditions = [
        "НЕ Д.ПометкаУдаления",
        f"Д.Дата >= {onec_datetime(date_from)}",
        f"Д.Дата <= {onec_datetime(date_to, end_of_day=True)}",
    ]
    theme_parts: list[str] = []
    for field in theme_fields:
        theme_parts.append(
            f"(Д.{field} ПОДОБНО \"%организац%\" И Д.{field} ПОДОБНО \"%совеща%\")"
        )
        theme_parts.append(f"Д.{field} ПОДОБНО \"%организация совещаний%\"")
    if theme_parts:
        conditions.append("(" + " ИЛИ ".join(theme_parts) + ")")
    person_parts: list[str] = []
    for field in person_fields:
        for needle in person_needles(fio):
            person_parts.append(f"Д.{field} ПОДОБНО \"%{like_escape(needle)}%\"")
    if person_parts:
        conditions.append("(" + " ИЛИ ".join(person_parts) + ")")
    query = "\n".join(
        [
            f"ВЫБРАТЬ ПЕРВЫЕ {limit}",
            f"        {select_clause}",
            f"        ИЗ Документ.{meta_name} КАК Д",
            "        ГДЕ " + " И ".join(conditions),
            "        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ",
        ]
    )
    return assert_select_only(query), theme_fields, person_fields


def build_meeting_notes_query_latin(
    *,
    document_name: str,
    date_from: date,
    date_to: date,
    fio: str,
    limit: int,
    include_addressee: bool = True,
    deref: bool = True,
    presentation: bool = False,
    person_field: str = "МенеджерКому",
    include_meeting_fields: bool = True,
    include_schedule: bool = True,
) -> tuple[str, list[str]]:
    """SELECT с латинскими алиасами — для 32-bit VBS helper."""
    meta_name = str(document_name or "").strip() or "ТД_СлужебнаяЗаписка"
    limit = max(1, min(200, int(limit or 50)))
    theme_field = "ТемаСлужебнойЗаписки"
    person_field = str(person_field or "МенеджерКому").strip() or "МенеджерКому"
    # Составной реквизит темы: в WHERE работает .Наименование, Строка() — нет.
    theme_expr = _latin_field_expr(theme_field, deref=True, presentation=False)
    person_expr = _latin_field_expr(
        person_field,
        deref=deref,
        presentation=presentation or not deref,
    )
    select = [
        "Д.Номер КАК Number",
        "Д.Дата КАК DocDate",
        f"{theme_expr} КАК Theme",
    ]
    columns = ["Number", "DocDate", "Theme"]
    if include_meeting_fields:
        for field_name, alias, kind in MEETING_FIELDS:
            if field_name == "Расписание" and not include_schedule:
                continue
            expr = _meeting_field_expr(field_name, kind, deref=deref, presentation=presentation)
            select.append(f"{expr} КАК {alias}")
            columns.append(alias)
    conditions = [
        "НЕ Д.ПометкаУдаления",
        f"Д.Дата >= {onec_datetime(date_from)}",
        f"Д.Дата <= {onec_datetime(date_to, end_of_day=True)}",
        (
            f"(({theme_expr} ПОДОБНО \"%организац%\" И {theme_expr} ПОДОБНО \"%совеща%\") "
            f"ИЛИ {theme_expr} ПОДОБНО \"%организация совещаний%\")"
        ),
    ]
    if include_addressee:
        select.append(f"{person_expr} КАК Addressee")
        columns.append("Addressee")
        person_parts = [
            f"{person_expr} ПОДОБНО \"%{like_escape(needle)}%\""
            for needle in person_needles(fio)
        ]
        if person_parts:
            conditions.append("(" + " ИЛИ ".join(person_parts) + ")")
    query = "\n".join(
        [
            f"ВЫБРАТЬ ПЕРВЫЕ {limit}",
            "        " + ",\n        ".join(select),
            f"        ИЗ Документ.{meta_name} КАК Д",
            "        ГДЕ " + " И ".join(conditions),
            "        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ",
        ]
    )
    return assert_select_only(query), columns


def _latin_field_expr(field_name: str, *, deref: bool, presentation: bool) -> str:
    name = str(field_name or "").strip()
    if presentation:
        return f"ПРЕДСТАВЛЕНИЕ(Д.{name})"
    if deref:
        return f"Д.{name}.Наименование"
    return f"Д.{name}"


def _meeting_field_expr(field_name: str, kind: str, *, deref: bool, presentation: bool) -> str:
    if kind == "bool":
        return f"Д.{field_name}"
    # ПРЕДСТАВЛЕНИЕ даёт читаемый текст для ссылок, дат, времени и перечислений.
    return f"ПРЕДСТАВЛЕНИЕ(Д.{field_name})"


def clean_onec_value(value: object, *, as_time: bool = False, as_date: bool = False) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    folded = text.casefold()
    if folded in {"false", "ложь", "<не задана>", "<не задано>", "<пусто>"}:
        return ""
    if as_time or as_date:
        parsed = _parse_onec_datetime(text)
        if parsed is None:
            return ""
        empty_calendar = parsed.year <= 1
        if as_time:
            if empty_calendar and parsed.hour == 0 and parsed.minute == 0:
                return ""
            return parsed.strftime("%H:%M")
        if empty_calendar:
            return ""
        return parsed.strftime("%d.%m.%Y")
    if any(marker == folded or folded.startswith(marker) for marker in _EMPTY_1C):
        return ""
    return text


def duration_minutes(start_text: str, end_text: str) -> int | None:
    start = _parse_onec_datetime(start_text)
    end = _parse_onec_datetime(end_text)
    if start is None or end is None:
        return None
    delta = int((end - start).total_seconds() // 60)
    if delta <= 0 or delta > 24 * 60:
        return None
    return delta


def meeting_params_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    data = row if isinstance(row, dict) else {}
    start = clean_onec_value(data.get("StartTime"), as_time=True)
    end = clean_onec_value(data.get("EndTime"), as_time=True)
    psd_raw = str(data.get("PsdLevel") or "").strip().casefold()
    return {
        "topic": clean_onec_value(data.get("MeetingTopic")),
        "place": clean_onec_value(data.get("Place")),
        "desired_date": clean_onec_value(data.get("DesiredDate"), as_date=True),
        "start_time": start,
        "end_time": end,
        "duration_minutes": duration_minutes(
            str(data.get("StartTime") or ""),
            str(data.get("EndTime") or ""),
        ),
        "meeting_date": clean_onec_value(data.get("MeetingDate"), as_date=True),
        "meeting_type": clean_onec_value(data.get("MeetingKind")),
        "psd_level": psd_raw in {"true", "истина", "1", "да"},
        "leader": clean_onec_value(data.get("Leader")),
        "priority": clean_onec_value(data.get("Priority")),
        "periodicity": clean_onec_value(data.get("Schedule")),
        "purpose": clean_onec_value(data.get("Purpose")),
    }


def note_from_com32_row(
    row: dict[str, Any],
    *,
    document_name: str,
    addressee: str,
) -> dict[str, Any]:
    meeting = meeting_params_from_row(row)
    return {
        "document_type": "Служебная записка",
        "metadata_name": document_name,
        "number": clean_onec_value(row.get("Number")),
        "date": clean_onec_value(row.get("DocDate")),
        "theme": clean_onec_value(row.get("Theme")),
        "meeting_topic": meeting["topic"],
        "place": meeting["place"],
        "addressee": clean_onec_value(row.get("Addressee")) or addressee,
        "meeting": meeting,
        "fields": {key: clean_onec_value(value) for key, value in row.items()},
    }


def default_addressee() -> str:
    login = os.environ.get("ERP_LOGIN", "").strip()
    return login or _DEFAULT_ADDRESSEE


def _parse_day(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_onec_datetime(value: object) -> datetime | None:
    text = str(value or "").strip().replace("Z", "")
    if not text:
        return None
    if "T" in text:
        text = text[:19]
    padded = re.sub(r" (\d):", r" 0\1:", text, count=1)
    for candidate in (text, padded):
        for fmt in (
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%H:%M:%S",
            "%H:%M",
            "%d.%m.%Y",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            if parsed.year == 1900 and fmt.startswith("%H"):
                return datetime(1, 1, 1, parsed.hour, parsed.minute, parsed.second)
            return parsed
    return None


def _alias(field_name: str) -> str:
    alias = "".join(ch if ch.isalnum() else "_" for ch in field_name).strip("_")
    return alias[:60] or "field"

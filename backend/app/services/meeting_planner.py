"""Планировщик совещаний по служебным запискам: записки 1С «Организация совещаний (регл.)».

Только чтение 1С. Совещания создаются в Exchange (app.services.outlook_ews).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.services.docflow_memos import (
    MEMO_ENTITY,
    DocflowMemoError,
    _odata,
    _q,
    _strip_html,
    _text,
    is_secret,
)

logger = logging.getLogger(__name__)

MEETING_PLANNER_TOOLS = frozenset(
    {
        "meetings.memo_requests",
        "outlook.ews_availability",
        "outlook.ews_create_meeting",
    }
)
MEETING_PLANNER_WRITE_TOOLS = frozenset({"outlook.ews_create_meeting"})

THEME_TITLE = "Организация совещаний (регл.)"
THEME_ENTITY = "Catalog_ТД_ТемыСлужебныхЗаписок"
USERS_ENTITY = "Catalog_Пользователи"
PERSONS_ENTITY = "Catalog_ФизическиеЛица"
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Статус",
    "ТемаСлужебнойЗаписки",
    "ТемаСовещания",
    "ЦельПланаСовещания",
    "ТекстСлужебнойЗаписки",
    "ВидСовещания",
    "НаУровнеПСД",
    "ЖелаемаяДатаПроведенияСовещания",
    "ВремяНачалаСовещания",
    "ВремяОкончанияСовещания",
    "ДатаПроведенияСовещания",
    "МестоПроведенияСовещания",
    "МестоПроведенияСовещания_Type",
    "РуководительСовещания_Key",
    "Ответственный_Key",
    "СписокУчастников",
    "ПланСовещания",
)
_DEFAULT_DAYS_BACK = 60
_MAX_ROWS = 200

_theme_ref: str | None = None
_names: dict[tuple[str, str], str] = {}


def _guid(value: Any) -> str:
    text = str(value or "").strip()
    return text if _GUID_RE.match(text) and text != _EMPTY_GUID else ""


def _theme_key() -> str:
    global _theme_ref
    if _theme_ref is None:
        flt = _q(f"Description eq '{THEME_TITLE}'")
        rows = _odata(f"{THEME_ENTITY}?$format=json&$top=1&$select=Ref_Key&$filter={flt}").get("value") or []
        _theme_ref = _guid(rows[0].get("Ref_Key")) if rows and isinstance(rows[0], dict) else ""
    return _theme_ref


def _lookup_names(entity: str, keys: set[str]) -> dict[str, str]:
    """Ref_Key → Description одним запросом на пачку ключей, с кэшем на процесс."""
    wanted = sorted(key for key in keys if _guid(key))
    missing = [key for key in wanted if (entity, key) not in _names]
    for start in range(0, len(missing), 15):
        chunk = missing[start : start + 15]
        flt = _q(" or ".join(f"Ref_Key eq guid'{key}'" for key in chunk))
        try:
            rows = _odata(f"{entity}?$format=json&$select=Ref_Key,Description&$filter={flt}").get("value") or []
        except DocflowMemoError as exc:
            logger.warning("names %s failed: %s", entity, exc)
            rows = []
        for row in rows:
            if isinstance(row, dict) and _guid(row.get("Ref_Key")):
                _names[(entity, row["Ref_Key"])] = _text(row.get("Description"))
        for key in chunk:
            _names.setdefault((entity, key), "")
    return {key: _names.get((entity, key), "") for key in wanted}


def _day(value: Any) -> str:
    text = _text(value)
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


def _clock(value: Any) -> str:
    text = _text(value) or str(value or "")
    match = re.search(r"T(\d{2}):(\d{2})", text)
    if not match:
        return ""
    return f"{match.group(1)}:{match.group(2)}"


def _duration(start: str, end: str) -> int | None:
    if not start or not end:
        return None
    a = int(start[:2]) * 60 + int(start[3:5])
    b = int(end[:2]) * 60 + int(end[3:5])
    return b - a if 0 < b - a <= 12 * 60 else None


def _parse_day(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _numbers(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = re.split(r"[,;\s]+", raw)
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _same_number(a: str, b: str) -> bool:
    return a.lstrip("0") == b.lstrip("0") and bool(a.lstrip("0"))


def _fetch_rows(date_from: date, date_to: date) -> list[dict[str, Any]]:
    filters = [
        "DeletionMark eq false",
        f"Date ge datetime'{date_from.isoformat()}T00:00:00'",
        f"Date le datetime'{date_to.isoformat()}T23:59:59'",
    ]
    theme = _theme_key()
    select = quote_select([*_FIELDS, "ГрифДоступа/Description"])
    base = f"{MEMO_ENTITY}?$format=json&$top={_MAX_ROWS}&$orderby=Date desc&$expand=ГрифДоступа"
    attempts = []
    if theme:
        attempts.append(
            f"{base}&$select={select}&$filter="
            + _q(" and ".join([*filters, f"ТемаСлужебнойЗаписки eq cast(guid'{theme}', '{THEME_ENTITY}')"]))
        )
    # Публикация 1С бывает капризна к cast() по составному реквизиту — тогда фильтруем тему сами.
    attempts.append(f"{base}&$select={select}&$filter=" + _q(" and ".join(filters)))
    last: DocflowMemoError | None = None
    for path in attempts:
        try:
            rows = [row for row in (_odata(path).get("value") or []) if isinstance(row, dict)]
        except DocflowMemoError as exc:
            last = exc
            continue
        if theme:
            rows = [row for row in rows if _guid(row.get("ТемаСлужебнойЗаписки")) == theme]
        return rows
    raise last or DocflowMemoError("1С не вернула служебные записки")


def quote_select(fields: list[str]) -> str:
    from urllib.parse import quote

    return quote(",".join(fields), safe=",/")


def _ref_text(row: dict[str, Any], field: str) -> str:
    """Реквизит составного типа: строка как есть, ссылка — наименование из справочника."""
    raw = row.get(field)
    kind = str(row.get(f"{field}_Type") or "")
    key = _guid(raw)
    if key and kind.startswith("StandardODATA."):
        entity = kind.split(".", 1)[1]
        return _lookup_names(entity, {key}).get(key, "")
    if key:
        return ""
    return " ".join(_text(raw).split())


def _person(name: str) -> str:
    return " ".join(str(name or "").split()).strip(" .,;")


def _memo_view(row: dict[str, Any]) -> dict[str, Any]:
    start = _clock(row.get("ВремяНачалаСовещания"))
    end = _clock(row.get("ВремяОкончанияСовещания"))
    if start == "00:00" and end in {"", "00:00"}:
        start = end = ""
    if end == start:
        end = ""
    parts = [
        _guid(item.get("Участник_Key"))
        for item in (row.get("СписокУчастников") or [])
        if isinstance(item, dict)
    ]
    people = _lookup_names(PERSONS_ENTITY, {key for key in parts if key})
    users = _lookup_names(
        USERS_ENTITY,
        {key for key in (_guid(row.get("РуководительСовещания_Key")), _guid(row.get("Ответственный_Key"))) if key},
    )
    participants: list[str] = []
    for key in parts:
        name = _person(people.get(key, ""))
        if name and name not in participants:
            participants.append(name)
    agenda = [
        text
        for text in (
            _ref_text(item, "Задача") for item in (row.get("ПланСовещания") or []) if isinstance(item, dict)
        )
        if text.strip(" .")
    ]
    status = _text(row.get("Статус"))
    desired = _day(row.get("ЖелаемаяДатаПроведенияСовещания"))
    held = _day(row.get("ДатаПроведенияСовещания"))
    return {
        "ref": _guid(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": _day(row.get("Date")),
        "status": "Согласована" if status == "Согласована" else "Не согласована",
        "approved": status == "Согласована",
        "topic": " ".join(_text(row.get("ТемаСовещания")).split()).strip(" ,"),
        "purpose": _text(row.get("ЦельПланаСовещания")),
        "text": _strip_html(_text(row.get("ТекстСлужебнойЗаписки"))),
        "kind": _text(row.get("ВидСовещания")),
        "psd_level": row.get("НаУровнеПСД") is True or str(row.get("НаУровнеПСД")).lower() == "true",
        "desired_date": desired,
        "desired_in_past": bool(desired) and desired < date.today().isoformat(),
        "start_time": start,
        "end_time": end,
        "duration_minutes": _duration(start, end),
        "held_date": held,
        "place": _ref_text(row, "МестоПроведенияСовещания"),
        "leader": _person(users.get(_guid(row.get("РуководительСовещания_Key")), "")),
        "author": _person(users.get(_guid(row.get("Ответственный_Key")), "")),
        "participants": participants,
        "agenda": agenda,
    }


def memo_requests(args: dict[str, Any]) -> dict[str, Any]:
    """Служебные записки на организацию совещаний: по регламенту они идут помощнику ПСД (Ильченко)."""
    today = date.today()
    wanted = _numbers(args.get("numbers") or args.get("number"))
    date_to = _parse_day(args.get("date_to")) or today
    date_from = _parse_day(args.get("date_from")) or (date_to - timedelta(days=_DEFAULT_DAYS_BACK))
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    only_open = args.get("only_open", True) is not False and not wanted
    limit = max(1, min(100, int(args.get("max_results") or 50)))

    raw = _fetch_rows(date_from, date_to)
    hidden = sum(1 for row in raw if is_secret(row))
    memos: list[dict[str, Any]] = []
    for row in raw:
        if is_secret(row):
            continue
        number = _text(row.get("Number"))
        if wanted and not any(_same_number(number, item) for item in wanted):
            continue
        if only_open and (_text(row.get("Статус")) == "Согласована" or _day(row.get("ДатаПроведенияСовещания"))):
            continue
        memos.append(_memo_view(row))
        if len(memos) >= limit:
            break

    planned: dict[str, dict[str, Any]] = {}
    from app.services import outlook_ews

    if memos and outlook_ews.ews_configured():
        start = datetime.combine(today - timedelta(days=14), datetime.min.time())
        planned = outlook_ews.planned_memos(start, start + timedelta(days=200))
    for memo in memos:
        memo["planned"] = planned.get(memo["number"])

    missing = [item for item in wanted if not any(_same_number(m["number"], item) for m in memos)]
    open_count = sum(1 for memo in memos if not memo["planned"])
    return {
        "summary": (
            f"Служебные записки «{THEME_TITLE}»: {len(memos)}"
            + (f", из них ещё не в Outlook: {open_count}" if planned else "")
            + (f". Не найдены: {', '.join(missing)}" if missing else "")
        ),
        "theme": THEME_TITLE,
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "only_open": only_open,
        "memos": memos,
        "count": len(memos),
        "not_found": missing,
        "hidden_secret": hidden,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def invoke_meeting_planner(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    from app.services import outlook_ews

    if tool == "meetings.memo_requests":
        return memo_requests(args)
    if tool == "outlook.ews_availability":
        return outlook_ews.availability(args)
    if tool == "outlook.ews_create_meeting":
        return outlook_ews.create_meeting(args)
    raise outlook_ews.OutlookEwsError(f"Неизвестный инструмент планировщика: {tool}")

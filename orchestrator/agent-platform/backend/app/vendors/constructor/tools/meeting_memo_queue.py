"""onec.meeting_service_notes: служебные записки «Организация совещаний» прямо из OData 1С.

Только чтение. Без Constructor и без COM: адрес и учётка — ONEC_ODATA_* из backend/.env.
Тема служебной записки — составное поле (строка у старых записок, ссылка на справочник у новых),
поэтому OData фильтрует только по дате и статусу, а тема сверяется здесь.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests

DOCUMENT_ENTITY = "Document_ТД_СлужебнаяЗаписка"
PARTICIPANTS_ENTITY = "Document_ТД_СлужебнаяЗаписка_СписокУчастников"
THEME_CATALOG = "Catalog_ТД_ТемыСлужебныхЗаписок"
ROOM_CATALOG = "Catalog_CRM_Помещения"
PERSON_CATALOGS = ("Catalog_Пользователи", "Catalog_ФизическиеЛица")
SELECT = (
    "Ref_Key,Number,Date,Posted,DeletionMark,Статус,ТемаСлужебнойЗаписки,"
    "ТемаСовещания,ЖелаемаяДатаПроведенияСовещания,ВремяНачалаСовещания,"
    "ВремяОкончанияСовещания,МестоПроведенияСовещания,РуководительСовещания_Key,"
    "Ответственный_Key,НаУровнеПСД,ВидСовещания,ЦельПланаСовещания,ТекстСлужебнойЗаписки"
)
PAGE = 200
MAX_PAGES = 100
MAX_RESULTS = 500
DEFAULT_DAYS_BACK = 30
STATUSES = ("НеСогласована", "Согласована", "Отклонена")
EMPTY_KEY = "00000000-0000-0000-0000-000000000000"
WORKERS = 8

_cache_lock = threading.Lock()
_names: dict[str, str] = {}
_rooms: dict[str, str] = {}
_theme_keys: dict[str, str | None] = {}
_local = threading.local()


def _config() -> Any:
    from app.vendors.aiagentback.tools.onec.connection import build_odata_config

    config = build_odata_config()
    if not config.url or not config.user:
        raise RuntimeError("Не заданы ONEC_ODATA_URL и ONEC_ODATA_USER (Настройки → Инструменты → 1С).")
    return config


def _session(config: Any) -> requests.Session:
    session = getattr(_local, "session", None)
    if session is None or getattr(_local, "auth", None) != (config.user, config.password):
        session = requests.Session()
        session.auth = (config.user, config.password)
        session.trust_env = False
        _local.session = session
        _local.auth = (config.user, config.password)
    return session


def _get(config: Any, path: str, *, timeout: int | None = None) -> dict[str, Any]:
    url = f"{config.url.rstrip('/')}/{path}"
    response = _session(config).get(url, timeout=timeout or config.timeout)
    if not response.ok:
        raise RuntimeError(f"OData HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


def _query(entity: str, **params: str) -> str:
    parts = [f"${key}={quote(value, safe=',')}" for key, value in params.items() if value]
    return f"{quote(entity)}?{'&'.join(parts)}&$format=json"


def _day(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return None if parsed.year <= 1 else parsed
    return None


def _clock(value: Any) -> str:
    text = str(value or "")
    if "T" not in text:
        return ""
    hhmm = text.split("T", 1)[1][:5]
    return "" if hhmm == "00:00" and text.startswith("0001") else hhmm


def _minutes(start: str, end: str) -> int | None:
    if not start or not end:
        return None
    delta = (int(end[:2]) * 60 + int(end[3:5])) - (int(start[:2]) * 60 + int(start[3:5]))
    return delta if 0 < delta <= 24 * 60 else None


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("Description") or value.get("Наименование") or ""
    return " ".join(str(value or "").split())


def _key(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text == EMPTY_KEY else text


def _is_guid(text: str) -> bool:
    return len(text) == 36 and text.count("-") == 4


def _theme() -> str:
    from app.vendors.aiagentback.core.config import settings

    return (settings.ONEC_MEETING_MEMO_THEME or "Организация совещаний (регл.)").strip()


def _theme_key(config: Any, theme: str) -> str | None:
    with _cache_lock:
        if theme in _theme_keys:
            return _theme_keys[theme]
    safe = theme.replace("'", "''")
    rows = _get(config, _query(THEME_CATALOG, filter=f"Description eq '{safe}'", select="Ref_Key", top="1"))
    key = _key((rows.get("value") or [{}])[0].get("Ref_Key")) or None
    with _cache_lock:
        _theme_keys[theme] = key
    return key


def _theme_matches(row: dict[str, Any], theme: str, theme_key: str | None) -> bool:
    value = row.get("ТемаСлужебнойЗаписки")
    if isinstance(value, dict):
        value = value.get("Description") or value.get("Ref_Key")
    text = str(value or "").strip()
    return bool(text) and (text == theme or (theme_key is not None and text.lower() == theme_key.lower()))


def _lookup(config: Any, cache: dict[str, str], catalogs: tuple[str, ...], key: str) -> str:
    key = _key(key)
    if not key:
        return ""
    with _cache_lock:
        if key in cache:
            return cache[key]
    name = ""
    for catalog in catalogs:
        try:
            row = _get(config, f"{quote(catalog)}(guid'{key}')?$select=Description&$format=json", timeout=30)
        except (RuntimeError, requests.RequestException):
            continue
        name = _text(row.get("Description"))
        if name:
            break
    with _cache_lock:
        cache[key] = name
    return name


def _participant_keys(config: Any, ref_key: str) -> list[str]:
    path = _query(
        PARTICIPANTS_ENTITY,
        filter=f"Ref_Key eq guid'{ref_key}'",
        select="Ref_Key,LineNumber,Участник_Key",
    )
    rows = _get(config, path, timeout=60).get("value") or []
    rows.sort(key=lambda row: int(row.get("LineNumber") or 0))
    return [key for key in (_key(row.get("Участник_Key")) for row in rows) if key]


def _period(args: dict[str, Any]) -> tuple[date, date]:
    today = date.today()
    one = _day(args.get("date"))
    start = _day(args.get("date_from")) or one or today - timedelta(days=DEFAULT_DAYS_BACK)
    end = _day(args.get("date_to")) or one or today
    return (start, end) if start <= end else (end, start)


def _desired_from(args: dict[str, Any]) -> date | None:
    raw = str(args.get("desired_from") if "desired_from" in args else "today").strip().casefold()
    if raw in ("", "any", "все", "none"):
        return None
    if raw in ("today", "сегодня"):
        return date.today()
    parsed = _day(raw)
    if parsed is None:
        raise RuntimeError("desired_from: дата YYYY-MM-DD, today или any")
    return parsed


def _status(args: dict[str, Any]) -> str:
    raw = str(args.get("status") or "НеСогласована").strip()
    if raw.casefold() in ("any", "все", "all"):
        return ""
    for status in STATUSES:
        if raw.casefold() == status.casefold():
            return status
    raise RuntimeError(f"status: {', '.join(STATUSES)} или any")


def _scan(config: Any, odata_filter: str) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        path = _query(
            DOCUMENT_ENTITY,
            filter=odata_filter,
            orderby="Date desc",
            select=SELECT,
            top=str(PAGE),
            skip=str(page * PAGE),
        )
        batch = _get(config, path).get("value") or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows, page + 1
    raise RuntimeError(
        f"Больше {MAX_PAGES * PAGE} документов за период — сузьте date_from/date_to."
    )


def _note(row: dict[str, Any]) -> dict[str, Any]:
    start = _clock(row.get("ВремяНачалаСовещания"))
    end = _clock(row.get("ВремяОкончанияСовещания"))
    desired = _day(row.get("ЖелаемаяДатаПроведенияСовещания"))
    place = _text(row.get("МестоПроведенияСовещания"))
    return {
        "ref_key": _key(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": str(row.get("Date") or "")[:10],
        "status": _text(row.get("Статус")),
        "meeting_topic": _text(row.get("ТемаСовещания")),
        "purpose": _text(row.get("ЦельПланаСовещания")),
        "text": _text(row.get("ТекстСлужебнойЗаписки"))[:500],
        "desired_date": desired.isoformat() if desired else "",
        "start_time": start,
        "end_time": end,
        "duration_minutes": _minutes(start, end),
        "place": "" if _is_guid(place) else place,
        "place_key": place if _is_guid(place) else "",
        "meeting_type": _text(row.get("ВидСовещания")),
        "psd_level": bool(row.get("НаУровнеПСД")),
        "leader_key": _key(row.get("РуководительСовещания_Key")),
        "initiator_key": _key(row.get("Ответственный_Key")),
    }


def _enrich(config: Any, note: dict[str, Any], with_participants: bool) -> dict[str, Any]:
    note["leader"] = _lookup(config, _names, PERSON_CATALOGS, note["leader_key"])
    note["initiator"] = _lookup(config, _names, PERSON_CATALOGS, note["initiator_key"])
    if note["place_key"]:
        note["place"] = _lookup(config, _rooms, (ROOM_CATALOG, *PERSON_CATALOGS), note["place_key"])
    if with_participants and note["ref_key"]:
        keys = _participant_keys(config, note["ref_key"])
        note["participants"] = [
            {"fio": _lookup(config, _names, PERSON_CATALOGS, key), "key": key} for key in keys
        ]
        note["participants_count"] = len(keys)
    return note


def _mentions(note: dict[str, Any], fio: str) -> bool:
    needle = " ".join(fio.casefold().split())
    people = [note.get("leader"), note.get("initiator")]
    people += [item.get("fio") for item in note.get("participants") or []]
    return any(needle in " ".join(str(person or "").casefold().split()) for person in people)


def invoke_meeting_service_notes(args: dict[str, Any]) -> dict[str, Any]:
    config = _config()
    date_from, date_to = _period(args)
    desired_from = _desired_from(args)
    status = _status(args)
    fio = str(args.get("fio") or "").strip()
    with_participants = args.get("include_participants", True) is not False
    limit = max(1, min(MAX_RESULTS, int(args.get("max_results") or MAX_RESULTS)))

    clauses = [
        "Posted eq true",
        "DeletionMark eq false",
        f"Date ge datetime'{date_from.isoformat()}T00:00:00'",
        f"Date le datetime'{date_to.isoformat()}T23:59:59'",
    ]
    if status:
        clauses.append(f"Статус eq '{status}'")
    odata_filter = " and ".join(clauses)

    theme = _theme()
    theme_key = _theme_key(config, theme)
    rows, pages = _scan(config, odata_filter)
    skipped = {"other_theme": 0, "desired_earlier": 0, "desired_empty": 0}
    notes: list[dict[str, Any]] = []
    for row in rows:
        if not _theme_matches(row, theme, theme_key):
            skipped["other_theme"] += 1
            continue
        note = _note(row)
        if desired_from is not None:
            if not note["desired_date"]:
                skipped["desired_empty"] += 1
                continue
            if note["desired_date"] < desired_from.isoformat():
                skipped["desired_earlier"] += 1
                continue
        notes.append(note)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        notes = list(pool.map(lambda note: _enrich(config, note, with_participants), notes))
    if fio:
        notes = [note for note in notes if _mentions(note, fio)]
    notes.sort(key=lambda note: (note["desired_date"] or "9999", note["start_time"] or "99", note["number"]))
    found = len(notes)

    return {
        "notes": notes[:limit],
        "count": min(found, limit),
        "found": found,
        "truncated": found > limit,
        "scanned_documents": len(rows),
        "pages": pages,
        "skipped": skipped,
        "filters": {
            "theme": theme,
            "status": status or "any",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "desired_from": desired_from.isoformat() if desired_from else "any",
            "fio": fio,
        },
        "source": "odata",
        "readonly": True,
        "entity": DOCUMENT_ENTITY,
        "method": "odata_meeting_memo_queue",
    }

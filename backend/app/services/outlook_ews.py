"""Exchange (EWS) для агентов: занятость людей и совещания в общем календаре «Совещания».

Работает от служебного ящика (OUTLOOK_EMAIL / OUTLOOK_MAILBOX), у которого есть права
Editor на календарь OUTLOOK_COMPANY_CALENDAR. Учётные данные — только из backend/.env.
"""

from __future__ import annotations

import html
import logging
import re
import threading
from datetime import date, datetime, time, timedelta
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

BOSS_FIO = "Амураль Игорь Борисович"
# По этой строке в тексте встречи находим уже запланированные служебные записки.
PLANNER_MARK = "Constructor: служебная записка №"
WORK_START = time(8, 0)
WORK_END = time(18, 0)
SLOT_STEP = timedelta(minutes=30)
MAX_RANGE_DAYS = 31
DEFAULT_DURATION_MIN = 60

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MARK_RE = re.compile(re.escape(PLANNER_MARK) + r"\s*([0-9A-Za-zА-Яа-я_\-]+)")
_BUSY_TYPES = frozenset({"Busy", "Tentative", "OOF", "WorkingElsewhere"})
_PLACE_SKIP = frozenset({"здание", "задание", "зд", "этаж", "корпус", "в", "на", "и"})

_lock = threading.Lock()
_accounts: dict[str, Any] = {}
_config: Any = None
_people: dict[str, dict[str, str]] = {}


class OutlookEwsError(RuntimeError):
    pass


def ews_configured() -> bool:
    return bool(
        settings.outlook_server.strip()
        and settings.outlook_email.strip()
        and settings.outlook_password
        and settings.outlook_company_calendar.strip()
    )


def _require_config() -> None:
    if not ews_configured():
        raise OutlookEwsError(
            "Exchange не настроен: задайте OUTLOOK_SERVER, OUTLOOK_EMAIL, OUTLOOK_PASSWORD "
            "и OUTLOOK_COMPANY_CALENDAR в backend/.env"
        )


def _tz() -> Any:
    from exchangelib import EWSTimeZone

    return EWSTimeZone(settings.outlook_timezone or "Europe/Moscow")


def _configuration() -> Any:
    global _config
    if _config is None:
        from exchangelib import Configuration, Credentials, Version
        from exchangelib.protocol import BaseProtocol
        from exchangelib.version import EXCHANGE_2013_SP1

        BaseProtocol.TIMEOUT = float(settings.outlook_timeout_sec or 60)
        _config = Configuration(
            server=settings.outlook_server.strip(),
            credentials=Credentials(settings.outlook_email.strip(), settings.outlook_password),
            version=Version(build=EXCHANGE_2013_SP1),
        )
    return _config


def _account(smtp: str) -> Any:
    key = smtp.strip().lower()
    with _lock:
        cached = _accounts.get(key)
        if cached is not None:
            return cached
    from exchangelib import DELEGATE, Account

    try:
        account = Account(
            primary_smtp_address=key,
            config=_configuration(),
            autodiscover=False,
            access_type=DELEGATE,
        )
    except Exception as exc:  # noqa: BLE001
        raise OutlookEwsError(f"Exchange: нет доступа к ящику {key}: {_short(exc)}") from exc
    with _lock:
        _accounts[key] = account
    return account


def _own() -> Any:
    _require_config()
    last: OutlookEwsError | None = None
    # Логин (UPN) и адрес ящика служебной учётки могут отличаться.
    for smtp in (settings.outlook_mailbox, settings.outlook_email):
        if not (smtp or "").strip():
            continue
        try:
            return _account(smtp)
        except OutlookEwsError as exc:
            last = exc
    raise last or OutlookEwsError("Exchange: не задан служебный ящик")


def _company() -> Any:
    _require_config()
    return _account(settings.outlook_company_calendar)


def _short(exc: BaseException) -> str:
    text = " ".join(str(exc or "").split())
    return (text[:240] + "…") if len(text) > 240 else (text or type(exc).__name__)


# --- время ---------------------------------------------------------------


def _parse_local(value: Any, *, what: str) -> datetime:
    text = str(value or "").strip().replace(" ", "T")
    if not text:
        raise OutlookEwsError(f"Не указано {what}")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d.%m.%YT%H:%M", "%d.%m.%YT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise OutlookEwsError(f"Не понял {what}: {value!r}. Нужно YYYY-MM-DDTHH:MM") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_tz()).replace(tzinfo=None)
    return parsed


def _parse_day(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _ews(value: datetime) -> Any:
    from exchangelib import EWSDateTime

    return EWSDateTime(
        value.year, value.month, value.day, value.hour, value.minute, value.second, tzinfo=_tz()
    )


def _local(value: Any) -> datetime:
    """EWSDateTime/EWSDate из Exchange → наивное местное время."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(_tz())
        return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return _parse_local(value, what="время")


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def _human(value: datetime) -> str:
    return value.strftime("%d.%m.%Y %H:%M")


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


# --- люди ----------------------------------------------------------------


def _name_key(value: str) -> list[str]:
    return [part for part in str(value or "").casefold().replace("ё", "е").replace(".", " ").split() if part]


def _same_person(display: str, fio: str) -> bool:
    a, b = _name_key(display), _name_key(fio)
    if not a or not b:
        return False
    return a[:2] == b[:2] or (len(b) == 1 and a[0] == b[0])


def resolve_person(query: str) -> dict[str, str]:
    """ФИО или адрес → {query, name, email, match}. Пустой email — не нашли в адресной книге."""
    text = " ".join(str(query or "").split())
    if not text:
        return {"query": "", "name": "", "email": "", "match": "none"}
    if _EMAIL_RE.match(text):
        return {"query": text, "name": text, "email": text.lower(), "match": "email"}
    key = " ".join(_name_key(text))
    with _lock:
        cached = _people.get(key)
    if cached is not None:
        return {**cached, "query": text}

    protocol = _own().protocol
    words = text.replace(".", " ").split()
    attempts = [text]
    if len(words) >= 3:
        attempts.append(" ".join(words[:2]))
    result = {"query": text, "name": "", "email": "", "match": "none"}
    for attempt in attempts:
        try:
            found = protocol.resolve_names([attempt], return_full_contact_data=False)
        except Exception as exc:  # noqa: BLE001
            logger.info("resolve_names %r failed: %s", attempt, _short(exc))
            continue
        mailboxes = [m for m in found if getattr(m, "email_address", None)]
        if not mailboxes:
            continue
        exact = [m for m in mailboxes if _same_person(getattr(m, "name", "") or "", text)]
        pick = exact[0] if exact else (mailboxes[0] if len(mailboxes) == 1 else None)
        if pick is not None:
            result = {
                "query": text,
                "name": text if not exact else (pick.name or text),
                "email": str(pick.email_address).lower(),
                "match": "exact" if exact else "single",
            }
            break
        result["candidates"] = ", ".join(
            f"{m.name} <{m.email_address}>" for m in mailboxes[:5]
        )
    with _lock:
        _people[key] = {k: v for k, v in result.items() if k != "query"}
    return result


def resolve_people(queries: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    people: list[dict[str, str]] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for query in queries:
        person = resolve_person(query)
        if not person.get("email"):
            if person.get("query"):
                unresolved.append(person["query"])
            continue
        if person["email"] in seen:
            continue
        seen.add(person["email"])
        people.append(person)
    return people, unresolved


def boss() -> dict[str, str]:
    person = resolve_person(BOSS_FIO)
    if not person.get("email"):
        raise OutlookEwsError(f"Exchange не нашёл в адресной книге «{BOSS_FIO}»")
    return {**person, "name": BOSS_FIO}


def _people_arg(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in re.split(r"[;\n]", raw) if part.strip()]
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                item = item.get("email") or item.get("fio") or item.get("name") or ""
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    return []


# --- занятость -----------------------------------------------------------


def busy_intervals(emails: list[str], start: datetime, end: datetime) -> dict[str, list[dict[str, Any]] | None]:
    """Занятость по free/busy Exchange. None — Exchange не отдал данные по ящику."""
    if not emails:
        return {}
    protocol = _own().protocol
    # Exchange требует окно длиннее интервала объединения — запрашиваем целые сутки.
    query_start = datetime.combine(start.date(), time(0, 0))
    query_end = datetime.combine(end.date() + timedelta(days=1), time(0, 0))
    try:
        info = list(
            protocol.get_free_busy_info(
                accounts=[(email, "Required", False) for email in emails],
                start=_ews(query_start),
                end=_ews(query_end),
                merged_free_busy_interval=30,
                requested_view="Detailed",
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise OutlookEwsError(f"Exchange: не удалось получить занятость: {_short(exc)}") from exc
    out: dict[str, list[dict[str, Any]] | None] = {}
    for email, view in zip(emails, info):
        if isinstance(view, Exception):
            out[email] = None
            continue
        rows: list[dict[str, Any]] = []
        for event in getattr(view, "calendar_events", None) or []:
            if event.busy_type not in _BUSY_TYPES:
                continue
            event_start, event_end = _local(event.start), _local(event.end)
            if event_end <= event_start:
                continue
            details = getattr(event, "details", None)
            rows.append(
                {
                    "start": event_start,
                    "end": event_end,
                    "status": event.busy_type,
                    "subject": str(getattr(details, "subject", "") or "") if details else "",
                }
            )
        rows.sort(key=lambda row: row["start"])
        out[email] = rows
    return out


def company_items(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Совещания общего календаря за период (подтягиваем тему к занятости шефа и место)."""
    try:
        view = _company().calendar.view(start=_ews(start), end=_ews(end)).only(
            "subject", "start", "end", "location", "required_attendees", "optional_attendees"
        )
        rows = []
        for item in view:
            attendees = [
                str(att.mailbox.email_address or "").lower()
                for att in list(item.required_attendees or []) + list(item.optional_attendees or [])
                if getattr(att, "mailbox", None) is not None
            ]
            rows.append(
                {
                    "subject": str(item.subject or ""),
                    "start": _local(item.start),
                    "end": _local(item.end),
                    "location": str(item.location or ""),
                    "attendees": attendees,
                }
            )
        return rows
    except OutlookEwsError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OutlookEwsError(f"Exchange: не удалось прочитать календарь совещаний: {_short(exc)}") from exc


def _place_tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zа-яё]+", str(text or "").casefold().replace("ё", "е"))
    return [word for word in words if word not in _PLACE_SKIP and len(word) >= 3]


def _room_numbers(text: str) -> set[str]:
    # «6/8», «8/8» — номер здания, в Outlook его часто опускают; «214» — номер кабинета.
    return set(re.findall(r"(?<![\d/])\d+(?![\d/])", str(text or "")))


def _stem(word: str) -> str:
    return word if len(word) <= 3 else word[: min(6, max(3, len(word) - 2))]


def same_place(place: str, location: str) -> bool:
    """«малый конференц-зал здание 6/8» ≈ «в малом конференц-зале»: сравниваем основы слов."""
    wanted = _place_tokens(place)
    if not wanted:
        return False
    if not _room_numbers(place) <= _room_numbers(location):
        return False
    have = _place_tokens(location)
    return all(any(token.startswith(_stem(word)) for token in have) for word in wanted)


def planned_memos(start: datetime, end: datetime) -> dict[str, dict[str, Any]]:
    """Номер служебной записки → совещание, которое агент уже создал в календаре «Совещания»."""
    found: dict[str, dict[str, Any]] = {}
    try:
        query = (
            _company()
            .calendar.filter(start__gte=_ews(start), start__lt=_ews(end), body__contains=PLANNER_MARK)
            .only("subject", "start", "end", "location", "body")
        )
        for item in query:
            for number in _MARK_RE.findall(html.unescape(re.sub(r"<[^>]+>", " ", str(item.body or "")))):
                found[number] = {
                    "subject": str(item.subject or ""),
                    "start": _iso(_local(item.start)),
                    "end": _iso(_local(item.end)),
                    "location": str(item.location or ""),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("planned memos lookup failed: %s", _short(exc))
    return found


def _free_windows(day: date, busy: list[dict[str, Any]], not_before: datetime) -> list[tuple[datetime, datetime]]:
    cursor = max(datetime.combine(day, WORK_START), not_before)
    finish = datetime.combine(day, WORK_END)
    windows: list[tuple[datetime, datetime]] = []
    for row in sorted(busy, key=lambda item: item["start"]):
        if row["end"] <= cursor:
            continue
        if row["start"] >= finish:
            break
        if row["start"] > cursor:
            windows.append((cursor, min(row["start"], finish)))
        cursor = max(cursor, row["end"])
    if cursor < finish:
        windows.append((cursor, finish))
    return windows


def _round_up(value: datetime) -> datetime:
    base = value.replace(second=0, microsecond=0)
    return base + timedelta(minutes=(-base.minute) % 30)


def _row_view(row: dict[str, Any], who: str = "") -> dict[str, Any]:
    out = {
        "start": _iso(row["start"]),
        "end": _iso(row["end"]),
        "status": row.get("status") or "Busy",
    }
    if row.get("subject"):
        out["subject"] = row["subject"]
    if row.get("location"):
        out["location"] = row["location"]
    if who:
        out["who"] = who
    return out


def _with_subjects(busy: list[dict[str, Any]], items: list[dict[str, Any]], email: str) -> list[dict[str, Any]]:
    """Free/busy не отдаёт тему — берём её из календаря «Совещания», где человек в участниках."""
    rows: list[dict[str, Any]] = []
    for row in busy:
        if not row.get("subject"):
            for item in items:
                if email in item["attendees"] and _overlaps(row["start"], row["end"], item["start"], item["end"]):
                    row = {**row, "subject": item["subject"], "location": item["location"]}
                    break
        rows.append(row)
    return rows


def availability(args: dict[str, Any]) -> dict[str, Any]:
    _require_config()
    duration = max(15, min(8 * 60, int(args.get("duration_minutes") or DEFAULT_DURATION_MIN)))
    requested_start = None
    requested_end = None
    if str(args.get("start") or "").strip():
        requested_start = _parse_local(args.get("start"), what="начало")
        requested_end = (
            _parse_local(args.get("end"), what="окончание")
            if str(args.get("end") or "").strip()
            else requested_start + timedelta(minutes=duration)
        )
        if requested_end <= requested_start:
            raise OutlookEwsError("Окончание совещания раньше начала")
        duration = int((requested_end - requested_start).total_seconds() // 60)

    today = date.today()
    day_from = _parse_day(args.get("date_from") or args.get("date")) or (
        requested_start.date() if requested_start else today
    )
    day_to = _parse_day(args.get("date_to")) or (day_from + timedelta(days=int(args.get("days") or 5)))
    if day_to < day_from:
        day_from, day_to = day_to, day_from
    day_from = max(day_from, today)
    day_to = min(max(day_to, day_from), day_from + timedelta(days=MAX_RANGE_DAYS))
    if requested_start:
        day_from = min(day_from, requested_start.date())
        day_to = max(day_to, requested_end.date())

    chief = boss()
    others, unresolved = resolve_people(_people_arg(args.get("people") or args.get("attendees")))
    others = [person for person in others if person["email"] != chief["email"]]
    place = str(args.get("place") or args.get("location") or "").strip()

    range_start = datetime.combine(day_from, time(0, 0))
    range_end = datetime.combine(day_to + timedelta(days=1), time(0, 0))
    emails = [chief["email"], *(person["email"] for person in others)]
    busy = busy_intervals(emails, range_start, range_end)
    items = company_items(range_start, range_end)
    chief_busy = busy.get(chief["email"])
    if chief_busy is None:
        raise OutlookEwsError(f"Exchange не отдал занятость {BOSS_FIO} ({chief['email']})")
    chief_busy = _with_subjects(chief_busy, items, chief["email"])
    place_busy = [item for item in items if place and same_place(place, item["location"])]

    def place_conflicts(start: datetime, end: datetime) -> list[dict[str, Any]]:
        return [_row_view(item) for item in place_busy if _overlaps(start, end, item["start"], item["end"])]

    def people_conflicts(start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for person in others:
            for row in busy.get(person["email"]) or []:
                if _overlaps(start, end, row["start"], row["end"]):
                    rows.append(_row_view(row, person["name"] or person["query"]))
                    break
        return rows

    result: dict[str, Any] = {
        "boss": {"name": BOSS_FIO, "email": chief["email"]},
        "people": [{"query": p["query"], "name": p["name"], "email": p["email"]} for p in others],
        "unresolved": unresolved,
        "no_free_busy": [p["name"] or p["query"] for p in others if busy.get(p["email"]) is None],
        "period": {"from": day_from.isoformat(), "to": day_to.isoformat()},
        "duration_minutes": duration,
        "work_hours": f"{WORK_START.strftime('%H:%M')}–{WORK_END.strftime('%H:%M')}, пн–пт",
        "boss_busy": [_row_view(row) for row in chief_busy],
    }

    if requested_start and requested_end:
        conflicts = [
            _row_view(row) for row in chief_busy if _overlaps(requested_start, requested_end, row["start"], row["end"])
        ]
        result["requested"] = {
            "start": _iso(requested_start),
            "end": _iso(requested_end),
            "boss_free": not conflicts,
            "boss_conflicts": conflicts,
            "place_conflicts": place_conflicts(requested_start, requested_end),
            "participants_busy": people_conflicts(requested_start, requested_end),
            "in_past": requested_start < datetime.now(),
        }

    not_before = _round_up(datetime.now() + timedelta(minutes=30))
    windows: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    need = timedelta(minutes=duration)
    day = day_from
    while day <= day_to:
        if day.weekday() < 5:
            for start, end in _free_windows(day, chief_busy, not_before):
                if end - start < need:
                    continue
                windows.append({"start": _iso(start), "end": _iso(end)})
                slot = _round_up(start)
                best: dict[str, Any] | None = None
                while slot + need <= end:
                    slot_end = slot + need
                    if not place_conflicts(slot, slot_end):
                        busy_people = people_conflicts(slot, slot_end)
                        candidate = {
                            "start": _iso(slot),
                            "end": _iso(slot_end),
                            "participants_busy": busy_people,
                        }
                        if best is None or len(busy_people) < len(best["participants_busy"]):
                            best = candidate
                        if not busy_people:
                            break
                    slot += SLOT_STEP
                if best is not None:
                    suggestions.append(best)
        day += timedelta(days=1)
    suggestions.sort(key=lambda row: (len(row["participants_busy"]) > 0, row["start"]))
    result["boss_free_windows"] = windows[:40]
    result["suggestions"] = suggestions[: max(1, min(20, int(args.get("max_suggestions") or 8)))]
    result["summary"] = _availability_summary(result)
    return result


def _availability_summary(result: dict[str, Any]) -> str:
    parts: list[str] = []
    requested = result.get("requested")
    if isinstance(requested, dict):
        start = _parse_local(requested["start"], what="начало")
        if requested["boss_free"]:
            parts.append(f"{BOSS_FIO} свободен {_human(start)}.")
        else:
            subjects = "; ".join(
                f"{row['start'][11:]}–{row['end'][11:]} {row.get('subject') or row['status']}"
                for row in requested["boss_conflicts"]
            )
            parts.append(f"{BOSS_FIO} занят {_human(start)}: {subjects}.")
        if requested["place_conflicts"]:
            parts.append("Место занято: " + "; ".join(row.get("subject", "") for row in requested["place_conflicts"]) + ".")
    if result.get("suggestions"):
        first = result["suggestions"][0]
        parts.append(f"Ближайшее удобное время: {_human(_parse_local(first['start'], what='начало'))}.")
    else:
        parts.append("В рабочее время периода у шефа нет свободного окна нужной длины.")
    if result.get("unresolved"):
        parts.append("Не найдены в адресной книге: " + ", ".join(result["unresolved"]) + ".")
    return " ".join(parts)


# --- создание совещания --------------------------------------------------


def _body_html(args: dict[str, Any], people: list[dict[str, str]], unresolved: list[str]) -> str:
    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        text = " ".join(str(value or "").split())
        if text:
            lines.append(f"<div><b>{html.escape(label)}:</b> {html.escape(text)}</div>")

    add("Руководитель", args.get("leader"))
    add("Цель", args.get("purpose"))
    agenda = [str(item).strip() for item in (args.get("agenda") or []) if str(item).strip()] if isinstance(
        args.get("agenda"), list
    ) else [part.strip() for part in str(args.get("agenda") or "").split("\n") if part.strip()]
    if agenda:
        lines.append("<div><b>Повестка:</b></div>")
        lines.extend(f"<div>{index}. {html.escape(item)}</div>" for index, item in enumerate(agenda, 1))
    names = [person["name"] or person["query"] for person in people] + unresolved
    if names:
        lines.append("<div>&nbsp;</div><div><b>Участники:</b></div>")
        lines.extend(f"<div>{html.escape(name)}</div>" for name in names)
    extra = str(args.get("body") or args.get("description") or "").strip()
    if extra:
        lines.append("<div>&nbsp;</div>")
        lines.extend(f"<div>{html.escape(part)}</div>" for part in extra.split("\n") if part.strip())
    number = str(args.get("memo_number") or "").strip()
    lines.append("<div>&nbsp;</div>")
    if number:
        memo_date = str(args.get("memo_date") or "").strip()
        suffix = f" от {html.escape(memo_date)}" if memo_date else ""
        lines.append(f"<div>{html.escape(PLANNER_MARK)}{html.escape(number)}{suffix}</div>")
    lines.append("<div>Запланировано ИИ-агентом «Планировщик совещаний по служебным запискам».</div>")
    return "<html><body><font face=\"Calibri\" size=\"2\">" + "".join(lines) + "</font></body></html>"


def create_meeting(args: dict[str, Any]) -> dict[str, Any]:
    _require_config()
    subject = " ".join(str(args.get("subject") or args.get("topic") or "").split())
    if not subject:
        raise OutlookEwsError("Не указана тема совещания (subject)")
    start = _parse_local(args.get("start"), what="начало совещания")
    if str(args.get("end") or "").strip():
        end = _parse_local(args.get("end"), what="окончание совещания")
    else:
        end = start + timedelta(minutes=int(args.get("duration_minutes") or DEFAULT_DURATION_MIN))
    if end <= start:
        raise OutlookEwsError("Окончание совещания раньше начала")
    if start < datetime.now() - timedelta(minutes=5):
        raise OutlookEwsError(f"Время {_human(start)} уже прошло — выберите будущее время")
    location = " ".join(str(args.get("location") or args.get("place") or "").split())

    chief = boss()
    people, unresolved = resolve_people(_people_arg(args.get("attendees") or args.get("people")))
    if args.get("include_boss", True) is not False and all(p["email"] != chief["email"] for p in people):
        people.append(chief)

    number = str(args.get("memo_number") or "").strip()
    if number:
        existing = planned_memos(start - timedelta(days=90), start + timedelta(days=180)).get(number)
        if existing:
            return {
                "created": False,
                "duplicate": True,
                "memo_number": number,
                "existing": existing,
                "summary": (
                    f"По служебной записке №{number} совещание уже есть в календаре «Совещания»: "
                    f"{existing['subject']}, {existing['start'].replace('T', ' ')}. Второе не создаю."
                ),
            }

    if not args.get("force"):
        busy = busy_intervals([chief["email"]], start, end).get(chief["email"]) or []
        conflicts = [_row_view(row) for row in busy if _overlaps(start, end, row["start"], row["end"])]
        if conflicts:
            items = company_items(start, end)
            conflicts = [
                _row_view(row)
                for row in _with_subjects(
                    [row for row in busy if _overlaps(start, end, row["start"], row["end"])], items, chief["email"]
                )
            ]
            return {
                "created": False,
                "boss_busy": True,
                "conflicts": conflicts,
                "summary": (
                    f"{BOSS_FIO} занят {_human(start)}–{end.strftime('%H:%M')}. Совещание не создано: "
                    "предложите человеку другое время (outlook.ews_availability) или force=true, "
                    "если он сам велел ставить поверх."
                ),
            }

    from exchangelib import CalendarItem, HTMLBody
    from exchangelib.items import SEND_ONLY_TO_ALL
    from exchangelib.properties import Attendee, Mailbox

    company = _company()
    item = CalendarItem(
        account=company,
        folder=company.calendar,
        subject=subject,
        body=HTMLBody(_body_html(args, people, unresolved)),
        start=_ews(start),
        end=_ews(end),
        location=location or None,
        required_attendees=[
            Attendee(mailbox=Mailbox(email_address=person["email"]), response_type="Unknown")
            for person in people
        ],
        reminder_is_set=True,
        reminder_minutes_before_start=15,
        legacy_free_busy_status="Busy",
    )
    try:
        item.save(send_meeting_invitations=SEND_ONLY_TO_ALL)
    except Exception as exc:  # noqa: BLE001
        raise OutlookEwsError(f"Exchange не создал совещание: {_short(exc)}") from exc

    names = [person["name"] or person["query"] for person in people]
    return {
        "created": True,
        "id": str(item.id or ""),
        "subject": subject,
        "start": _iso(start),
        "end": _iso(end),
        "location": location,
        "calendar": settings.outlook_company_calendar.strip().lower(),
        "attendees": [{"name": p["name"] or p["query"], "email": p["email"]} for p in people],
        "unresolved": unresolved,
        "memo_number": number,
        "invitations_sent": True,
        "summary": (
            f"Совещание «{subject}» {_human(start)}–{end.strftime('%H:%M')} создано в календаре «Совещания»"
            + (f", место: {location}" if location else "")
            + f". Приглашения отправлены: {', '.join(names)}."
            + (f" Не найдены в адресной книге (приглашение не ушло): {', '.join(unresolved)}." if unresolved else "")
        ),
    }


def delete_meeting(item_id: str, changekey: str = "") -> None:
    """Для отладки: удалить созданное совещание без рассылки отмены."""
    from exchangelib import CalendarItem
    from exchangelib.items import SEND_TO_NONE

    company = _company()
    found = list(company.fetch(ids=[(item_id, changekey or None)]))
    for item in found:
        if isinstance(item, CalendarItem):
            item.delete(send_meeting_cancellations=SEND_TO_NONE)

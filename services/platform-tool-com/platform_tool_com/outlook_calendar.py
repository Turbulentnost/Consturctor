"""Outlook COM helpers: launch app and read calendar appointments."""

from __future__ import annotations

import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

# Outlook OlDefaultFolders.olFolderCalendar
OL_FOLDER_CALENDAR = 9

_lock = threading.Lock()
_outlook_sessions: dict[str, dict[str, Any]] = {}
_stub_sessions: dict[str, dict[str, Any]] = {}

_STUB_EVENTS = [
    {
        "entry_id": "stub-entry-001",
        "subject": "Планерка МТО",
        "start": "",
        "end": "",
        "location": "Переговорная 2",
        "organizer": "omto@turbo-don.ru",
        "required_attendees": "omto@turbo-don.ru; td_ceh@turbo-don.ru",
        "optional_attendees": "",
        "body": "Еженедельная планёрка отдела МТО.",
        "all_day": False,
        "busy_status": 2,
        "categories": "Work",
    },
    {
        "entry_id": "stub-entry-002",
        "subject": "Совещание по спецификации DN200",
        "start": "",
        "end": "",
        "location": "Teams",
        "organizer": "chief@turbo-don.ru",
        "required_attendees": "omto@turbo-don.ru",
        "optional_attendees": "",
        "body": "Согласование спецификации арматуры.",
        "all_day": False,
        "busy_status": 2,
        "categories": "Meeting",
    },
]


def _is_windows() -> bool:
    return sys.platform == "win32"


def _parse_dt(value: Any, *, default: datetime | None = None) -> datetime:
    if value is None or value == "":
        if default is None:
            raise ValueError("datetime required")
        return default
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    # Accept ISO and common Outlook-friendly forms
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ):
        try:
            dt = datetime.strptime(text.replace("Z", "+0000"), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {value}") from exc


def _fmt_outlook_restrict(dt: datetime) -> str:
    # Outlook Restrict typically expects locale-ish date; ISO-like works on many RU/EN installs with this form.
    local = dt.astimezone()
    return local.strftime("%m/%d/%Y %H:%M")


def _safe_str(value: Any, limit: int = 2000) -> str:
    try:
        text = str(value if value is not None else "")
    except Exception:
        text = ""
    return text[:limit]


def _appointment_to_dict(item: Any, *, include_body: bool = False) -> dict[str, Any]:
    body = ""
    if include_body:
        try:
            body = _safe_str(getattr(item, "Body", ""), 4000)
        except Exception:
            body = ""
    start = getattr(item, "Start", None)
    end = getattr(item, "End", None)
    return {
        "entry_id": _safe_str(getattr(item, "EntryID", ""), 256),
        "subject": _safe_str(getattr(item, "Subject", ""), 500),
        "start": _safe_str(start, 64),
        "end": _safe_str(end, 64),
        "location": _safe_str(getattr(item, "Location", ""), 300),
        "organizer": _safe_str(getattr(item, "Organizer", ""), 300),
        "required_attendees": _safe_str(getattr(item, "RequiredAttendees", ""), 1000),
        "optional_attendees": _safe_str(getattr(item, "OptionalAttendees", ""), 1000),
        "body": body,
        "all_day": bool(getattr(item, "AllDayEvent", False)),
        "busy_status": getattr(item, "BusyStatus", None),
        "categories": _safe_str(getattr(item, "Categories", ""), 200),
    }


def _stub_events_for_range(start: datetime, end: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for idx, base in enumerate(_STUB_EVENTS):
        event_start = start + timedelta(hours=10 + idx * 3)
        event_end = event_start + timedelta(hours=1)
        if event_start > end:
            event_start = start + timedelta(minutes=30 + idx * 15)
            event_end = event_start + timedelta(minutes=45)
        row = dict(base)
        row["start"] = event_start.isoformat()
        row["end"] = event_end.isoformat()
        events.append(row)
    return events


def launch_outlook(*, visible: bool = True, stub: bool = False) -> dict[str, Any]:
    if stub or not _is_windows():
        session_id = str(uuid.uuid4())
        _stub_sessions[session_id] = {"created_at": datetime.now(timezone.utc).isoformat(), "visible": visible}
        return {
            "summary": "stub Outlook launched",
            "session_id": session_id,
            "app": "outlook",
            "progid": "Outlook.Application",
            "visible": visible,
            "source": "stub",
            "platform": sys.platform,
        }

    with _lock:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        # Ensure profile/store is available; Logon is often a no-op if already running.
        try:
            namespace.Logon("", "", False, False)
        except Exception:
            pass
        if visible:
            try:
                explorers = outlook.Explorers
                if explorers.Count == 0:
                    calendar = namespace.GetDefaultFolder(OL_FOLDER_CALENDAR)
                    calendar.Display()
                else:
                    explorers.Item(1).Display()
            except Exception:
                pass
        session_id = str(uuid.uuid4())
        _outlook_sessions[session_id] = {
            "outlook": outlook,
            "namespace": namespace,
            "visible": visible,
        }
    return {
        "summary": "Outlook launched via COM",
        "session_id": session_id,
        "app": "outlook",
        "progid": "Outlook.Application",
        "visible": visible,
        "source": "com",
        "platform": sys.platform,
    }


def close_outlook(session_id: str = "", *, quit_app: bool = False, stub: bool = False) -> dict[str, Any]:
    session_id = (session_id or "").strip()

    # Allow close without session_id (sandbox chains): close the newest session.
    if not session_id:
        if _stub_sessions:
            session_id = next(reversed(_stub_sessions))
        elif _outlook_sessions:
            session_id = next(reversed(_outlook_sessions))
        else:
            return {
                "summary": "no Outlook session to close",
                "session_id": "",
                "closed": False,
                "quit": quit_app,
                "source": "stub" if stub else "com",
            }

    if stub or session_id in _stub_sessions:
        if session_id not in _stub_sessions and session_id not in _outlook_sessions:
            raise ValueError("session not found")
        _stub_sessions.pop(session_id, None)
        return {
            "summary": "stub Outlook session closed",
            "session_id": session_id,
            "closed": True,
            "quit": quit_app,
            "source": "stub",
        }

    with _lock:
        session = _outlook_sessions.pop(session_id, None)
        if not session:
            raise ValueError("session not found")
        if quit_app:
            outlook = session.get("outlook")
            if outlook is not None and hasattr(outlook, "Quit"):
                try:
                    outlook.Quit()
                except Exception:
                    pass
    return {
        "summary": "Outlook session closed",
        "session_id": session_id,
        "closed": True,
        "quit": quit_app,
        "source": "com",
    }


def calendar_list(
    *,
    session_id: str = "",
    start: Any = None,
    end: Any = None,
    days: int = 7,
    limit: int = 50,
    query: str = "",
    include_body: bool = False,
    stub: bool = False,
) -> dict[str, Any]:
    now = datetime.now().astimezone()
    start_dt = _parse_dt(start, default=now.replace(hour=0, minute=0, second=0, microsecond=0))
    if end is None or end == "":
        end_dt = start_dt + timedelta(days=max(1, min(90, int(days))))
    else:
        end_dt = _parse_dt(end)
    if end_dt < start_dt:
        raise ValueError("end must be >= start")
    limit = max(1, min(200, int(limit)))
    query = (query or "").strip().lower()

    if stub or (session_id and session_id in _stub_sessions) or (not _is_windows() and not session_id):
        # Auto-create stub session if missing for convenience in CI/demo
        if not session_id or session_id not in _stub_sessions:
            launched = launch_outlook(visible=False, stub=True)
            session_id = launched["session_id"]
        events = _stub_events_for_range(start_dt, end_dt)
        if query:
            events = [e for e in events if query in e["subject"].lower() or query in e["location"].lower()]
        events = events[:limit]
        return {
            "summary": f"stub calendar events={len(events)}",
            "session_id": session_id,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "count": len(events),
            "events": events,
            "source": "stub",
        }

    with _lock:
        session = _outlook_sessions.get(session_id) if session_id else None
        if session is None:
            # Allow one-shot list without prior launch
            launched = launch_outlook(visible=False, stub=False)
            session_id = launched["session_id"]
            session = _outlook_sessions[session_id]

        namespace = session["namespace"]
        folder = namespace.GetDefaultFolder(OL_FOLDER_CALENDAR)
        items = folder.Items
        items.IncludeRecurrences = True
        items.Sort("[Start]")
        restriction = (
            f"[Start] >= '{_fmt_outlook_restrict(start_dt)}' AND "
            f"[Start] <= '{_fmt_outlook_restrict(end_dt)}'"
        )
        try:
            restricted = items.Restrict(restriction)
        except Exception:
            restricted = items

        events: list[dict[str, Any]] = []
        # Outlook COM collections are 1-based
        count = int(getattr(restricted, "Count", 0) or 0)
        for idx in range(1, count + 1):
            if len(events) >= limit:
                break
            try:
                item = restricted.Item(idx)
            except Exception:
                continue
            row = _appointment_to_dict(item, include_body=include_body)
            if query and query not in row["subject"].lower() and query not in row["location"].lower():
                continue
            events.append(row)

    return {
        "summary": f"calendar events={len(events)}",
        "session_id": session_id,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "count": len(events),
        "events": events,
        "source": "com",
    }


def calendar_get(
    *,
    entry_id: str,
    session_id: str = "",
    include_body: bool = True,
    stub: bool = False,
) -> dict[str, Any]:
    entry_id = (entry_id or "").strip()
    if not entry_id:
        raise ValueError("entry_id required")

    if stub or (session_id and session_id in _stub_sessions) or not _is_windows():
        if not session_id or session_id not in _stub_sessions:
            launched = launch_outlook(visible=False, stub=True)
            session_id = launched["session_id"]
        for event in _stub_events_for_range(datetime.now().astimezone(), datetime.now().astimezone() + timedelta(days=7)):
            if event["entry_id"] == entry_id:
                if not include_body:
                    event = {**event, "body": ""}
                return {
                    "summary": event["subject"],
                    "session_id": session_id,
                    "event": event,
                    "source": "stub",
                }
        raise ValueError(f"appointment not found: {entry_id}")

    with _lock:
        session = _outlook_sessions.get(session_id) if session_id else None
        if session is None:
            launched = launch_outlook(visible=False, stub=False)
            session_id = launched["session_id"]
            session = _outlook_sessions[session_id]
        namespace = session["namespace"]
        try:
            item = namespace.GetItemFromID(entry_id)
        except Exception as exc:
            raise ValueError(f"appointment not found: {entry_id}") from exc
        event = _appointment_to_dict(item, include_body=include_body)
    return {
        "summary": event.get("subject") or "appointment",
        "session_id": session_id,
        "event": event,
        "source": "com",
    }

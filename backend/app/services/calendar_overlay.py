from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.calendar_overlay import CalendarOverlay

_MARKS = {
    "keep": "meeting",
    "meeting": "meeting",
    "stay": "meeting",
    "cancel": "recommend_cancel",
    "recommend_cancel": "recommend_cancel",
    "red": "recommend_cancel",
    "add": "recommend_add",
    "recommend_add": "recommend_add",
    "green": "recommend_add",
}


def _mark(value: str) -> str:
    key = (value or "").strip().casefold().replace("-", "_")
    return _MARKS.get(key, "meeting")


def _iso(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat()


def _as_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace(";", "\n").replace(",", "\n").splitlines()
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, dict):
        name = (
            value.get("name")
            or value.get("fio")
            or value.get("full_name")
            or value.get("email")
            or value.get("title")
        )
        return [str(name).strip()] if name else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_as_names(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def _as_substitutes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace(";", "\n").splitlines() if part.strip()]
    if isinstance(value, dict):
        who = str(
            value.get("who")
            or value.get("deputy")
            or value.get("substitute")
            or value.get("name")
            or value.get("fio")
            or ""
        ).strip()
        instead = str(
            value.get("instead_of")
            or value.get("replaces")
            or value.get("for")
            or value.get("absent")
            or value.get("original")
            or ""
        ).strip()
        if who and instead:
            return [f"{who} замещает {instead}"]
        if who or instead:
            return [who or instead]
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_as_substitutes(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def normalize_meetings(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("subject") or item.get("name") or "").strip()
        start = _iso(str(item.get("start") or item.get("start_at") or item.get("at") or ""))
        if not title or not start:
            continue
        end = _iso(str(item.get("end") or item.get("end_at") or ""))
        reason = str(item.get("reason") or item.get("note") or item.get("subtitle") or "").strip()
        organizer = str(item.get("organizer") or item.get("owner") or item.get("chair") or "").strip()
        location = str(item.get("location") or item.get("place") or item.get("room") or "").strip()
        attendees = _as_names(
            item.get("attendees")
            or item.get("required_attendees")
            or item.get("participants")
            or item.get("people")
        )
        optional = _as_names(item.get("optional_attendees"))
        for name in optional:
            if name not in attendees:
                attendees.append(name)
        substitutes = _as_substitutes(
            item.get("substitutes")
            or item.get("replacements")
            or item.get("deputies")
            or item.get("who_replaces")
        )
        row: dict[str, Any] = {
            "title": title,
            "start": start,
            "end": end,
            "mark": _mark(str(item.get("mark") or item.get("color") or item.get("kind") or "")),
            "reason": reason,
        }
        if organizer:
            row["organizer"] = organizer
        if location:
            row["location"] = location
        if attendees:
            row["attendees"] = attendees
        if substitutes:
            row["substitutes"] = substitutes
        out.append(row)
    return out


def upsert_overlay(
    db: Session,
    *,
    user_id: str,
    workflow_id: str = "",
    run_id: str = "",
    meetings: Any,
) -> CalendarOverlay:
    uid = (user_id or "").strip()
    wid = (workflow_id or "").strip()
    items = normalize_meetings(meetings)
    row = (
        db.query(CalendarOverlay)
        .filter(CalendarOverlay.user_id == uid, CalendarOverlay.workflow_id == wid)
        .one_or_none()
    )
    if row is None:
        row = CalendarOverlay(
            id=uuid4().hex,
            user_id=uid,
            workflow_id=wid,
            run_id=(run_id or "").strip(),
            meetings=items,
        )
        db.add(row)
    else:
        row.run_id = (run_id or "").strip() or row.run_id
        row.meetings = items
    db.commit()
    db.refresh(row)
    return row


def list_overlays(db: Session, *, user_id: str, workflow_id: str = "") -> list[CalendarOverlay]:
    query = db.query(CalendarOverlay).filter(CalendarOverlay.user_id == (user_id or "").strip())
    wanted = (workflow_id or "").strip()
    if wanted:
        query = query.filter(CalendarOverlay.workflow_id == wanted)
    return list(query.all())

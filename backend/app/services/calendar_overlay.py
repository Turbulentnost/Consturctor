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


def normalize_meetings(raw: Any) -> list[dict[str, str]]:
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("subject") or item.get("name") or "").strip()
        start = _iso(str(item.get("start") or item.get("start_at") or item.get("at") or ""))
        if not title or not start:
            continue
        end = _iso(str(item.get("end") or item.get("end_at") or ""))
        reason = str(item.get("reason") or item.get("note") or item.get("subtitle") or "").strip()
        out.append(
            {
                "title": title,
                "start": start,
                "end": end,
                "mark": _mark(str(item.get("mark") or item.get("color") or item.get("kind") or "")),
                "reason": reason,
            }
        )
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

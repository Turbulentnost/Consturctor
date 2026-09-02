from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services.calendar_overlay import normalize_meetings, upsert_overlay
from app.services.workflows.board_live import push_board_updated

router = APIRouter(prefix="/calendar", tags=["calendar"])


class CalendarMeetingIn(BaseModel):
    title: str = ""
    start: str = ""
    end: str = ""
    mark: str = "keep"
    reason: str = ""


class CalendarOverlayIn(BaseModel):
    workflow_id: str = ""
    run_id: str = ""
    meetings: list[CalendarMeetingIn] = Field(default_factory=list)


@router.post("/overlays")
def save_calendar_overlay(
    body: CalendarOverlayIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    raw = [item.model_dump() for item in body.meetings]
    row = upsert_overlay(
        db,
        user_id=auth.user_id,
        workflow_id=body.workflow_id,
        run_id=body.run_id,
        meetings=raw,
    )
    push_board_updated(
        db,
        user_id=auth.user_id,
        workflow_id=body.workflow_id,
        reason="calendar_overlay",
    )
    shown = normalize_meetings(row.meetings)
    return {"ok": True, "id": row.id, "shown": len(shown), "meetings": shown}

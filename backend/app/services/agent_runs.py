from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.schemas.workflow import AgentRunOut
from app.services.workflows.service import _get_owned, _iso


def start_agent_run(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    source: str = "chat",
) -> AgentRun:
    _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    kind = (source or "chat").strip() or "chat"
    if kind not in {"chat", "trigger"}:
        kind = "chat"
    row = AgentRun(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        user_id=user_id,
        message=(message or "").strip(),
        status="started",
        source=kind,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_agent_run(
    db: Session,
    *,
    run_id: str,
    status: str,
    answer: str = "",
) -> None:
    row = db.get(AgentRun, run_id)
    if row is None:
        return
    row.status = "ok" if status == "ok" else "error"
    row.answer = (answer or "").strip()[:4000]
    row.finished_at = datetime.now(timezone.utc)
    db.commit()


def list_agent_runs(db: Session, *, user_id: str, workflow_id: str) -> list[AgentRunOut]:
    _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    rows = (
        db.execute(
            select(AgentRun)
            .where(AgentRun.workflow_id == workflow_id, AgentRun.user_id == user_id)
            .order_by(AgentRun.started_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return [_to_out(row) for row in rows]


def answer_from_result(result: Any) -> str:
    if isinstance(result, dict):
        text = str(result.get("answer") or result.get("text") or "").strip()
        if text:
            return text
        return str(result)[:400]
    return str(result or "").strip()


def _to_out(row: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=row.id,
        workflow_id=row.workflow_id,
        message=row.message or "",
        status=row.status or "",
        answer=row.answer or "",
        source=row.source or "chat",
        started_at=_iso(row.started_at),
        finished_at=_iso(row.finished_at) if row.finished_at else "",
    )

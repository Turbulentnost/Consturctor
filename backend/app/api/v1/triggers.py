from __future__ import annotations

import json
import logging
from queue import Queue
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import SessionLocal, get_db
from app.schemas.trigger import TriggerCreate, TriggerFiredAck, TriggerList, TriggerOut
from app.services.tool_bridge import tool_bridge
from app.services.triggers.check import check_trigger_condition
from app.services.triggers.service import (
    TriggerError,
    cancel_trigger,
    create_trigger,
    list_triggers,
    mark_fired,
)
from app.services.workflows.cursor_tools import clear_tool_context, set_tool_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


def _raise(exc: TriggerError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.post("", response_model=TriggerOut)
def create_trigger_endpoint(
    body: TriggerCreate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TriggerOut:
    try:
        return create_trigger(db, owner_user_id=auth.user_id, payload=body)
    except TriggerError as exc:
        _raise(exc)
        raise


@router.get("", response_model=TriggerList)
def read_triggers(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TriggerList:
    return TriggerList(items=list_triggers(db, user_id=auth.user_id))


@router.post("/{trigger_id}/cancel", response_model=TriggerOut)
def cancel_trigger_endpoint(
    trigger_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TriggerOut:
    try:
        return cancel_trigger(db, user_id=auth.user_id, trigger_id=trigger_id)
    except TriggerError as exc:
        _raise(exc)
        raise


@router.post("/{trigger_id}/ack-fired", response_model=TriggerOut)
def ack_fired_endpoint(
    trigger_id: str,
    body: TriggerFiredAck | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TriggerOut:
    try:
        return mark_fired(
            db,
            user_id=auth.user_id,
            trigger_id=trigger_id,
            evidence=(body.evidence if body else "") or "",
        )
    except TriggerError as exc:
        _raise(exc)
        raise


@router.post("/{trigger_id}/check/stream")
def check_trigger_stream(
    trigger_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        _check_stream(user_id=auth.user_id, trigger_id=trigger_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _check_stream(*, user_id: str, trigger_id: str):
    queue: Queue[dict | None] = Queue()
    run_id = tool_bridge.new_run_id()

    def emit(payload: dict) -> None:
        queue.put(payload)

    def run() -> None:
        db = SessionLocal()
        tool_bridge.register_run(run_id, user_id)
        set_tool_context(run_id, user_id)
        try:
            emit({"type": "run", "run_id": run_id})
            result = check_trigger_condition(
                db,
                user_id=user_id,
                trigger_id=trigger_id,
                emit=emit,
            )
            emit({"type": "done", "result": result})
        except TriggerError as exc:
            emit({"type": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Trigger check failed id=%s", trigger_id)
            emit({"type": "error", "message": str(exc)})
        finally:
            clear_tool_context()
            tool_bridge.unregister_run(run_id)
            db.close()
            queue.put(None)

    Thread(target=run, daemon=True).start()
    while True:
        item = queue.get()
        if item is None:
            break
        yield _sse(item)


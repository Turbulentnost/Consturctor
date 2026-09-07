from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.workflow import Workflow
from app.services import agent_kpi
from app.services.triggers.service import workflow_is_inactive

logger = logging.getLogger(__name__)


def list_due_workflows(db: Session, *, now: datetime | None = None) -> list[tuple[Workflow, list[str]]]:
    now = now or datetime.now(timezone.utc)
    rows = list(db.execute(select(Workflow)).scalars().all())
    due: list[tuple[Workflow, list[str]]] = []
    for row in rows:
        local = row.local_run if isinstance(row.local_run, dict) else {}
        if workflow_is_inactive(row):
            continue
        kpi = local.get("kpi") if isinstance(local.get("kpi"), dict) else None
        if not kpi or not (kpi.get("tiles") or []):
            continue
        if agent_kpi.is_calc_lock_active(kpi.get("calculating_at"), now):
            continue
        tile_ids = agent_kpi.due_tile_ids(kpi, now)
        if tile_ids:
            due.append((row, tile_ids))
    return due


def calculate_workflow_kpi(db: Session, row: Workflow, tile_ids: list[str]) -> None:
    """Fill KPI facts from stored runs. Do not call Cursor: that blocks the API process."""
    local = dict(row.local_run or {})
    kpi = dict(local.get("kpi") or {})
    tiles = [item for item in (kpi.get("tiles") or []) if isinstance(item, dict)]
    wanted = {item for item in tile_ids if str(item or "").strip()}
    due = [item for item in tiles if str(item.get("id") or "") in wanted]
    if not due:
        return
    draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    runs = agent_kpi.list_runs_for_kpi(db, user_id=row.user_id, workflow_id=row.id)
    updates = agent_kpi.local_calc_updates(due, runs, draft)
    kpi = agent_kpi.apply_calc_updates(kpi, updates, due_ids=wanted)
    kpi["calculating_at"] = ""
    local["kpi"] = kpi
    row.local_run = local
    db.commit()
    logger.info(
        "KPI calc done workflow=%s tiles=%s updates=%s source=local",
        row.id,
        list(wanted),
        [item.get("id") for item in updates],
    )


def run_due_kpi_calculations() -> int:
    db = SessionLocal()
    try:
        due = list_due_workflows(db)
        if not due:
            return 0
        row, tile_ids = due[0]
        calculate_workflow_kpi(db, row, tile_ids)
        return 1
    except Exception:
        logger.exception("KPI scheduler tick failed")
        return 0
    finally:
        db.close()

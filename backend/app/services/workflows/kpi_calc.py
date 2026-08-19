from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.workflow import Workflow
from app.services import agent_kpi
from app.services.triggers.service import is_workflow_paused
from app.services.workflows import prompts
from app.services.workflows.plan_models import WorkflowPlan

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL_SEC = 30
MAX_WORKFLOWS_PER_TICK = 5


def list_due_workflows(db: Session, *, now: datetime | None = None) -> list[tuple[Workflow, list[str]]]:
    now = now or datetime.now(timezone.utc)
    rows = list(db.execute(select(Workflow)).scalars().all())
    due: list[tuple[Workflow, list[str]]] = []
    for row in rows:
        if str(getattr(row, "phase", "") or "") != "done":
            continue
        local = row.local_run if isinstance(row.local_run, dict) else {}
        if is_workflow_paused(local):
            continue
        kpi = local.get("kpi") if isinstance(local.get("kpi"), dict) else None
        if not kpi or not (kpi.get("tiles") or []):
            continue
        if str(kpi.get("status") or "") != "ready":
            continue
        if agent_kpi.is_calc_lock_active(kpi.get("calculating_at"), now):
            continue
        tile_ids = agent_kpi.due_tile_ids(kpi, now)
        if tile_ids:
            due.append((row, tile_ids))
    return due


def calculate_workflow_kpi(db: Session, row: Workflow, tile_ids: list[str]) -> None:
    local = dict(row.local_run or {})
    kpi = dict(local.get("kpi") or {})
    tiles = [item for item in (kpi.get("tiles") or []) if isinstance(item, dict)]
    due = [item for item in tiles if str(item.get("id") or "") in set(tile_ids)]
    if not due:
        return
    kpi["calculating_at"] = datetime.now(timezone.utc).isoformat()
    local["kpi"] = kpi
    row.local_run = local
    db.commit()

    draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    title = str(draft.get("name") or row.title or plan.title or "ИИ-агент")
    goal = str(draft.get("goal") or plan.goal or "")
    runs = agent_kpi.list_runs_for_kpi(db, user_id=row.user_id, workflow_id=row.id)
    prompt = prompts.build_kpi_calc_prompt(
        title=title,
        goal=goal,
        plan_text=prompts.plan_summary_text(plan),
        schedule_draft=draft,
        tiles=due,
        runs=agent_kpi.runs_digest(runs),
    )
    due_set = set(tile_ids)
    fallback = agent_kpi.build_deterministic_calc_updates(kpi, runs, draft, due_ids=due_set)
    updates: list[dict] = []
    try:
        from app.services.workflows.service import _create_exec_agent, _stream_run

        agent_id, run_id = _create_exec_agent(f"KPI calc · {title}", prompt)
        result = _stream_run(agent_id, run_id)
        updates = agent_kpi.parse_calc_payload(result.text or "")
        if result.error and not updates:
            raise RuntimeError(result.error)
        seen = {str(item.get("id") or "") for item in updates}
        for item in fallback:
            if item["id"] not in seen:
                updates.append(item)
        kpi = agent_kpi.apply_calc_updates(kpi, updates, due_ids=due_set)
        logger.info(
            "KPI calc done workflow=%s tiles=%s updates=%s",
            row.id,
            tile_ids,
            [item.get("id") for item in updates],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("KPI calc failed workflow=%s: %s", row.id, exc)
        kpi = agent_kpi.apply_calc_updates(kpi, fallback, due_ids=due_set)
    finally:
        kpi["calculating_at"] = ""
        local = dict(row.local_run or {})
        local["kpi"] = kpi
        row.local_run = local
        db.commit()


def run_due_kpi_calculations() -> int:
    db = SessionLocal()
    try:
        due = list_due_workflows(db)
        if not due:
            return 0
        processed = 0
        for row, tile_ids in due[:MAX_WORKFLOWS_PER_TICK]:
            calculate_workflow_kpi(db, row, tile_ids)
            processed += 1
        return processed
    except Exception:
        logger.exception("KPI scheduler tick failed")
        return 0
    finally:
        db.close()


async def kpi_scheduler() -> None:
    while True:
        await asyncio.sleep(SCHEDULER_INTERVAL_SEC)
        try:
            await asyncio.to_thread(run_due_kpi_calculations)
        except Exception:  # noqa: BLE001
            logger.exception("KPI scheduler tick failed")

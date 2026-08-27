"""Celery tasks: enqueue and execute due agent runs and KPI calcs."""

from __future__ import annotations

import logging

from celery import shared_task

from app.db.session import SessionLocal
from app.models.workflow import Workflow
from app.services.triggers.runner import execute_scheduled_agent_run
from app.services.triggers.service import (
    agent_run_task_id,
    claim_due_agent_jobs,
    kpi_calc_task_id,
)
from app.services.orchestrator.service import (
    dispatch_due_orchestrator,
    list_due_orchestrators,
    orch_calc_task_id,
)
from app.services.workflows.kpi_calc import calculate_workflow_kpi, list_due_workflows

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.scheduled.enqueue_due_agent_runs")
def enqueue_due_agent_runs(user_id: str | None = None) -> int:
    db = SessionLocal()
    queued = 0
    try:
        for row in claim_due_agent_jobs(db, user_id=user_id):
            task_id = agent_run_task_id(
                row.id,
                interval_seconds=int(row.interval_seconds or 0),
                fire_at=row.fire_at,
            )
            run_scheduled_agent.apply_async(args=[row.id], task_id=task_id)
            queued += 1
    except Exception:
        logger.exception("Failed to enqueue due agent runs")
        raise
    finally:
        db.close()
    return queued


@shared_task(name="app.tasks.scheduled.enqueue_due_kpi")
def enqueue_due_kpi() -> int:
    db = SessionLocal()
    queued = 0
    try:
        for row, tile_ids in list_due_workflows(db):
            task_id = kpi_calc_task_id(row.id, tile_ids)
            calc_workflow_kpi.apply_async(args=[row.id, tile_ids], task_id=task_id)
            queued += 1
    except Exception:
        logger.exception("Failed to enqueue due KPI")
        raise
    finally:
        db.close()
    return queued


@shared_task(name="app.tasks.scheduled.run_scheduled_agent", acks_late=True)
def run_scheduled_agent(trigger_id: str) -> dict:
    db = SessionLocal()
    try:
        return execute_scheduled_agent_run(db, trigger_id=trigger_id)
    finally:
        db.close()


@shared_task(name="app.tasks.scheduled.enqueue_due_orchestrator_kpi")
def enqueue_due_orchestrator_kpi() -> int:
    db = SessionLocal()
    queued = 0
    try:
        for row, tile_ids in list_due_orchestrators(db):
            task_id = orch_calc_task_id(row.user_id, tile_ids)
            run_orchestrator_kpi.apply_async(args=[row.id, tile_ids], task_id=task_id)
            queued += 1
    except Exception:
        logger.exception("Failed to enqueue due orchestrator KPI")
        raise
    finally:
        db.close()
    return queued


@shared_task(name="app.tasks.scheduled.run_orchestrator_kpi", acks_late=True)
def run_orchestrator_kpi(orchestrator_id: str, tile_ids: list[str]) -> dict:
    from app.models.orchestrator import UserOrchestrator

    db = SessionLocal()
    try:
        row = db.get(UserOrchestrator, orchestrator_id)
        if row is None:
            return {"ok": False, "reason": "missing"}
        dispatched = dispatch_due_orchestrator(db, row, tile_ids)
        return {
            "ok": dispatched,
            "user_id": row.user_id,
            "tiles": tile_ids,
        }
    finally:
        db.close()


@shared_task(name="app.tasks.scheduled.calc_workflow_kpi", acks_late=True)
def calc_workflow_kpi(workflow_id: str, tile_ids: list[str]) -> dict:
    db = SessionLocal()
    try:
        row = db.get(Workflow, workflow_id)
        if row is None:
            return {"ok": False, "reason": "missing"}
        calculate_workflow_kpi(db, row, tile_ids)
        return {"ok": True, "workflow_id": workflow_id, "tiles": tile_ids}
    finally:
        db.close()

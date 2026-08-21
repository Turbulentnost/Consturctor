"""Celery app: scheduled agent runs and KPI calculations."""

from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "constructor",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    timezone="UTC",
    enable_utc=True,
    imports=("app.tasks.scheduled",),
    beat_schedule={
        "enqueue-due-agent-runs": {
            "task": "app.tasks.scheduled.enqueue_due_agent_runs",
            "schedule": 20.0,
        },
        "enqueue-due-kpi": {
            "task": "app.tasks.scheduled.enqueue_due_kpi",
            "schedule": 30.0,
        },
    },
)
celery_app.set_default()

"""In-process due-trigger tick so scheduled runs work without Celery/Redis."""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.services.triggers.runner import execute_scheduled_agent_run
from app.services.triggers.service import claim_due_agent_jobs

logger = logging.getLogger(__name__)


def tick_due_triggers() -> int:
    db = SessionLocal()
    ran = 0
    try:
        for row in claim_due_agent_jobs(db):
            execute_scheduled_agent_run(db, trigger_id=row.id)
            ran += 1
    except Exception:
        logger.exception("Trigger tick failed")
        raise
    finally:
        db.close()
    return ran

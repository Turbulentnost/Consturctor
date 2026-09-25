"""Persist the daily AST00 + PSD protocol playbook on the published agent.

Usage (from backend/):
  py -3.13 scripts/patch_daily_assignment_chain.py
  py -3.13 scripts/patch_daily_assignment_chain.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal, init_db
from app.models.workflow import Workflow
from app.services.workflows.daily_assignment_playbook import (
    apply_daily_assignment_config,
    apply_daily_assignment_plan_runtime,
    daily_assignment_playbook_draft,
)

WORKFLOW_ID = "af314914-bb0a-4cb7-95e0-6ef87698d3f5"


def patch(*, dry_run: bool = False) -> dict:
    init_db()
    db = SessionLocal()
    try:
        row = db.get(Workflow, WORKFLOW_ID)
        if row is None:
            raise SystemExit(f"workflow {WORKFLOW_ID} not found")
        local = apply_daily_assignment_config(
            dict(row.local_run or {}),
            title=row.title or "",
            notes=row.notes or "",
        )
        plan = apply_daily_assignment_plan_runtime(
            dict(row.plan_json or {}) if isinstance(row.plan_json, dict) else {},
            title=row.title or "",
            notes=row.notes or "",
        )
        playbook = local.get("playbook") or {}
        row.local_run = local
        row.plan_json = plan
        flag_modified(row, "local_run")
        flag_modified(row, "plan_json")
        steps = [f"{step.get('id')} {step.get('tool')}" for step in playbook.get("steps") or []]
        if dry_run:
            print(f"DRY-RUN {row.id} {row.title}")
            print("steps:", steps)
            print("tools:", playbook.get("tools"))
            return {"workflowId": row.id, "dryRun": True, "steps": steps}
        db.add(row)
        db.commit()
        print(f"PATCHED {row.id} {row.title}")
        print("steps:", steps)
        return {
            "workflowId": row.id,
            "title": row.title,
            "steps": len(daily_assignment_playbook_draft()["steps"]),
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    patch(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

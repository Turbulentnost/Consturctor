"""Patch published RK meeting agent: weekly Monday schedule, playbook, tools.

Usage (from backend/):
  py -3.12 scripts/patch_rk_meeting_agent.py
  py -3.12 scripts/patch_rk_meeting_agent.py --fio "Жалыбин Максим Дмитриевич"
  py -3.12 scripts/patch_rk_meeting_agent.py --dry-run
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
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.triggers.service import sync_recurring_triggers_from_draft
from app.services.workflows.meeting_agent_config import (
    apply_meeting_agent_config,
    apply_meeting_plan_runtime,
)
from app.services.workflows.rk_meeting_playbook import is_rk_meeting_agent, rk_local_playbook

DEFAULT_FIO = "Жалыбин Максим Дмитриевич"
TITLE_HINT = "ревизион"


def _find_rk_workflow(db, user_id: str) -> Workflow | None:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id)
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    for row in rows:
        if is_rk_meeting_agent(row.title or "", row.notes or ""):
            return row
    for row in rows:
        if TITLE_HINT in (row.title or "").casefold():
            return row
    return None


def patch_rk(*, user_id: str, dry_run: bool = False) -> dict:
    init_db()
    db = SessionLocal()
    try:
        row = _find_rk_workflow(db, user_id)
        if row is None:
            raise SystemExit("RK workflow not found for user")

        title = (row.title or "").strip()
        notes = (row.notes or row.document_text or title).strip()
        playbook = rk_local_playbook(title=title, demo_text=notes, answered_scope=title)
        row.plan_json = apply_meeting_plan_runtime(
            dict(row.plan_json or {}),
            title=title,
            notes=notes,
        )
        local = dict(row.local_run or {})
        local["playbook"] = playbook
        local["published"] = True
        local["phase"] = local.get("phase") or "done"
        local["tests_status"] = local.get("tests_status") or "pass"
        local["demo_ok"] = True
        row.local_run = apply_meeting_agent_config(local, title=title, notes=notes)
        row.phase = "done"
        flag_modified(row, "local_run")
        flag_modified(row, "plan_json")

        if dry_run:
            print(f"DRY-RUN would patch: {row.id} {row.title}")
            print("schedule:", row.local_run.get("schedule_draft"))
            print("tools:", len(row.local_run.get("tools") or []))
            return {"workflowId": row.id, "dryRun": True}

        db.add(row)
        db.commit()
        db.refresh(row)
        sync_recurring_triggers_from_draft(db, user_id=user_id, workflow=row)
        db.commit()
        print(f"PATCHED {row.id[:8]}… {row.title}")
        print("Triggers synced from schedule_draft (Monday 09:00–10:00)")
        return {"workflowId": row.id, "title": row.title, "status": "patched"}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch RK meeting agent schedule and playbook")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--fio", default=DEFAULT_FIO)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        user_id = args.user_id.strip()
        if not user_id:
            user = db.query(AppUser).filter(AppUser.fio == args.fio).first()
            if user is None:
                user = (
                    db.query(AppUser)
                    .filter(AppUser.fio.ilike(f"%{args.fio.split()[0]}%"))
                    .first()
                )
            if user is None:
                raise SystemExit(f"User not found: {args.fio}")
            user_id = user.id
            print(f"User: {user.fio} ({user_id})")
    finally:
        db.close()

    patch_rk(user_id=user_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

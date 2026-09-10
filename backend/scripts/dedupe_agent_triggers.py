"""Disable duplicate enabled passport triggers (keep one per workflow).

Usage (from backend/):
  py -3.12 scripts/dedupe_agent_triggers.py
  py -3.12 scripts/dedupe_agent_triggers.py --fio "Жалыбин Максим Дмитриевич"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select

from app.db.session import SessionLocal, init_db
from app.models.trigger import AgentTrigger
from app.models.user import AppUser
from app.services.triggers.service import _is_passport_trigger
from app.models.workflow import Workflow

DEFAULT_FIO = "Жалыбин Максим Дмитриевич"


def dedupe(*, user_id: str, dry_run: bool = False) -> int:
    init_db()
    db = SessionLocal()
    disabled = 0
    try:
        workflows = (
            db.query(Workflow)
            .filter(Workflow.user_id == user_id, Workflow.phase == "done")
            .all()
        )
        for workflow in workflows:
            rows = list(
                db.execute(
                    select(AgentTrigger).where(
                        AgentTrigger.owner_user_id == user_id,
                        AgentTrigger.workflow_id == workflow.id,
                        AgentTrigger.enabled.is_(True),
                    ).order_by(AgentTrigger.created_at.asc())
                ).scalars()
            )
            passport = [row for row in rows if _is_passport_trigger(row)]
            if len(passport) <= 1:
                continue
            keep = passport[-1]
            for row in passport:
                if row.id == keep.id:
                    continue
                if dry_run:
                    print(f"DRY disable trigger {row.id[:8]}… wf={workflow.title}")
                else:
                    row.enabled = False
                disabled += 1
            if not dry_run:
                db.commit()
                print(f"DEDUPED {workflow.title}: kept 1 of {len(passport)} triggers")
        return disabled
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Disable duplicate agent triggers")
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
                raise SystemExit(f"User not found: {args.fio}")
            user_id = user.id
            print(f"User: {user.fio} ({user_id})")
    finally:
        db.close()

    count = dedupe(user_id=user_id, dry_run=args.dry_run)
    print(f"Disabled duplicate triggers: {count}")


if __name__ == "__main__":
    main()

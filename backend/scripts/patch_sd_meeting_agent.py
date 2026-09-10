"""Patch published SD meeting agents: playbook without mail/IMAP loops.

Usage (from backend/):
  py -3.12 scripts/patch_sd_meeting_agent.py
  py -3.12 scripts/patch_sd_meeting_agent.py --all
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
from app.services.workflows.meeting_agent_config import (
    apply_meeting_agent_config,
    apply_meeting_plan_runtime,
)
from app.services.workflows.sd_meeting_playbook import is_sd_meeting_agent, sd_runtime_tools

DEFAULT_FIOS = (
    "Жалыбин Максим Дмитриевич",
    "Комарькова Анастасия Эдуардовна",
)
SERIES_MARKER = "самый ранний удобный свободный день"


def _find_sd_workflows(db, user_id: str) -> list[Workflow]:
    rows = db.query(Workflow).filter(Workflow.user_id == user_id).all()
    return [row for row in rows if is_sd_meeting_agent(row.title or "")]


def _strip_series_rule(text: str) -> str:
    raw = (text or "").strip()
    if SERIES_MARKER not in raw.casefold() and SERIES_MARKER not in raw:
        return raw
    parts = raw.split("\n\n")
    kept = [part for part in parts if SERIES_MARKER not in part]
    return "\n\n".join(kept).strip()


def patch_sd(*, user_id: str, dry_run: bool = False) -> list[dict]:
    out: list[dict] = []
    db = SessionLocal()
    try:
        rows = _find_sd_workflows(db, user_id)
        if not rows:
            print(f"No SD workflow for {user_id}")
            return out
        for row in rows:
            title = (row.title or "").strip()
            notes = (row.notes or row.document_text or title).strip()
            row.plan_json = apply_meeting_plan_runtime(
                dict(row.plan_json or {}),
                title=title,
                notes=notes,
            )
            local = apply_meeting_agent_config(dict(row.local_run or {}), title=title, notes=notes)
            playbook = dict(local.get("playbook") or {})
            playbook["instructions"] = _strip_series_rule(str(playbook.get("instructions") or ""))
            local["playbook"] = playbook
            local["tools"] = sd_runtime_tools()
            local["published"] = True
            row.local_run = local
            flag_modified(row, "local_run")
            flag_modified(row, "plan_json")
            info = {
                "workflowId": row.id,
                "title": row.title,
                "tools": local.get("tools"),
            }
            out.append(info)
            if dry_run:
                print(f"DRY-RUN {row.id} {row.title}")
                continue
            db.add(row)
        if not dry_run:
            db.commit()
        for item in out:
            print(f"PATCHED {item['workflowId']} {item['title']}")
        return out
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch SD meeting agent playbook and tools")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--fio", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        users: list[AppUser] = []
        if args.user_id.strip():
            user = db.query(AppUser).filter(AppUser.id == args.user_id.strip()).first()
            if user is None:
                raise SystemExit(f"User not found: {args.user_id}")
            users = [user]
        elif args.fio.strip():
            user = db.query(AppUser).filter(AppUser.fio == args.fio.strip()).first()
            if user is None:
                raise SystemExit(f"User not found: {args.fio}")
            users = [user]
        else:
            for fio in DEFAULT_FIOS:
                user = db.query(AppUser).filter(AppUser.fio == fio).first()
                if user is not None:
                    users.append(user)
            if not users:
                raise SystemExit("Default SD owners not found")
    finally:
        db.close()

    for user in users:
        print(f"User: {user.fio} ({user.id})")
        patch_sd(user_id=user.id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

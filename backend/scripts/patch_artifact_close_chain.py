"""Lock published artifact-close agents onto the journal + files chain.

Usage (from backend/):
  py -3.13 scripts/patch_artifact_close_chain.py
  py -3.13 scripts/patch_artifact_close_chain.py --dry-run
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
from app.services.workflows.artifact_close_playbook import (
    apply_artifact_close_config,
    apply_artifact_close_plan_runtime,
    artifact_close_runtime_tools,
    is_artifact_close_agent,
)


def _strip_rk_answers(plan: dict) -> dict:
    answers = []
    for item in plan.get("answered_questions") or []:
        if not isinstance(item, dict):
            continue
        blob = f"{item.get('question') or ''} {item.get('answer') or ''}".casefold()
        if "ревизион" in blob or "реестр_поручений" in blob or "артефакты" == str(item.get("question") or "").casefold():
            continue
        answers.append(item)
    plan["answered_questions"] = answers
    return plan


def patch(*, dry_run: bool = False, fio: str = "") -> list[dict]:
    init_db()
    db = SessionLocal()
    updated: list[dict] = []
    try:
        query = db.query(Workflow).filter(Workflow.phase != "deleted")
        if fio.strip():
            users = db.query(AppUser).filter(AppUser.fio.ilike(f"%{fio.strip()}%")).all()
            ids = [user.id for user in users]
            query = query.filter(Workflow.user_id.in_(ids or ["-"]))
        rows = query.all()
        for row in rows:
            if not is_artifact_close_agent(row.title or "", row.notes or "", row.document_text or ""):
                continue
            local = apply_artifact_close_config(
                dict(row.local_run or {}),
                title=row.title or "",
                notes=row.notes or "",
            )
            local["tools"] = artifact_close_runtime_tools()
            local["published"] = True
            local["demo_ok"] = True
            plan = apply_artifact_close_plan_runtime(
                dict(row.plan_json or {}) if isinstance(row.plan_json, dict) else {},
                title=row.title or "",
                notes=row.notes or "",
            )
            plan = _strip_rk_answers(plan)
            row.local_run = local
            row.plan_json = plan
            flag_modified(row, "local_run")
            flag_modified(row, "plan_json")
            item = {
                "id": row.id,
                "title": row.title,
                "user_id": row.user_id,
                "steps": [step.get("id") for step in (local.get("playbook") or {}).get("steps") or []],
            }
            updated.append(item)
            print(f"{'DRY-RUN' if dry_run else 'PATCHED'} {row.id} {row.title}")
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return updated
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fio", default="Ильченко")
    args = parser.parse_args()
    rows = patch(dry_run=args.dry_run, fio=args.fio)
    print(f"count={len(rows)}")


if __name__ == "__main__":
    main()

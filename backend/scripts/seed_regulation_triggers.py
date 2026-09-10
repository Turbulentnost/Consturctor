"""Attach Monday morning schedule triggers to regulation batch agents.

Schedule (MSK): every Monday, 09:00–10:00 every 10 minutes
(09:00, 09:10, 09:20, 09:30, 09:40, 09:50, 10:00).

Usage (from backend/):
  py -3.12 scripts/seed_regulation_triggers.py
  py -3.12 scripts/seed_regulation_triggers.py --fio "Жалыбин Максим Дмитриевич"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal, init_db
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.schemas.trigger import ScheduleTriggerSpec
from app.services.triggers.service import sync_recurring_triggers_from_draft

DEFAULT_FIO = "Жалыбин Максим Дмитриевич"

# Agents from «на разработку ИИ-агента рабочего места 1.docx»
REGULATION_AGENT_TITLE_KEYS = [
    "еженедельный отчёт",
    "реестра подарков",
    "данных kpi",
    "утреннего доклада",
    "распознавания аудио",
    "технических замечаний",
    "версий нормативных",
]

MONDAY_MORNING_TRIGGER = ScheduleTriggerSpec(
    kind="interval",
    message="Плановый запуск: понедельник до 10:00 (каждые 10 мин)",
    interval_value=10,
    interval_unit="minutes",
    weekdays=[0],  # 0 = Monday (MSK)
    window_start="09:00",
    window_end="10:00",
    once=False,
)


def _normalize_title(title: str) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip().casefold())
    return text.replace("ии-агент:", "").strip()


def _schedule_draft_payload() -> dict:
    spec = MONDAY_MORNING_TRIGGER.model_dump(mode="json")
    return {
        "name": "",
        "goal": "",
        "triggers": [spec],
    }


def apply_monday_trigger(db, row: Workflow, *, user_id: str) -> None:
    local = dict(row.local_run or {})
    local["schedule_draft"] = _schedule_draft_payload()
    row.local_run = local
    flag_modified(row, "local_run")
    db.add(row)
    db.flush()
    sync_recurring_triggers_from_draft(db, user_id=user_id, workflow=row)


def seed_triggers(
    *,
    user_id: str,
    title_keys: list[str] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    keys = title_keys or REGULATION_AGENT_TITLE_KEYS
    init_db()
    db = SessionLocal()
    applied: list[dict] = []
    try:
        rows = (
            db.query(Workflow)
            .filter(Workflow.user_id == user_id, Workflow.phase == "done")
            .order_by(Workflow.updated_at.desc())
            .all()
        )
        seen: set[str] = set()
        for key in keys:
            norm_key = _normalize_title(key)
            if norm_key in seen:
                continue
            match = next(
                (row for row in rows if norm_key in _normalize_title(row.title or "")),
                None,
            )
            if match is None:
                print(f"MISSING: {key}")
                continue
            seen.add(norm_key)
            if dry_run:
                print(f"DRY trigger: {match.title}")
                continue
            apply_monday_trigger(db, match, user_id=user_id)
            applied.append({"workflowId": match.id, "title": match.title})
            print(f"TRIGGER {match.id[:8]}… {match.title}")
        if not dry_run:
            db.commit()
        return applied
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Monday 9–10 triggers for regulation agents")
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

    items = seed_triggers(user_id=user_id, dry_run=args.dry_run)
    print(f"\nTriggers set: {len(items)}")


if __name__ == "__main__":
    main()

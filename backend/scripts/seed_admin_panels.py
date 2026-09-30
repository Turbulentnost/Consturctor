"""Назначить default прежним администраторам и finance финансовым должностям.

Запускать после синхронизации оргструктуры:
    python scripts/seed_admin_panels.py
"""

from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.org import (
    AdminPanelAssignment,
    AdminUserPanelAssignment,
    OrgMember,
    OrgPosition,
)
from app.services.org_structure import fio_key

LEGACY_ADMIN_FIOS = (
    "Уставицкий Андрей Алексеевич",
    "Жалыбин Максим Дмитриевич",
    "Жалыбин Максим Димитриевич",
)
FINANCE_POSITION_NAMES = (
    "Финансовый директор",
    "Ведущий бухгалтер по заработной плате",
)
PERSONAL_FINANCE_ADMIN_FIOS = ("Комарькова Анастасия Эдуардовна",)


def seed_default_panel() -> tuple[int, list[str]]:
    keys = {fio_key(fio) for fio in LEGACY_ADMIN_FIOS}
    with SessionLocal() as db:
        members = db.scalars(
            select(OrgMember)
            .join(OrgPosition, OrgPosition.id == OrgMember.position_id)
            .where(
                OrgMember.fio_key.in_(keys),
                OrgMember.position_id.is_not(None),
                OrgPosition.is_active.is_(True),
            )
        ).all()
        found_keys = {member.fio_key for member in members}
        missing = sorted(keys - found_keys)
        changed = 0
        for position_id in {member.position_id for member in members if member.position_id}:
            assignment = db.get(AdminPanelAssignment, position_id)
            if assignment is None:
                db.add(AdminPanelAssignment(position_id=position_id, panel_key="default"))
                changed += 1
            elif assignment.panel_key != "default":
                assignment.panel_key = "default"
                changed += 1
        finance_positions = db.scalars(
            select(OrgPosition).where(
                OrgPosition.name.in_(FINANCE_POSITION_NAMES),
                OrgPosition.is_active.is_(True),
            )
        ).all()
        finance_position_ids = {position.id for position in finance_positions}
        stale_finance_assignments = db.scalars(
            select(AdminPanelAssignment).where(
                AdminPanelAssignment.panel_key == "finance",
                AdminPanelAssignment.position_id.not_in(finance_position_ids),
            )
        ).all()
        for assignment in stale_finance_assignments:
            db.delete(assignment)
            changed += 1
        for position in finance_positions:
            assignment = db.get(AdminPanelAssignment, position.id)
            if assignment is None:
                db.add(
                    AdminPanelAssignment(
                        position_id=position.id,
                        panel_key="finance",
                    )
                )
                changed += 1
            elif assignment.panel_key != "finance":
                assignment.panel_key = "finance"
                changed += 1
        personal_keys = {fio_key(fio) for fio in PERSONAL_FINANCE_ADMIN_FIOS}
        personal_members = db.scalars(
            select(OrgMember).where(
                OrgMember.fio_key.in_(personal_keys),
                OrgMember.user_id != "",
            )
        ).all()
        found_personal_keys = {member.fio_key for member in personal_members}
        missing.extend(sorted(personal_keys - found_personal_keys))
        for member in personal_members:
            assignment = db.get(AdminUserPanelAssignment, member.user_id)
            if assignment is None:
                db.add(
                    AdminUserPanelAssignment(
                        user_id=member.user_id,
                        panel_key="finance",
                    )
                )
                changed += 1
            elif assignment.panel_key != "finance":
                assignment.panel_key = "finance"
                changed += 1
        db.commit()
        return changed, missing


if __name__ == "__main__":
    changed_count, missing_fios = seed_default_panel()
    print(f"Назначений панелей создано/обновлено: {changed_count}")
    if missing_fios:
        print("Не найдены в org_members:", ", ".join(missing_fios))

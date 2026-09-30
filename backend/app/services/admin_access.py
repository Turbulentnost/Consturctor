from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.org import (
    AdminPanelAssignment,
    AdminUserPanelAssignment,
    OrgMember,
    OrgPosition,
)

DEFAULT_ADMIN_PAGES = (
    "overview",
    "history",
    "launch_calendar",
    "kpi",
    "users",
    "ai_agents",
    "knowledge_base",
    "settings",
)
FINANCE_ADMIN_PAGES = (
    "finance_employees",
    "finance_upload",
    "finance_import_history",
)
PANEL_PAGES: dict[str, tuple[str, ...]] = {
    "default": DEFAULT_ADMIN_PAGES,
    "finance": FINANCE_ADMIN_PAGES,
}


@dataclass(frozen=True, slots=True)
class AdminAccess:
    panel_key: str
    pages: tuple[str, ...]


def resolve_admin_access(db: Session, user_id: str) -> AdminAccess | None:
    if not user_id:
        return None
    user_assignment = db.get(AdminUserPanelAssignment, user_id)
    if user_assignment is not None:
        panel_key = user_assignment.panel_key
    else:
        panel_key = db.scalar(
            select(AdminPanelAssignment.panel_key)
            .join(OrgPosition, OrgPosition.id == AdminPanelAssignment.position_id)
            .join(OrgMember, OrgMember.position_id == OrgPosition.id)
            .where(
                OrgMember.user_id == user_id,
                OrgPosition.is_active.is_(True),
            )
            .limit(1)
        )
    key = str(panel_key or "").strip().lower()
    pages = PANEL_PAGES.get(key)
    return AdminAccess(panel_key=key, pages=pages) if pages else None


def get_admin_access(user_id: str) -> AdminAccess | None:
    with SessionLocal() as db:
        return resolve_admin_access(db, user_id)


def is_admin_user(user_id: str) -> bool:
    return get_admin_access(user_id) is not None


def admin_user_ids(db: Session) -> set[str]:
    known_panels = tuple(PANEL_PAGES)
    user_ids = {
        str(user_id)
        for user_id in db.scalars(
            select(OrgMember.user_id)
            .join(OrgPosition, OrgPosition.id == OrgMember.position_id)
            .join(AdminPanelAssignment, AdminPanelAssignment.position_id == OrgPosition.id)
            .where(
                OrgMember.user_id != "",
                OrgPosition.is_active.is_(True),
                AdminPanelAssignment.panel_key.in_(known_panels),
            )
            .distinct()
        )
        if user_id
    }
    user_ids.update(
        str(user_id)
        for user_id in db.scalars(
            select(AdminUserPanelAssignment.user_id).where(
                AdminUserPanelAssignment.panel_key.in_(known_panels),
            )
        )
        if user_id
    )
    return user_ids

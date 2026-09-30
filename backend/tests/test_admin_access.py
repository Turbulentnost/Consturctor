from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.org import (
    AdminPanelAssignment,
    AdminUserPanelAssignment,
    OrgMember,
    OrgPosition,
)
from app.services.admin_access import resolve_admin_access


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            OrgPosition.__table__,
            OrgMember.__table__,
            AdminPanelAssignment.__table__,
            AdminUserPanelAssignment.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _assign(db: Session, *, panel: str = "default", active: bool = True) -> None:
    db.add(OrgPosition(id="POS-1", name="Главный специалист", is_active=active))
    db.add(
        OrgMember(
            fio_key="тестов тест тестович",
            fio="Тестов Тест Тестович",
            user_id="user-1",
            position="Главный специалист",
            position_id="POS-1",
            unit_id="UNIT-1",
            department="Отдел",
        )
    )
    db.add(AdminPanelAssignment(position_id="POS-1", panel_key=panel))
    db.commit()


@pytest.mark.parametrize(
    ("panel", "pages"),
    [
        ("default", {"overview", "users", "ai_agents", "settings"}),
        (
            "finance",
            {"finance_employees", "finance_upload", "finance_import_history"},
        ),
    ],
)
def test_resolve_admin_access_by_current_position(
    db: Session, panel: str, pages: set[str]
) -> None:
    _assign(db, panel=panel)

    access = resolve_admin_access(db, "user-1")

    assert access is not None
    assert access.panel_key == panel
    assert set(access.pages) == pages if panel == "finance" else pages <= set(access.pages)


def test_no_assignment_means_no_admin_access(db: Session) -> None:
    assert resolve_admin_access(db, "user-1") is None


@pytest.mark.parametrize("panel", ["unknown", ""])
def test_unknown_panel_is_denied(db: Session, panel: str) -> None:
    _assign(db, panel=panel)
    assert resolve_admin_access(db, "user-1") is None


def test_inactive_position_is_denied(db: Session) -> None:
    _assign(db, active=False)
    assert resolve_admin_access(db, "user-1") is None


def test_personal_assignment_overrides_position_panel(db: Session) -> None:
    _assign(db, panel="default")
    db.add(AdminUserPanelAssignment(user_id="user-1", panel_key="finance"))
    db.commit()

    access = resolve_admin_access(db, "user-1")

    assert access is not None
    assert access.panel_key == "finance"
    assert set(access.pages) == {
        "finance_employees",
        "finance_upload",
        "finance_import_history",
    }

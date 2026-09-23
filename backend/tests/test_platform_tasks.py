"""Задачи платформы и оргструктура: ликвидированные, «не начальникам», статусы, просрочка."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.clients.erp_sql import ErpOrgDept, ErpStaffAssignment
from app.db.base import Base
from app.models.org import OrgMember, OrgUnit
from app.models.platform_task import PlatformTask, PlatformTaskFile
from app.models.user import AppUser
from app.services import org_structure, platform_tasks

CHAIRMAN = "Амураль Игорь Борисович"
ME = "Мангасарян Давид Каренович"
KOMARKOVA = "Комарькова Анастасия Эдуардовна"
PEER = "Уставицкий Андрей Андреевич"


def _dept(dept_id: str, name: str, parent: str = "", head: str = "") -> ErpOrgDept:
    return ErpOrgDept(id=dept_id, name=name, parent_id=parent, head_fio=head)


def _staff(fio: str, dept: str, position: str = "Специалист") -> ErpStaffAssignment:
    return ErpStaffAssignment(fio=fio, position=position, hr_department=dept, staff_folder=dept, staff_unit=position)


DEPARTMENTS = [
    _dept("ROOT", "Председатель Совета Директоров", head=CHAIRMAN),
    _dept("AUA", "Административно-управленческий аппарат", "ROOT", CHAIRMAN),
    _dept("AI", "Сектор по внедрению искусственного интеллекта", "AUA", ME),
    _dept("SALES", "Отдел продаж", "ROOT", PEER),
    _dept("OLD", "(ликв.) Отдел маркетинга", "ROOT", "Бывший Начальник Отдела"),
    _dept("GRAVE", "_Ликвидированные"),
    _dept("INSIDE", "Конструкторское бюро", "GRAVE", "Кто-то Внутри Ликвидированных"),
]
STAFF = [
    _staff(ME, "Сектор по внедрению искусственного интеллекта", "Руководитель сектора"),
    _staff(KOMARKOVA, "Сектор по внедрению искусственного интеллекта", "Промпт-инженер"),
    _staff(PEER, "Отдел продаж", "Начальник отдела"),
    _staff("Маркетолог Старый Отделович", "(ликв.) Отдел маркетинга"),
    _staff("Конструктор Внутри Папки", "Конструкторское бюро"),
    _staff("Упразднённый Сотрудник Иванович", "Отдел продаж", "(ликв.) Менеджер"),
]
LOGINS = {
    org_structure.fio_key(fio): f"id-{index}"
    for index, fio in enumerate([CHAIRMAN, ME, KOMARKOVA, PEER, "Маркетолог Старый Отделович"])
}


def test_liquidated_units_and_their_people_are_dropped() -> None:
    units, dead = org_structure.build_units(DEPARTMENTS)
    assert {unit.id for unit in units} == {"ROOT", "AUA", "AI", "SALES"}
    assert "(ликв.) Отдел маркетинга" in dead and "Конструкторское бюро" in dead
    members = {m.fio: m for m in org_structure.build_members(STAFF, units, dead, LOGINS)}
    assert "Маркетолог Старый Отделович" not in members
    assert "Конструктор Внутри Папки" not in members
    assert "Упразднённый Сотрудник Иванович" not in members
    assert members[KOMARKOVA].unit_id == "AI" and members[KOMARKOVA].user_id
    # Председатель не в штате, но руководит подразделениями — добавлен как сотрудник.
    assert members[CHAIRMAN].unit_id in {"ROOT", "AUA"}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True)
    tables = [t.__table__ for t in (AppUser, OrgUnit, OrgMember, PlatformTask, PlatformTaskFile)]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine, future=True)()
    units, dead = org_structure.build_units(DEPARTMENTS)
    for unit in units:
        session.add(OrgUnit(id=unit.id, name=unit.name, parent_id=unit.parent_id, head_fio=unit.head_fio))
    for m in org_structure.build_members(STAFF, units, dead, LOGINS):
        session.add(
            OrgMember(
                fio_key=org_structure.fio_key(m.fio),
                fio=m.fio,
                user_id=m.user_id,
                position=m.position,
                unit_id=m.unit_id,
                department=m.department,
            )
        )
    session.add(AppUser(id=LOGINS[org_structure.fio_key(ME)], fio=ME))
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def notes(monkeypatch) -> list[dict]:
    sent: list[dict] = []
    monkeypatch.setattr(platform_tasks, "_notify", lambda _db, **kwargs: sent.append(kwargs))
    return sent


def _me() -> str:
    return LOGINS[org_structure.fio_key(ME)]


def test_bosses_are_whole_chain_up(db) -> None:
    assert org_structure.boss_keys(db, ME) == {org_structure.fio_key(CHAIRMAN)}
    assert org_structure.boss_keys(db, KOMARKOVA) == {org_structure.fio_key(ME), org_structure.fio_key(CHAIRMAN)}


def test_assignable_excludes_self_and_bosses(db) -> None:
    names = [row.fio for row in org_structure.assignable_members(db, ME)]
    assert KOMARKOVA in names and PEER in names
    assert ME not in names and CHAIRMAN not in names


def test_create_task_notifies_assignee_and_rejects_boss(db, notes) -> None:
    due = datetime.now(timezone.utc) + timedelta(days=2)
    task = platform_tasks.create_task(
        db, author_id=_me(), author_fio=ME, assignee_fio=KOMARKOVA, description="Собрать отчёт", priority="high", due_at=due
    )
    assert task["assignee_fio"] == KOMARKOVA and task["status"] == "open" and task["role"] == "author"
    assert notes and notes[0]["recipient_id"] == LOGINS[org_structure.fio_key(KOMARKOVA)]
    # Исполнитель ещё не входил в Оркестратор — заведён по учётке 1С, чтобы дошло уведомление.
    assert db.get(AppUser, LOGINS[org_structure.fio_key(KOMARKOVA)]) is not None
    with pytest.raises(platform_tasks.PlatformTaskError, match="руководитель"):
        platform_tasks.create_task(
            db, author_id=_me(), author_fio=ME, assignee_fio=CHAIRMAN, description="x", priority="normal", due_at=due
        )
    with pytest.raises(platform_tasks.PlatformTaskError, match="позже"):
        platform_tasks.create_task(
            db,
            author_id=_me(),
            author_fio=ME,
            assignee_fio=KOMARKOVA,
            description="x",
            priority="normal",
            due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )


def test_only_assignee_closes_and_reject_needs_reason(db, notes) -> None:
    due = datetime.now(timezone.utc) + timedelta(days=1)
    task = platform_tasks.create_task(
        db, author_id=_me(), author_fio=ME, assignee_fio=KOMARKOVA, description="Проверить", priority="low", due_at=due
    )
    assignee = LOGINS[org_structure.fio_key(KOMARKOVA)]
    with pytest.raises(platform_tasks.PlatformTaskError, match="только исполнитель"):
        platform_tasks.change_status(db, user_id=_me(), task_id=task["id"], action="done")
    with pytest.raises(platform_tasks.PlatformTaskError, match="причину"):
        platform_tasks.change_status(db, user_id=assignee, task_id=task["id"], action="reject")
    done = platform_tasks.change_status(db, user_id=assignee, task_id=task["id"], action="done")
    assert done["status"] == "done" and notes[-1]["recipient_id"] == _me()
    assert [item["id"] for item in platform_tasks.list_tasks(db, user_id=assignee)] == [task["id"]]


def test_overdue_notifies_both_once(db, notes) -> None:
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    task = platform_tasks.create_task(
        db, author_id=_me(), author_fio=ME, assignee_fio=PEER, description="Срочно", priority="high", due_at=due
    )
    row = db.get(PlatformTask, task["id"])
    row.due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    notes.clear()
    assert platform_tasks.notify_overdue(db) == 1
    assert {note["recipient_id"] for note in notes} == {_me(), LOGINS[org_structure.fio_key(PEER)]}
    assert platform_tasks.notify_overdue(db) == 0

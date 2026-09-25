"""Управленческая структура из 1С ERP в базе Оркестратора.

Кто кому начальник: руководители своего подразделения и всех вышестоящих.
Ликвидированные подразделения и должности не учитываются: в 1С они помечены
приставкой «(ликв.)» в наименовании или лежат в папке «_Ликвидированные».
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.clients.erp_sql import ErpOrgDept, ErpStaffAssignment
from app.models.org import OrgMember, OrgUnit

logger = logging.getLogger(__name__)

_LIQUIDATED = re.compile(r"^\s*[(_]\s*ликв", re.IGNORECASE)
_sync_lock = threading.Lock()


class OrgStructureError(RuntimeError):
    pass


def fio_key(fio: str) -> str:
    return " ".join((fio or "").lower().replace("ё", "е").split())


def is_liquidated(name: str) -> bool:
    return bool(_LIQUIDATED.match(name or ""))


@dataclass(frozen=True, slots=True)
class UnitRow:
    id: str
    name: str
    parent_id: str
    head_fio: str


@dataclass(frozen=True, slots=True)
class MemberRow:
    fio: str
    user_id: str
    position: str
    unit_id: str
    department: str


def build_units(departments: Iterable[ErpOrgDept]) -> tuple[list[UnitRow], set[str]]:
    """Действующие подразделения и названия ликвидированных (с учётом вложенности)."""
    by_id = {dept.id: dept for dept in departments}

    def liquidated(dept: ErpOrgDept) -> bool:
        current: ErpOrgDept | None = dept
        for _ in range(40):
            if current is None:
                return False
            if is_liquidated(current.name):
                return True
            current = by_id.get(current.parent_id)
        return False

    kept = [dept for dept in by_id.values() if not liquidated(dept)]
    kept_ids = {dept.id for dept in kept}
    dead_names = {dept.name for dept in by_id.values() if dept.id not in kept_ids}
    units = [
        UnitRow(
            id=dept.id,
            name=dept.name,
            parent_id=dept.parent_id if dept.parent_id in kept_ids else "",
            head_fio=dept.head_fio,
        )
        for dept in kept
    ]
    return units, dead_names


def build_members(
    staff: Iterable[ErpStaffAssignment],
    units: list[UnitRow],
    dead_names: set[str],
    login_ids: dict[str, str],
) -> list[MemberRow]:
    """Сотрудники с текущим назначением; подразделение ищем по имени отдела или папки ШР."""
    unit_by_name = {unit.name: unit for unit in units}
    members: dict[str, MemberRow] = {}
    for item in staff:
        key = fio_key(item.fio)
        if not key or key in members:
            continue
        if is_liquidated(item.position) or is_liquidated(item.staff_unit):
            continue
        if item.hr_department in dead_names or item.staff_folder in dead_names:
            continue
        unit = unit_by_name.get(item.hr_department) or unit_by_name.get(item.staff_folder)
        members[key] = MemberRow(
            fio=item.fio,
            user_id=login_ids.get(key, ""),
            position=item.position,
            unit_id=unit.id if unit else "",
            department=unit.name if unit else (item.hr_department or item.staff_folder),
        )
    for unit in units:
        key = fio_key(unit.head_fio)
        if key and key not in members:
            members[key] = MemberRow(
                fio=unit.head_fio,
                user_id=login_ids.get(key, ""),
                position="Руководитель",
                unit_id=unit.id,
                department=unit.name,
            )
    return list(members.values())


def sync_org_structure(db: Session) -> dict[str, int | str]:
    """Перечитать структуру из ERP и заменить таблицы целиком. Идёт около полутора минут."""
    from app.clients import erp_sql

    if not _sync_lock.acquire(blocking=False):
        raise OrgStructureError("Синхронизация оргструктуры уже идёт")
    try:
        started = time.perf_counter()
        departments, staff = erp_sql.load_org_structure()
        logins = {fio_key(row.fio): row.id for row in erp_sql.search_user_directory(limit=20000)}
        units, dead_names = build_units(departments)
        members = build_members(staff, units, dead_names, logins)
        now = datetime.now(timezone.utc)
        db.execute(delete(OrgMember))
        db.execute(delete(OrgUnit))
        db.add_all(
            OrgUnit(id=u.id, name=u.name, parent_id=u.parent_id, head_fio=u.head_fio, synced_at=now) for u in units
        )
        db.add_all(
            OrgMember(
                fio_key=fio_key(m.fio),
                fio=m.fio,
                user_id=m.user_id,
                position=m.position,
                unit_id=m.unit_id,
                department=m.department,
                synced_at=now,
            )
            for m in members
        )
        db.commit()
        stats = {
            "units": len(units),
            "liquidated_units": len(departments) - len(units),
            "members": len(members),
            "members_with_login": sum(1 for m in members if m.user_id),
            "seconds": round(time.perf_counter() - started, 1),
        }
        logger.info("org structure synced: %s", stats)
        return stats
    finally:
        _sync_lock.release()


def org_status(db: Session) -> dict[str, int | str]:
    units = db.scalar(select(func.count()).select_from(OrgUnit)) or 0
    members = db.scalar(select(func.count()).select_from(OrgMember)) or 0
    synced = db.scalar(select(func.max(OrgMember.synced_at)))
    return {"units": units, "members": members, "synced_at": synced.isoformat() if synced else ""}


def member_by_fio(db: Session, fio: str) -> OrgMember | None:
    return db.get(OrgMember, fio_key(fio))


def boss_keys(db: Session, fio: str) -> set[str]:
    """ФИО (ключи) руководителей сотрудника: своего подразделения и всех вышестоящих."""
    own = fio_key(fio)
    member = member_by_fio(db, fio)
    if member is None:
        return set()
    units = {unit.id: unit for unit in db.execute(select(OrgUnit)).scalars()}
    bosses: set[str] = set()
    current = units.get(member.unit_id)
    for _ in range(40):
        if current is None:
            break
        head = fio_key(current.head_fio)
        if head and head != own:
            bosses.add(head)
        current = units.get(current.parent_id)
    return bosses


def assignable_members(db: Session, author_fio: str, *, search: str = "", limit: int = 5000) -> list[OrgMember]:
    """Кому можно поставить задачу: сотрудники с учётной записью, кроме себя и своих начальников."""
    if not org_status(db)["members"]:
        raise OrgStructureError("Оргструктура 1С ещё не загружена. Повторите через пару минут.")
    blocked = boss_keys(db, author_fio) | {fio_key(author_fio)}
    stmt = select(OrgMember).where(OrgMember.user_id != "").order_by(OrgMember.fio)
    needle = search.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(OrgMember.fio.ilike(like), OrgMember.position.ilike(like), OrgMember.department.ilike(like))
        )
    rows = [row for row in db.execute(stmt).scalars() if row.fio_key not in blocked]
    return rows[:limit]

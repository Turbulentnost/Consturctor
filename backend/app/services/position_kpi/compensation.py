from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.erp_sql import ErpSqlError
from app.core.jwt import AuthContext
from app.models.finance import FinanceSalaryEntry
from app.models.org import OrgPerson, OrgPosition
from app.models.position_kpi import PositionCompRule
from app.services.admin.finance import current_salary
from app.services.admin.salary_source import MODE_ONEC, effective_salary_mode
from app.services.org_structure import fio_key
from app.services.position_kpi.daily import get_or_compute_position_kpi, resolve_profile
from app.services.position_kpi.erp_salary import PlannedSalary, lookup_salary_history
from app.services.position_kpi.pin import KpiPinError, verify_pin


class CompensationError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _assignment(db: Session, auth: AuthContext) -> tuple[str, str]:
    """(position_id, department) of the signed-in employee."""
    person = db.scalar(
        select(OrgPerson)
        .where(OrgPerson.user_id == auth.user_id, OrgPerson.is_active.is_(True))
        .limit(1)
    )
    if person is None and auth.fio:
        person = db.scalar(
            select(OrgPerson)
            .where(OrgPerson.fio_key == fio_key(auth.fio), OrgPerson.is_active.is_(True))
            .limit(1)
        )
    department = (
        (person.department if person is not None else "") or getattr(auth, "department", "") or ""
    ).strip()
    if person is not None and person.position_id:
        return person.position_id, department

    position_name = (auth.position or "").strip()
    if not position_name:
        return "", department
    position = db.scalar(
        select(OrgPosition)
        .where(OrgPosition.name.ilike(position_name), OrgPosition.is_active.is_(True))
        .limit(1)
    )
    return (position.id if position is not None else ""), department


def _salary(
    db: Session, auth: AuthContext, as_of: date
) -> tuple[FinanceSalaryEntry | None, str]:
    position_id, department = _assignment(db, auth)
    return current_salary(db, position_id, department, as_of), department


def _money(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _masked(available: bool, *, currency: str = "RUB", effective_from: str = "") -> dict[str, Any]:
    return {
        "available": available,
        "unlocked": False,
        "currency": currency,
        "effective_from": effective_from,
        "salary": None,
        "bonus": None,
        "total": None,
    }


def _history_payload(points: list[PlannedSalary]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for point in points:
        salary_text = _money(point.amount)
        rows.append(
            {
                "effective_from": point.effective_from.isoformat(),
                "salary": salary_text,
                "bonus": salary_text,
                "total": _money(point.amount + point.amount),
            }
        )
    return rows


def masked_compensation(db: Session, auth: AuthContext, *, as_of: date | None = None) -> dict[str, Any]:
    target_day = as_of or date.today()
    if effective_salary_mode(db) == MODE_ONEC:
        fio = (auth.fio or "").strip()
        if not fio:
            return _masked(False)
        try:
            history = lookup_salary_history(fio, target_day)
        except ErpSqlError:
            return _masked(False)
        if not history:
            return _masked(False)
        return _masked(True, effective_from=history[-1].effective_from.isoformat())

    salary, _department = _salary(db, auth, target_day)
    return _masked(
        salary is not None,
        currency=salary.currency if salary is not None else "RUB",
        effective_from=salary.effective_from.isoformat() if salary is not None else "",
    )


def unlock_compensation(
    db: Session,
    auth: AuthContext,
    *,
    pin: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    try:
        verify_pin(db, auth.user_id, pin)
    except KpiPinError as exc:
        raise CompensationError(exc.message, exc.status_code) from exc

    target_day = date_to or date.today()
    if effective_salary_mode(db) == MODE_ONEC:
        fio = (auth.fio or "").strip()
        history: list[PlannedSalary] = []
        if fio:
            try:
                history = lookup_salary_history(fio, target_day)
            except ErpSqlError as exc:
                raise CompensationError("Не удалось получить оклад из 1С", 502) from exc
        if not history:
            raise CompensationError("Для вашей должности оклад не найден", 404)
        current = history[-1]
        salary_text = _money(current.amount)
        return {
            "available": True,
            "unlocked": True,
            "currency": "RUB",
            "effective_from": current.effective_from.isoformat(),
            "salary": salary_text,
            "bonus": salary_text,
            "total": _money(current.amount + current.amount),
            "history": _history_payload(history),
        }

    salary, department = _salary(db, auth, target_day)
    if salary is None:
        raise CompensationError("Для вашей должности оклад не найден", 404)

    bonus: Decimal | None = None
    position_name = (auth.position or salary.position_snapshot or "").strip()
    profile = resolve_profile(db, position_name, as_of=target_day, department=department)
    if profile is not None:
        rule = db.scalar(select(PositionCompRule).where(PositionCompRule.profile_id == profile.id))
        if rule is not None and rule.bonus_kind == "salary_times_crp_times_sum":
            snapshot = get_or_compute_position_kpi(
                db,
                position_name,
                as_of=target_day,
                date_from=date_from,
                date_to=date_to,
                allow_stale=True,
                subject=(auth.fio or "").strip(),
                department=department,
            )
            contributions = [tile.get("contrib") for tile in snapshot.get("tiles", [])]
            if contributions and all(value is not None for value in contributions):
                contribution_pct = sum(Decimal(str(value)) for value in contributions)
                bonus = (
                    salary.amount
                    * Decimal(rule.bonus_base_pct)
                    / Decimal(100)
                    * contribution_pct
                    / Decimal(100)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total = salary.amount + bonus if bonus is not None else None
    return {
        "available": True,
        "unlocked": True,
        "currency": salary.currency,
        "effective_from": salary.effective_from.isoformat(),
        "salary": str(salary.amount),
        "bonus": str(bonus) if bonus is not None else None,
        "total": str(total) if total is not None else None,
    }

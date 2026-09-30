from __future__ import annotations

import hmac
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.jwt import AuthContext
from app.models.finance import FinanceSalaryEntry
from app.models.org import OrgPerson, OrgPosition
from app.models.position_kpi import PositionCompRule
from app.services.org_structure import fio_key
from app.services.position_kpi.daily import get_or_compute_position_kpi, resolve_profile


class CompensationError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _position_id(db: Session, auth: AuthContext) -> str:
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
    if person is not None and person.position_id:
        return person.position_id

    position_name = (auth.position or "").strip()
    if not position_name:
        return ""
    position = db.scalar(
        select(OrgPosition)
        .where(OrgPosition.name.ilike(position_name), OrgPosition.is_active.is_(True))
        .limit(1)
    )
    return position.id if position is not None else ""


def _salary(db: Session, auth: AuthContext, as_of: date) -> FinanceSalaryEntry | None:
    position_id = _position_id(db, auth)
    if not position_id:
        return None
    return db.scalar(
        select(FinanceSalaryEntry)
        .where(
            FinanceSalaryEntry.position_id == position_id,
            FinanceSalaryEntry.is_current.is_(True),
            FinanceSalaryEntry.effective_from <= as_of,
        )
        .order_by(FinanceSalaryEntry.effective_from.desc())
        .limit(1)
    )


def masked_compensation(db: Session, auth: AuthContext, *, as_of: date | None = None) -> dict[str, Any]:
    target_day = as_of or date.today()
    salary = _salary(db, auth, target_day)
    return {
        "available": salary is not None,
        "unlocked": False,
        "currency": salary.currency if salary is not None else "RUB",
        "effective_from": salary.effective_from.isoformat() if salary is not None else "",
        "salary": None,
        "bonus": None,
        "total": None,
    }


def unlock_compensation(
    db: Session,
    auth: AuthContext,
    *,
    pin: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    if not hmac.compare_digest(str(pin), settings.salary_pin):
        raise CompensationError("Неверный PIN-код", 403)

    target_day = date_to or date.today()
    salary = _salary(db, auth, target_day)
    if salary is None:
        raise CompensationError("Для вашей должности оклад не найден", 404)

    bonus: Decimal | None = None
    position_name = (auth.position or salary.position_snapshot or "").strip()
    profile = resolve_profile(db, position_name, as_of=target_day)
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

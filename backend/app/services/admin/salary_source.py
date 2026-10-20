from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.finance import FinanceImport, FinanceSalarySource

SOURCE_ID = "global"
MODE_FILE = "file"
MODE_ONEC = "onec"
_MODES = {MODE_FILE, MODE_ONEC}


class SalarySourceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def has_confirmed_salary_file(db: Session) -> bool:
    row_id = db.scalar(
        select(FinanceImport.id)
        .where(
            FinanceImport.kind == "salary",
            FinanceImport.status == "confirmed",
        )
        .limit(1)
    )
    return row_id is not None


def _stored_mode(db: Session) -> str:
    row = db.get(FinanceSalarySource, SOURCE_ID)
    mode = (row.mode if row is not None else MODE_FILE).strip()
    return mode if mode in _MODES else MODE_FILE


def salary_source_state(db: Session) -> dict[str, Any]:
    can_use_file = has_confirmed_salary_file(db)
    stored = _stored_mode(db)
    return {
        "mode": stored if can_use_file else MODE_ONEC,
        "can_use_file": can_use_file,
    }


def effective_salary_mode(db: Session) -> str:
    return str(salary_source_state(db)["mode"])


def set_salary_source(db: Session, mode: str) -> dict[str, Any]:
    chosen = (mode or "").strip()
    if chosen not in _MODES:
        raise SalarySourceError("Неизвестный источник зарплаты")
    if chosen == MODE_FILE and not has_confirmed_salary_file(db):
        raise SalarySourceError("Файл зарплат ещё не загружен", 409)
    row = db.get(FinanceSalarySource, SOURCE_ID)
    if row is None:
        db.add(FinanceSalarySource(id=SOURCE_ID, mode=chosen))
    else:
        row.mode = chosen
    db.commit()
    return salary_source_state(db)

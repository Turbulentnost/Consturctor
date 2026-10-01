"""История оклада сотрудника из erp_pm.

Регистр dbo._InfoRg47232 хранит тарифную ставку: _Fld47233RRef — сотрудник,
_Fld47240 — оклад. Повторы той же суммы и несколько строк за один день
схлопываются, остаётся последнее значение дня.

Плановые начисления (dbo._InfoRg47114) для этой истории не подходят:
там размер вида расчёта и временные доплаты, из-за этого у сотрудника
получалась другая цепочка сумм.
Премия в режиме 1С равна окладу и считается уже в compensation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

import pyodbc

from app.clients.erp_sql import ErpSqlError, _connect, _release_connection
from app.services.erp_tasks import from_1c_datetime, to_1c_datetime

_RATE_SQL = """
SELECT
    t._Period AS Period,
    CAST(t._Fld47240 AS decimal(18, 2)) AS Amount
FROM dbo._Reference486 emp WITH (NOLOCK)
INNER JOIN dbo._InfoRg47232 t WITH (NOLOCK)
    ON t._Fld47233RRef = emp._IDRRef
   AND t._Period <= ?
WHERE LTRIM(RTRIM(emp._Description)) = ?
  AND emp._Marked = 0x00
ORDER BY t._Period
"""


@dataclass(frozen=True)
class PlannedSalary:
    amount: Decimal
    effective_from: date


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def revisions_from_rates(points: list[tuple[date, Decimal]]) -> list[PlannedSalary]:
    """Только даты, в которые оклад изменился. За один день остаётся последняя сумма."""
    revisions: list[PlannedSalary] = []
    for period, raw in points:
        amount = _money(raw)
        if amount <= 0:
            continue
        if revisions and revisions[-1].effective_from == period:
            revisions[-1] = PlannedSalary(amount=amount, effective_from=period)
            if len(revisions) >= 2 and revisions[-1].amount == revisions[-2].amount:
                revisions.pop()
            continue
        if revisions and revisions[-1].amount == amount:
            continue
        revisions.append(PlannedSalary(amount=amount, effective_from=period))
    return revisions


def lookup_salary_history(fio: str, as_of: date) -> list[PlannedSalary]:
    name = " ".join((fio or "").split())
    if not name:
        return []
    as_of_1c = to_1c_datetime(datetime.combine(as_of, time(23, 59, 59)))
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(_RATE_SQL, (as_of_1c, name))
        fetched = cur.fetchall()
    except pyodbc.Error as exc:
        raise ErpSqlError("Не удалось прочитать оклад") from exc
    finally:
        _release_connection(conn)

    points: list[tuple[date, Decimal]] = []
    for period_raw, amount_raw in fetched:
        period = from_1c_datetime(period_raw if isinstance(period_raw, datetime) else None)
        if period is None or amount_raw is None:
            continue
        points.append((period.date(), Decimal(str(amount_raw))))
    return revisions_from_rates(points)

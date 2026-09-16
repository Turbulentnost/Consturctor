from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.kpi_daily_metric import WorkplaceKpiDailyMetric
from app.schemas.workplace_kpi import WorkplaceKpiChartSeriesOut, WorkplaceKpiDynamicsOut


def _iter_days(day_from: date, day_to: date) -> list[date]:
    lo, hi = (day_from, day_to) if day_from <= day_to else (day_to, day_from)
    out: list[date] = []
    cursor = lo
    while cursor <= hi:
        out.append(cursor)
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return out


def upsert_daily_metrics(
    db: Session,
    *,
    user_id: str,
    rows: list[tuple[date, int, int]],
) -> None:
    for day, tasks_pct, sla_pct in rows:
        existing = db.execute(
            select(WorkplaceKpiDailyMetric).where(
                WorkplaceKpiDailyMetric.user_id == user_id,
                WorkplaceKpiDailyMetric.day == day,
            )
        ).scalars().first()
        tasks = max(0, min(100, int(tasks_pct)))
        sla = max(0, min(100, int(sla_pct)))
        if existing:
            existing.tasks_pct = tasks
            existing.sla_pct = sla
        else:
            db.add(
                WorkplaceKpiDailyMetric(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    day=day,
                    tasks_pct=tasks,
                    sla_pct=sla,
                )
            )
    db.commit()


def dynamics_from_daily_metrics(
    db: Session,
    *,
    user_id: str,
    day_from: date,
    day_to: date,
    fallback: WorkplaceKpiDynamicsOut,
) -> WorkplaceKpiDynamicsOut:
    days = _iter_days(day_from, day_to)
    if not days:
        return fallback

    stored = {
        row.day: row
        for row in db.execute(
            select(WorkplaceKpiDailyMetric).where(
                WorkplaceKpiDailyMetric.user_id == user_id,
                WorkplaceKpiDailyMetric.day >= days[0],
                WorkplaceKpiDailyMetric.day <= days[-1],
            )
        )
        .scalars()
        .all()
    }

    x_labels = [f"{d.day:02d}.{d.month:02d}" for d in days]
    tasks_points = [stored[d].tasks_pct if d in stored else 0 for d in days]
    sla_points = [stored[d].sla_pct if d in stored else 0 for d in days]

    if not stored:
        return fallback

    return WorkplaceKpiDynamicsOut(
        title=fallback.title or "Динамика показателей",
        x_labels=x_labels,
        y_max=100,
        series=[
            WorkplaceKpiChartSeriesOut(
                id="tasks",
                label="Выполнение задач",
                color="#e8943a",
                points=tasks_points,
            ),
            WorkplaceKpiChartSeriesOut(
                id="sla",
                label="Соблюдение сроков",
                color="#08745f",
                points=sla_points,
            ),
        ],
        source="computed",
    )

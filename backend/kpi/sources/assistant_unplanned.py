"""Внеплановые совещания помощника руководителя.

План — служебные записки Document_ТД_СлужебнаяЗаписка за месяц:
тема «организация совещаний», статус «Согласована», без отметки ПСД
(НаУровнеПСД = нет).
Нарушение — такой записки нет в общем календаре Outlook «Совещания».
Шкала ПЛ-НПО-010: меньше 5 нарушений → 100%, от 5 до 8 → 50%, больше 8 → 0%.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from kpi.sources.assistant_meetings import (
    ENTITY,
    FOLDER,
    THEME_NEEDLE,
    format_report as format_meetings_report,
    load_meetings_schedule_rows,
    score_meetings_schedule_kpi,
)

WEIGHT = 30

SOURCE = {
    "kind": "onec",
    "loader": "odata",
    "entity": ENTITY,
    "theme": THEME_NEEDLE,
    "status": "Согласована",
    "exclude_psd": True,
    "folder": FOLDER,
}


def score_unplanned_meetings_kpi(
    rows: list[dict[str, Any]] | None,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    return score_meetings_schedule_kpi(
        rows,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        weight=WEIGHT,
        exclude_psd=True,
    )


def compute_unplanned_meetings_kpi(
    ctx: Any,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start = date_from or getattr(ctx, "date_from", None)
    end = date_to or getattr(ctx, "date_to", None)
    rows = load_meetings_schedule_rows(ctx, date_from=start, date_to=end)
    return score_unplanned_meetings_kpi(rows, as_of=as_of, date_from=start, date_to=end)


def format_report(report: dict[str, Any]) -> str:
    text = format_meetings_report(report)
    if not report.get("plan_total"):
        return "Согласованных записок на организацию совещаний без отметки ПСД за период нет."
    return text

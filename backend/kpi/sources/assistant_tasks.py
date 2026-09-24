"""Индивидуальные задачи помощника руководителя.

План — задачи 1С за месяц, которые Донцова поставила Акининой.
Факт — сколько из них выполнено.
Источник — кэш задач документооборота. Если в нём только открытые,
добираем выполненные тем же запросом и кладём ответ в этот кэш.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.tools.onec.dok_soap import (
    fetch_performer_period_rows,
    normalize_person,
    parse_soap_datetime,
    person_matches,
    read_cached_dump_rows,
    soap_configured,
)

logger = logging.getLogger(__name__)

PERFORMER = "Акинина Татьяна Владимировна"
AUTHOR = "Донцова Анна Егоровна"
WEIGHT = 10

SOURCE = {
    "kind": "onec",
    "loader": "docflow",
    "performer": PERFORMER,
    "author": AUTHOR,
}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _bounds(ctx: Any, date_from: date | None, date_to: date | None) -> tuple[date | None, date | None]:
    start = date_from or getattr(ctx, "date_from", None)
    end = date_to or getattr(ctx, "date_to", None)
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    if start and end and end < start:
        start, end = end, start
    return start, end


def _same_person(value: Any, needle: str) -> bool:
    text = str(value or "").strip()
    if not text or not needle:
        return False
    if person_matches(text, needle):
        return True
    left = normalize_person(text).split()
    right = normalize_person(needle).split()
    return len(right) == 1 and bool(left) and left[0] == right[0]


def _assigned_day(row: dict[str, Any]) -> date | None:
    for key in ("begin", "created_at", "Date"):
        raw = str(row.get(key) or "").strip().replace(" ", "T")
        parsed = parse_soap_datetime(raw)
        if parsed is not None:
            return parsed.date()
    return None


def _in_period(day: date | None, date_from: date | None, date_to: date | None) -> bool:
    if day is None:
        return False
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def _done(row: dict[str, Any]) -> bool:
    if row.get("executed") is True or row.get("done") is True:
        return True
    status = normalize_person(str(row.get("status") or row.get("state") or ""))
    return status in {"выполнена", "исполнена"}


def _title(row: dict[str, Any]) -> str:
    for key in ("description", "title", "name", "target"):
        text = " ".join(str(row.get(key) or "").split())
        if text:
            return text
    return ""


def _number(row: dict[str, Any]) -> str:
    return str(row.get("number") or row.get("id") or "").strip()


def select_plan(
    rows: list[dict[str, Any]],
    *,
    date_from: date | None,
    date_to: date | None,
    performer: str = PERFORMER,
    author: str = AUTHOR,
) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    for row in rows:
        if not _same_person(row.get("performer"), performer):
            continue
        if not _same_person(row.get("author"), author):
            continue
        day = _assigned_day(row)
        if not _in_period(day, date_from, date_to):
            continue
        picked.append(row)
    picked.sort(key=lambda item: (_assigned_day(item) or date.min, _number(item)))
    return picked


def _includes_completed(rows: list[dict[str, Any]]) -> bool:
    flagged = [row for row in rows if "_includes_completed" in row]
    if not flagged:
        return True
    return any(bool(row.get("_includes_completed")) for row in flagged)


def score_individual_tasks_kpi(
    rows: list[dict[str, Any]] | None,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
    performer: str = PERFORMER,
    author: str = AUTHOR,
) -> dict[str, Any]:
    source = _as_rows(rows)
    picked = select_plan(
        source,
        date_from=date_from,
        date_to=date_to,
        performer=performer,
        author=author,
    )
    total = len(picked)
    done = sum(1 for row in picked if _done(row))
    includes_completed = _includes_completed(source)
    if total:
        fact = round(100.0 * done / total, 1)
        contrib = round(fact * WEIGHT / 100.0, 1)
    else:
        fact = None
        contrib = None
    detailed: list[dict[str, Any]] = []
    for row in picked:
        day = _assigned_day(row)
        detailed.append(
            {
                "number": _number(row),
                "title": _title(row),
                "author": str(row.get("author") or "").strip(),
                "performer": str(row.get("performer") or "").strip(),
                "assigned": day.isoformat() if day else "",
                "done": _done(row),
            }
        )
    return {
        "as_of": as_of.isoformat() if isinstance(as_of, date) else str(as_of or ""),
        "date_from": date_from.isoformat() if isinstance(date_from, date) else "",
        "date_to": date_to.isoformat() if isinstance(date_to, date) else "",
        "performer": performer,
        "author": author,
        "plan_total": total,
        "done_total": done if total else None,
        "includes_completed": includes_completed,
        "fact_pct": fact,
        "score_pct": fact,
        "weight": WEIGHT,
        "contrib_pct": contrib,
        "rows": detailed,
    }


def _tag(rows: list[dict[str, Any]], includes_completed: bool) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["_includes_completed"] = includes_completed
        tagged.append(item)
    return tagged


def fetch_rows(
    date_from: date | None,
    date_to: date | None,
    *,
    performer: str = "",
) -> list[dict[str, Any]]:
    """Сначала период с выполненными, при ошибке — уже лежащий кэш."""
    name = str(performer or PERFORMER).strip() or PERFORMER
    if isinstance(date_from, date) and isinstance(date_to, date) and soap_configured():
        try:
            return _tag(fetch_performer_period_rows(name, date_from, date_to), True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("assistant tasks period cache missed, using dump: %s", exc)
    rows, includes_completed = read_cached_dump_rows()
    return _tag(rows, includes_completed)


def load_individual_task_rows(
    ctx: Any,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    start, end = _bounds(ctx, date_from, date_to)
    load = getattr(ctx, "load_for", None)
    if callable(load):
        extra = dict(SOURCE)
        more = ctx.extra_for() if hasattr(ctx, "extra_for") else {}
        if isinstance(more, dict):
            extra.update(more)
        return _as_rows(load(extra))
    return fetch_rows(start, end)


def compute_individual_tasks_kpi(
    ctx: Any,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start, end = _bounds(ctx, date_from, date_to)
    rows = load_individual_task_rows(ctx, date_from=start, date_to=end)
    performer = PERFORMER
    author = AUTHOR
    if hasattr(ctx, "extra_for"):
        extra = ctx.extra_for() or {}
        if isinstance(extra, dict):
            performer = str(extra.get("performer") or performer)
            author = str(extra.get("author") or author)
    return score_individual_tasks_kpi(
        rows,
        as_of=as_of,
        date_from=start,
        date_to=end,
        performer=performer,
        author=author,
    )


def format_report(report: dict[str, Any]) -> str:
    total = report.get("plan_total") or 0
    if not total:
        return "Задач от Донцовой Акининой за период нет."
    lines = [f"{'дата':<12} {'выполнена':<10} задача"]
    for row in report.get("rows") or []:
        lines.append(
            f"{str(row.get('assigned') or ''):<12} "
            f"{'да' if row.get('done') else 'нет':<10} "
            f"{row.get('title') or row.get('number') or ''}"
        )
    note = ""
    if report.get("includes_completed") is False:
        note = " Кэш хранит только открытые задачи, выполненные в выборку не входят."
    lines.append(
        f"Выполнено {report.get('done_total')}/{total}, факт {report.get('fact_pct')}%.{note}"
    )
    return "\n".join(lines)

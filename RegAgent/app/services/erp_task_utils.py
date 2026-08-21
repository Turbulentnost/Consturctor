"""Утилиты дат и просрочки задач 1С (общие для OData документооборота)."""

from __future__ import annotations

from datetime import datetime, timedelta

_YEAR_OFFSET = 2000


class ErpTaskError(RuntimeError):
    pass


def from_1c_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.year >= 3000:
        try:
            return value.replace(year=value.year - _YEAR_OFFSET)
        except ValueError:
            return value - timedelta(days=365 * _YEAR_OFFSET)
    if value.year <= 2001:
        return None
    return value


def task_is_late(
    *,
    done: bool,
    completed_at: datetime | None,
    due_at: datetime | None,
) -> bool:
    if not done or completed_at is None or due_at is None:
        return False
    return completed_at > due_at


def parse_date(raw: str, *, end: bool = False) -> datetime:
    text = (raw or "").strip()
    if not text:
        raise ErpTaskError("Нужна дата в формате YYYY-MM-DD")
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ErpTaskError(f"Непонятная дата: {text}")
    if end and parsed.hour == 0 and parsed.minute == 0 and len(text) <= 10:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed

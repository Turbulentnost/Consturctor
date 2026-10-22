"""Каждый run() модуля KPI сам пишет полный результат в кэш дня и в личный снимок."""

from __future__ import annotations

import json
import os
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

MOSCOW = ZoneInfo("Europe/Moscow")


def remember_module_run(
    module_file: str,
    fio: str,
    month: str | None,
    result: dict[str, Any],
    *,
    db: Session | None = None,
    root: Path | None = None,
    today: date | None = None,
) -> Path:
    """Файл кэша и плитки сотрудника. Без файла запуск модуля не считается законченным."""
    person = str(fio or "").strip()
    if not person:
        raise ValueError("Для кэша KPI нужно ФИО")
    if not isinstance(result, dict):
        raise TypeError("Результат модуля должен быть словарём")
    stem = Path(module_file).stem
    day = today or datetime.now(MOSCOW).date()
    period_from, period_to = _period(month, day)
    cache_root = root or _default_root()
    position = _position_for(db, stem)
    payload = {
        "status": "ok",
        "module": stem,
        "fio": person,
        "month": f"{period_from.year:04d}-{period_from.month:02d}",
        "position": position,
        "output": _output_text(result),
        "result": _jsonable(result),
    }
    folder = cache_root / day.isoformat() / stem
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{person}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)
    _publish(
        db,
        stem=stem,
        fio=person,
        as_of=day,
        date_from=period_from,
        date_to=period_to,
        root=cache_root,
    )
    return target


def _default_root() -> Path:
    from app.services.position_kpi.daily import runner_cache_root

    return runner_cache_root()


def _period(month: str | None, today: date) -> tuple[date, date]:
    text = str(month or "").strip()
    year, month_no = today.year, today.month
    if len(text) >= 7 and text[4] == "-":
        try:
            year, month_no = int(text[:4]), int(text[5:7])
        except ValueError:
            year, month_no = today.year, today.month
    if not 1 <= month_no <= 12:
        year, month_no = today.year, today.month
    last = monthrange(year, month_no)[1]
    return date(year, month_no, 1), date(year, month_no, last)


def _output_text(result: dict[str, Any]) -> str:
    lines = [
        f"Показатель: {result.get('name') or ''}",
        f"Вес: {result.get('weight') or 0}%",
    ]
    if result.get("no_base"):
        lines.extend(
            [
                "План: нет базы",
                "Факт: нет базы",
                "Выполнение: нет базы",
                "Вклад: нет базы",
            ]
        )
    else:
        lines.extend(
            [
                f"План: {result.get('plan')}",
                f"Факт: {result.get('fact')}",
                f"Выполнение: {result.get('score')}%",
                f"Вклад: {result.get('contribution')}%",
            ]
        )
    return "\n".join(lines) + "\n"


def _session(db: Session | None) -> tuple[Session, bool]:
    if db is not None:
        return db, False
    from app.db.session import SessionLocal

    return SessionLocal(), True


def _position_for(db: Session | None, stem: str) -> str:
    session, own = _session(db)
    try:
        profile = _profile_for(session, stem)
        return profile.position_name if profile is not None else ""
    finally:
        if own:
            session.close()


def _profile_for(session: Session, stem: str):
    from app.models.position_kpi import PositionKpiModule, PositionKpiProfile

    module = session.scalar(
        select(PositionKpiModule).where(PositionKpiModule.module_name == f"kpi.generated.{stem}")
    )
    if module is None:
        return None
    return session.get(PositionKpiProfile, module.profile_id)


def _publish(
    db: Session | None,
    *,
    stem: str,
    fio: str,
    as_of: date,
    date_from: date,
    date_to: date,
    root: Path,
) -> None:
    from app.services.position_kpi.daily import publish_subject_tiles, tiles_from_runner_cache

    session, own_session = _session(db)
    try:
        profile = _profile_for(session, stem)
        if profile is None:
            return
        tiles = tiles_from_runner_cache(session, profile, fio=fio, as_of=as_of, root=root)
        if not tiles:
            return
        publish_subject_tiles(
            session,
            profile,
            fio=fio,
            as_of=as_of,
            date_from=date_from,
            date_to=date_to,
            tiles=tiles,
        )
    finally:
        if own_session:
            session.close()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

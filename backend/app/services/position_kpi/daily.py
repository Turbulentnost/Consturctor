from __future__ import annotations

import calendar
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.position_kpi import (
    PositionKpiDailyFact,
    PositionKpiMetric,
    PositionKpiProfile,
    PositionKpiSource,
)
from app.services.position_kpi.registry import scorer_for

logger = logging.getLogger(__name__)

_UNSET = object()


class PositionKpiNotFound(Exception):
    """Должность нет в каталоге KPI."""


def normalize_position_name(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def resolve_profile(db: Session, position: str) -> PositionKpiProfile | None:
    name = str(position or "").strip()
    if not name:
        return None
    exact = db.execute(
        select(PositionKpiProfile).where(PositionKpiProfile.position_name == name)
    ).scalar_one_or_none()
    if exact is not None:
        return exact
    wanted = normalize_position_name(name)
    if not wanted:
        return None
    for row in db.execute(select(PositionKpiProfile)).scalars():
        if normalize_position_name(row.position_name) == wanted:
            return row
    return None


def load_outlook_events(date_from: date, date_to: date) -> list[dict[str, Any]]:
    from kpi.dpi_outlook import read_outlook_subjects

    return read_outlook_subjects(date_from, date_to)


def load_protocols(date_from: date, date_to: date) -> list[dict[str, Any]]:
    from kpi.protocol_outlook import fetch_odata_protocols

    return fetch_odata_protocols(date_from - timedelta(days=31), date_to)


def load_cards() -> list[dict[str, Any]]:
    from kpi.instruction_tracker import fetch_odata_cards

    return fetch_odata_cards()


class SourceBundle:
    """Общие источники на один расчёт профиля: грузим только если калькулятор спросил."""

    def __init__(
        self,
        *,
        as_of: date,
        date_from: date,
        date_to: date,
    ) -> None:
        self.as_of = as_of
        self.date_from = date_from
        self.date_to = date_to
        self._events: object = _UNSET
        self._protocols: object = _UNSET
        self._cards: object = _UNSET
        self._metric_extra: dict[str, Any] = {}

    def _load(self, attr: str, loader) -> list[dict[str, Any]]:
        cached = getattr(self, attr)
        if cached is not _UNSET:
            return cached  # type: ignore[return-value]
        try:
            value = loader()
        except Exception as exc:  # noqa: BLE001
            logger.warning("position kpi source %s failed: %s", attr, exc)
            value = []
        setattr(self, attr, value)
        return value

    @property
    def events(self) -> list[dict[str, Any]]:
        return self._load("_events", lambda: load_outlook_events(self.date_from, self.date_to))

    @property
    def protocols(self) -> list[dict[str, Any]]:
        return self._load("_protocols", lambda: load_protocols(self.date_from, self.date_to))

    @property
    def cards(self) -> list[dict[str, Any]]:
        return self._load("_cards", load_cards)

    def extra_for(self, _metric: PositionKpiMetric | None = None) -> dict[str, Any]:
        return dict(self._metric_extra)

    def load_odata(self, extra: dict[str, Any]) -> list[dict[str, Any]]:
        entity = str(extra.get("entity") or "").strip()
        if not entity:
            return []
        try:
            from app.services.onec_tools import _fetch_odata_list

            raw = _fetch_odata_list(
                {
                    "entity": entity,
                    "filter": str(extra.get("filter") or ""),
                    "top": int(extra.get("top") or 200),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("position kpi odata %s failed: %s", entity, exc)
            return []
        rows = raw.get("value") or raw.get("rows") or []
        return [row for row in rows if isinstance(row, dict)]

    def load_files(self, extra: dict[str, Any]) -> list[dict[str, Any]]:
        path = str(extra.get("file") or extra.get("path") or "").strip()
        if not path:
            return []
        try:
            from kpi.instruction_tracker import load_tracker_xlsx

            return load_tracker_xlsx(Path(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("position kpi file %s failed: %s", path, exc)
            return []

    def load_for(self, extra: dict[str, Any] | None) -> list[dict[str, Any]]:
        data = extra if isinstance(extra, dict) else {}
        preset = data.get("rows")
        if isinstance(preset, list):
            return [row for row in preset if isinstance(row, dict)]
        loader = str(data.get("loader") or "").strip().lower()
        if loader == "outlook":
            return self.events
        if loader == "protocols":
            return self.protocols
        if loader == "cards":
            return self.cards
        if loader == "odata":
            return self.load_odata(data)
        if loader == "files":
            return self.load_files(data)
        if data.get("entity"):
            return self.load_odata(data)
        if data.get("file") or data.get("path"):
            return self.load_files(data)
        return []


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _metric_module(sources: list[PositionKpiSource]) -> str | None:
    for source in sources:
        if str(source.role or "") != "fact":
            continue
        extra = source.extra_json if isinstance(source.extra_json, dict) else {}
        module = str(extra.get("module") or "").strip()
        if scorer_for(module) is not None:
            return module
    return None


def _tile_from_report(
    metric: PositionKpiMetric,
    report: dict[str, Any],
    evidence: str,
) -> dict[str, Any]:
    fact = report.get("fact_pct")
    score = report.get("score_pct")
    contrib = report.get("contrib_pct")
    return {
        "code": metric.code,
        "name": metric.name,
        "weight": int(metric.weight or 0),
        "unit": metric.unit or "%",
        "plan": metric.plan_value,
        "fact": fact,
        "score": score,
        "contrib": contrib,
        "evidence": evidence,
        "detail": _jsonable(report),
    }


def _compute_tiles(db: Session, profile: PositionKpiProfile, ctx: SourceBundle) -> list[dict[str, Any]]:
    from app.services.position_kpi.connect import ensure_generated_modules

    ensure_generated_modules(db, profile.id)
    metrics = (
        db.execute(
            select(PositionKpiMetric)
            .where(PositionKpiMetric.profile_id == profile.id)
            .order_by(PositionKpiMetric.sort_order, PositionKpiMetric.code)
        )
        .scalars()
        .all()
    )
    if not metrics:
        return []
    sources_by_metric: dict[str, list[PositionKpiSource]] = {row.id: [] for row in metrics}
    source_rows = (
        db.execute(
            select(PositionKpiSource).where(PositionKpiSource.metric_id.in_(list(sources_by_metric)))
        )
        .scalars()
        .all()
    )
    for source in source_rows:
        sources_by_metric.setdefault(source.metric_id, []).append(source)

    tiles: list[dict[str, Any]] = []
    for metric in metrics:
        module = _metric_module(sources_by_metric.get(metric.id) or [])
        scorer = scorer_for(module)
        if scorer is None:
            continue
        extra: dict[str, Any] = {}
        for source in sources_by_metric.get(metric.id) or []:
            payload = source.extra_json if isinstance(source.extra_json, dict) else {}
            if str(source.role or "") == "fact" and payload:
                extra = payload
                break
        ctx._metric_extra = extra
        try:
            report, evidence = scorer(metric, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "position kpi %s/%s failed: %s",
                profile.id,
                metric.code,
                exc,
            )
            continue
        if not isinstance(report, dict):
            continue
        tiles.append(_tile_from_report(metric, report, evidence))
    return tiles


def _cache_row(
    db: Session,
    *,
    profile_id: str,
    day: date,
    period_from: date,
    period_to: date,
) -> PositionKpiDailyFact | None:
    return db.execute(
        select(PositionKpiDailyFact).where(
            PositionKpiDailyFact.profile_id == profile_id,
            PositionKpiDailyFact.day == day,
            PositionKpiDailyFact.period_from == period_from,
            PositionKpiDailyFact.period_to == period_to,
        )
    ).scalar_one_or_none()


def _payload(
    *,
    profile: PositionKpiProfile,
    as_of: date,
    date_from: date,
    date_to: date,
    tiles: list[dict[str, Any]],
    computed_at: datetime,
) -> dict[str, Any]:
    return {
        "position": profile.position_name,
        "profile_id": profile.id,
        "period_from": date_from.isoformat(),
        "period_to": date_to.isoformat(),
        "as_of": as_of.isoformat(),
        "computed_at": computed_at.isoformat(),
        "tiles": tiles,
    }


def _store(
    db: Session,
    *,
    profile: PositionKpiProfile,
    as_of: date,
    date_from: date,
    date_to: date,
    payload: dict[str, Any],
    computed_at: datetime,
) -> None:
    row = _cache_row(
        db,
        profile_id=profile.id,
        day=as_of,
        period_from=date_from,
        period_to=date_to,
    )
    if row is None:
        db.add(
            PositionKpiDailyFact(
                id=str(uuid.uuid4()),
                profile_id=profile.id,
                day=as_of,
                period_from=date_from,
                period_to=date_to,
                payload=payload,
                computed_at=computed_at,
            )
        )
    else:
        row.payload = payload
        row.computed_at = computed_at
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = _cache_row(
            db,
            profile_id=profile.id,
            day=as_of,
            period_from=date_from,
            period_to=date_to,
        )
        if row is None:
            raise
        row.payload = payload
        row.computed_at = computed_at
        db.commit()


def _latest_cache_row(
    db: Session,
    *,
    profile_id: str,
    period_from: date,
    period_to: date,
) -> PositionKpiDailyFact | None:
    return db.execute(
        select(PositionKpiDailyFact)
        .where(
            PositionKpiDailyFact.profile_id == profile_id,
            PositionKpiDailyFact.period_from == period_from,
            PositionKpiDailyFact.period_to == period_to,
        )
        .order_by(PositionKpiDailyFact.day.desc())
        .limit(1)
    ).scalar_one_or_none()


def _from_cache(row: PositionKpiDailyFact, *, stale: bool) -> dict[str, Any]:
    payload = dict(row.payload) if isinstance(row.payload, dict) else {}
    return {**payload, "cached": True, "stale": stale}


def read_position_kpi_snapshot(
    db: Session,
    position: str,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any] | None:
    """Только кэш, без расчёта. None — снимка ещё нет."""
    profile = resolve_profile(db, position)
    if profile is None:
        return None
    as_of = as_of or date.today()
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds(as_of.year, as_of.month)
    cached = _cache_row(
        db,
        profile_id=profile.id,
        day=as_of,
        period_from=date_from,
        period_to=date_to,
    )
    if cached is not None and isinstance(cached.payload, dict):
        return _from_cache(cached, stale=False)
    latest = _latest_cache_row(
        db,
        profile_id=profile.id,
        period_from=date_from,
        period_to=date_to,
    )
    if latest is not None and isinstance(latest.payload, dict):
        return _from_cache(latest, stale=latest.day != as_of)
    return None


def get_or_compute_position_kpi(
    db: Session,
    position: str,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    refresh: bool = False,
    allow_stale: bool = False,
) -> dict[str, Any]:
    profile = resolve_profile(db, position)
    if profile is None:
        raise PositionKpiNotFound(str(position or "").strip())
    as_of = as_of or date.today()
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds(as_of.year, as_of.month)
    if not refresh:
        cached = _cache_row(
            db,
            profile_id=profile.id,
            day=as_of,
            period_from=date_from,
            period_to=date_to,
        )
        if cached is not None and isinstance(cached.payload, dict):
            return _from_cache(cached, stale=False)
        if allow_stale:
            latest = _latest_cache_row(
                db,
                profile_id=profile.id,
                period_from=date_from,
                period_to=date_to,
            )
            if latest is not None and isinstance(latest.payload, dict):
                return _from_cache(latest, stale=latest.day != as_of)

    ctx = SourceBundle(as_of=as_of, date_from=date_from, date_to=date_to)
    tiles = _compute_tiles(db, profile, ctx)
    computed_at = datetime.now(timezone.utc)
    payload = _payload(
        profile=profile,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        tiles=tiles,
        computed_at=computed_at,
    )
    _store(
        db,
        profile=profile,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        payload=payload,
        computed_at=computed_at,
    )
    return {**payload, "cached": False, "stale": False}


def refresh_all_profiles(
    db: Session,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    force: bool = True,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds(as_of.year, as_of.month)
    computed: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    profiles = db.execute(select(PositionKpiProfile)).scalars().all()
    for profile in profiles:
        if not force:
            existing = _cache_row(
                db,
                profile_id=profile.id,
                day=as_of,
                period_from=date_from,
                period_to=date_to,
            )
            if existing is not None:
                skipped.append(profile.id)
                continue
        try:
            get_or_compute_position_kpi(
                db,
                profile.position_name,
                as_of=as_of,
                date_from=date_from,
                date_to=date_to,
                refresh=force,
            )
            computed.append(profile.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("position kpi warmup failed for %s", profile.id)
            failed.append({"profile_id": profile.id, "error": str(exc)})
    return {
        "ok": not failed,
        "as_of": as_of.isoformat(),
        "period_from": date_from.isoformat(),
        "period_to": date_to.isoformat(),
        "computed": computed,
        "skipped": skipped,
        "failed": failed,
    }


def run_daily_position_kpi_cache(*, force: bool = False) -> dict[str, Any]:
    """Заполнить кэш сегодняшнего дня. Повторный тик без force ничего не пересчитывает."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        result = refresh_all_profiles(db, force=force)
        logger.info(
            "position kpi daily cache as_of=%s computed=%s skipped=%s failed=%s",
            result.get("as_of"),
            len(result.get("computed") or []),
            len(result.get("skipped") or []),
            len(result.get("failed") or []),
        )
        return result
    except Exception:
        logger.exception("position kpi daily cache failed")
        return {"ok": False, "computed": [], "skipped": [], "failed": [{"error": "daily cache failed"}]}
    finally:
        db.close()


_FILL_LOCK = threading.Lock()
_FILL_STARTED: set[str] = set()


def schedule_today_fill(
    position: str,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> None:
    """Досчитать сегодняшний снимок в фоне, не блокируя GET."""

    day = as_of or date.today()
    start = date_from
    end = date_to
    key = f"{position}|{day.isoformat()}|{start}|{end}"
    with _FILL_LOCK:
        if key in _FILL_STARTED:
            return
        _FILL_STARTED.add(key)

    def _run() -> None:
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            get_or_compute_position_kpi(
                db,
                position,
                as_of=day,
                date_from=start,
                date_to=end,
                refresh=False,
            )
        except Exception:
            logger.warning("background position kpi fill failed for %s", position, exc_info=True)
        finally:
            db.close()
            with _FILL_LOCK:
                _FILL_STARTED.discard(key)

    threading.Thread(target=_run, name="position-kpi-today-fill", daemon=True).start()

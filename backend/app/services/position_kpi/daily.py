from __future__ import annotations

import calendar
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.position_kpi import (
    PositionKpiDailyFact,
    PositionKpiMetric,
    PositionKpiModule,
    PositionKpiProfile,
    PositionKpiSource,
    PositionKpiSubjectFact,
)
from app.services.position_kpi.registry import scorer_for

logger = logging.getLogger(__name__)

_UNSET = object()
_MSK = ZoneInfo("Europe/Moscow")


def msk_today() -> date:
    return datetime.now(_MSK).date()


class PositionKpiNotFound(Exception):
    """Должность нет в каталоге KPI."""


def normalize_position_name(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def subject_key(fio: str) -> str:
    """Ключ сотрудника в кэше: регистр и «ё» не различаем."""
    return " ".join(str(fio or "").casefold().replace("ё", "е").split())


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def department_key(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def resolve_profile(
    db: Session,
    position: str,
    *,
    as_of: date | None = None,
    department: str | None = None,
    exact_department: bool = False,
) -> PositionKpiProfile | None:
    """department=None keeps the old any-department lookup.

    With a department: its own profile, then the shared one (empty department), then any
    profile of the position. exact_department stops after the first step.
    """
    name = str(position or "").strip()
    if not name:
        return None
    target_day = as_of or date.today()
    exact_rows = db.execute(
        select(PositionKpiProfile).where(PositionKpiProfile.position_name == name)
    ).scalars().all()
    exact = _pick_profile(exact_rows, target_day, department, exact_department)
    if exact is not None:
        return exact
    wanted = normalize_position_name(name)
    if not wanted:
        return None
    normalized = [
        row
        for row in db.execute(select(PositionKpiProfile)).scalars()
        if normalize_position_name(row.position_name) == wanted
    ]
    return _pick_profile(normalized, target_day, department, exact_department)


def _pick_profile(
    rows: list[PositionKpiProfile],
    target_day: date,
    department: str | None,
    exact_department: bool,
) -> PositionKpiProfile | None:
    if department is None:
        return _profile_for_day(rows, target_day)
    wanted = department_key(department)
    own = _profile_for_day(
        [row for row in rows if department_key(row.department) == wanted], target_day
    )
    if own is not None or exact_department:
        return own
    shared = _profile_for_day([row for row in rows if not row.department.strip()], target_day)
    return shared or _profile_for_day(rows, target_day)


def _profile_for_day(
    rows: list[PositionKpiProfile], target_day: date
) -> PositionKpiProfile | None:
    eligible = [
        row
        for row in rows
        if (row.effective_from is None or row.effective_from <= target_day)
        and (row.effective_to is None or row.effective_to >= target_day)
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row.effective_from or date.min)


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
        subject_fio: str = "",
        subject_position: str = "",
        db: Session | None = None,
    ) -> None:
        self.as_of = as_of
        self.date_from = date_from
        self.date_to = date_to
        self.subject_fio = str(subject_fio or "").strip()
        self.subject_position = str(subject_position or "").strip()
        self.db = db
        self._events: object = _UNSET
        self._protocols: object = _UNSET
        self._cards: object = _UNSET
        self._metric_extra: dict[str, Any] = {}
        self._shared_failures: dict[str, str] = {}
        # Сбои источников текущего показателя: пустой список от упавшего источника — не «0 нарушений».
        self.source_errors: list[str] = []

    def note_failure(self, label: str, exc: BaseException | str) -> None:
        text = " ".join(str(exc).split())[:240]
        self.source_errors.append(f"{label}: {text}" if text else label)

    def _load(self, attr: str, loader) -> list[dict[str, Any]]:
        cached = getattr(self, attr)
        if cached is not _UNSET:
            if attr in self._shared_failures:
                self.note_failure(attr.lstrip("_"), self._shared_failures[attr])
            return cached  # type: ignore[return-value]
        try:
            value = loader()
        except Exception as exc:  # noqa: BLE001
            logger.warning("position kpi source %s failed: %s", attr, exc)
            self._shared_failures[attr] = str(exc)
            self.note_failure(attr.lstrip("_"), exc)
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

            payload: dict[str, Any] = {
                "entity": entity,
                "filter": str(extra.get("filter") or ""),
                "top": int(extra.get("top") or 200),
            }
            if extra.get("skip") is not None:
                payload["skip"] = int(extra["skip"])
            if extra.get("select"):
                payload["select"] = str(extra["select"])
            raw = _fetch_odata_list(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("position kpi odata %s failed: %s", entity, exc)
            self.note_failure(f"1С {entity}", exc)
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
            self.note_failure("файл", exc)
            return []

    def load_docflow(self, extra: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            from kpi.sources.assistant_tasks import fetch_rows

            performer = str(extra.get("performer") or "").strip()
            return fetch_rows(self.date_from, self.date_to, performer=performer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("position kpi docflow cache failed: %s", exc)
            self.note_failure("Документооборот", exc)
            return []

    def load_for(self, extra: dict[str, Any] | None) -> list[dict[str, Any]]:
        data = extra if isinstance(extra, dict) else {}
        preset = data.get("rows")
        if isinstance(preset, list):
            return [row for row in preset if isinstance(row, dict)]
        if str(data.get("source") or "").strip():
            from app.services.position_kpi.sources import load as load_registry_source

            return load_registry_source(data, self)
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
        if loader == "docflow":
            return self.load_docflow(data)
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


def _profile_has_calculator(db: Session, profile_id: str) -> bool:
    metric_ids = list(
        db.scalars(select(PositionKpiMetric.id).where(PositionKpiMetric.profile_id == profile_id)).all()
    )
    if not metric_ids:
        return False
    by_metric: dict[str, list[PositionKpiSource]] = {}
    for source in db.scalars(select(PositionKpiSource).where(PositionKpiSource.metric_id.in_(metric_ids))).all():
        by_metric.setdefault(source.metric_id, []).append(source)
    return any(_metric_module(rows) for rows in by_metric.values())


def _metric_module(sources: list[PositionKpiSource]) -> str | None:
    for source in sources:
        if str(source.role or "") != "fact":
            continue
        extra = source.extra_json if isinstance(source.extra_json, dict) else {}
        module = str(extra.get("module") or "").strip()
        if scorer_for(module) is not None:
            return module
    return None


_EMPTY_PCT = frozenset({"нет базы", "нет данных", "n/a", "-", ""})
_PCT_LINE = re.compile(r"(?im)^(Факт|Выполнение|Вклад):\s*(.+)$")


def _read_pct(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", ".").replace("%", "").strip()
    if text.casefold() in _EMPTY_PCT:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def module_pcts(report: dict[str, Any] | None, text: str = "") -> dict[str, float | None]:
    """fact/score из JSON модуля или из stdout «Факт: 83.33» / «Выполнение: 87.72%»."""
    blob = dict(report or {})
    fact = _read_pct(blob.get("fact_pct"))
    if fact is None:
        fact = _read_pct(blob.get("fact"))
    score = _read_pct(blob.get("score_pct"))
    if score is None:
        score = _read_pct(blob.get("score"))
    contrib = _read_pct(blob.get("contrib_pct"))
    if contrib is None:
        contrib = _read_pct(blob.get("contribution"))
        if contrib is None:
            contrib = _read_pct(blob.get("contrib"))
    src = text or str(blob.get("text") or "")
    if src:
        found: dict[str, str] = {}
        for match in _PCT_LINE.finditer(src):
            found[match.group(1).casefold()] = match.group(2).strip()
        if fact is None:
            fact = _read_pct(found.get("факт"))
        if score is None:
            score = _read_pct(found.get("выполнение"))
        if contrib is None:
            contrib = _read_pct(found.get("вклад"))
    return {"fact_pct": fact, "score_pct": score, "contrib_pct": contrib}


def _hydrate_tiles(payload: dict[str, Any]) -> dict[str, Any]:
    tiles = payload.get("tiles")
    if not isinstance(tiles, list):
        return payload
    fixed: list[Any] = []
    for tile in tiles:
        if not isinstance(tile, dict) or tile.get("fact") is not None:
            fixed.append(tile)
            continue
        detail = tile.get("detail") if isinstance(tile.get("detail"), dict) else {}
        pcts = module_pcts(detail, str(detail.get("text") or tile.get("evidence") or ""))
        fixed.append(
            {
                **tile,
                "fact": pcts["fact_pct"],
                "score": tile.get("score") if tile.get("score") is not None else pcts["score_pct"],
                "contrib": tile.get("contrib") if tile.get("contrib") is not None else pcts["contrib_pct"],
            }
        )
    return {**payload, "tiles": fixed}


def _tile_from_report(
    metric: PositionKpiMetric,
    report: dict[str, Any],
    evidence: str,
) -> dict[str, Any]:
    pcts = module_pcts(report, evidence)
    fact = report.get("fact_pct")
    if fact is None:
        fact = pcts["fact_pct"]
    score = report.get("score_pct")
    if score is None:
        score = pcts["score_pct"]
    contrib = report.get("contrib_pct")
    if contrib is None:
        contrib = pcts["contrib_pct"]
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
        ctx.source_errors = []
        try:
            report, evidence = scorer(metric, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "position kpi %s/%s failed: %s",
                profile.id,
                metric.code,
                exc,
            )
            reason = " ".join(str(exc).split())[:240]
            tiles.append(
                _tile_from_report(
                    metric,
                    {
                        "fact_pct": None,
                        "score_pct": None,
                        "contrib_pct": None,
                        "module_error": True,
                    },
                    f"Модуль не посчитал: {reason}" if reason else "Модуль не посчитал.",
                )
            )
            continue
        if not isinstance(report, dict):
            continue
        if ctx.source_errors:
            failures = "; ".join(dict.fromkeys(ctx.source_errors))
            report = {**report, "fact_pct": None, "score_pct": None, "contrib_pct": None, "source_errors": failures}
            evidence = f"Источник не ответил — показатель не посчитан. {failures}"
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


def _subject_row(
    db: Session,
    *,
    profile_id: str,
    subject: str,
    day: date,
    period_from: date,
    period_to: date,
) -> PositionKpiSubjectFact | None:
    return db.execute(
        select(PositionKpiSubjectFact).where(
            PositionKpiSubjectFact.profile_id == profile_id,
            PositionKpiSubjectFact.subject == subject,
            PositionKpiSubjectFact.day == day,
            PositionKpiSubjectFact.period_from == period_from,
            PositionKpiSubjectFact.period_to == period_to,
        )
    ).scalar_one_or_none()


def _latest_subject_row(
    db: Session,
    *,
    profile_id: str,
    subject: str,
    period_from: date,
    period_to: date,
) -> PositionKpiSubjectFact | None:
    return db.execute(
        select(PositionKpiSubjectFact)
        .where(
            PositionKpiSubjectFact.profile_id == profile_id,
            PositionKpiSubjectFact.subject == subject,
            PositionKpiSubjectFact.period_from == period_from,
            PositionKpiSubjectFact.period_to == period_to,
        )
        .order_by(PositionKpiSubjectFact.day.desc())
        .limit(1)
    ).scalar_one_or_none()


def _is_agent_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("source") == "kpi_launch_agent"


def _store_subject(
    db: Session,
    *,
    profile: PositionKpiProfile,
    subject: str,
    subject_fio: str,
    as_of: date,
    date_from: date,
    date_to: date,
    payload: dict[str, Any],
    computed_at: datetime,
) -> None:
    lookup = {
        "profile_id": profile.id,
        "subject": subject,
        "day": as_of,
        "period_from": date_from,
        "period_to": date_to,
    }
    row = _subject_row(db, **lookup)
    if row is not None and _is_agent_payload(row.payload) and not _is_agent_payload(payload):
        return
    if row is None:
        db.add(
            PositionKpiSubjectFact(
                id=str(uuid.uuid4()),
                subject_fio=subject_fio,
                payload=payload,
                computed_at=computed_at,
                **lookup,
            )
        )
    else:
        row.payload = payload
        row.computed_at = computed_at
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = _subject_row(db, **lookup)
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


def _from_cache(row: PositionKpiDailyFact | PositionKpiSubjectFact, *, stale: bool) -> dict[str, Any]:
    payload = dict(row.payload) if isinstance(row.payload, dict) else {}
    return {**_hydrate_tiles(payload), "cached": True, "stale": stale}


def _cached_snapshot(
    db: Session,
    *,
    profile: PositionKpiProfile,
    subject: str,
    as_of: date,
    date_from: date,
    date_to: date,
    allow_stale: bool,
) -> dict[str, Any] | None:
    if subject:
        exact = _subject_row(
            db,
            profile_id=profile.id,
            subject=subject,
            day=as_of,
            period_from=date_from,
            period_to=date_to,
        )
    else:
        exact = _cache_row(
            db,
            profile_id=profile.id,
            day=as_of,
            period_from=date_from,
            period_to=date_to,
        )
    if exact is not None and isinstance(exact.payload, dict):
        return _from_cache(exact, stale=False)
    if not allow_stale:
        return None
    if subject:
        latest = _latest_subject_row(
            db,
            profile_id=profile.id,
            subject=subject,
            period_from=date_from,
            period_to=date_to,
        )
    else:
        latest = _latest_cache_row(
            db,
            profile_id=profile.id,
            period_from=date_from,
            period_to=date_to,
        )
    if latest is not None and isinstance(latest.payload, dict):
        return _from_cache(latest, stale=latest.day != as_of)
    return None


def runner_cache_root() -> Path:
    """Каталог, куда «Запуск модулей KPI» кладёт JSON расчёта: день / модуль / ФИО."""
    return Path.home() / "Documents" / "kpi" / "cache"


def _parse_runner_output(text: str) -> dict[str, Any]:
    found: dict[str, str] = {}
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        found[label.strip()] = value.strip()

    def number(label: str) -> float | None:
        raw = found.get(label, "").replace("%", "").replace(",", ".").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    fact = number("Факт")
    if fact is None:
        return {}
    return {
        "fact_pct": fact,
        "score_pct": number("Выполнение"),
        "contrib_pct": number("Вклад"),
    }


def tiles_from_runner_cache(
    db: Session,
    profile: PositionKpiProfile,
    *,
    fio: str,
    as_of: date,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Плитки из уже посчитанного кэша агента. Экран KPI читает базу, а не эти файлы."""
    person = str(fio or "").strip()
    if not person:
        return []
    day_dir = (root or runner_cache_root()) / as_of.isoformat()
    if not day_dir.is_dir():
        return []
    modules = list(
        db.scalars(select(PositionKpiModule).where(PositionKpiModule.profile_id == profile.id)).all()
    )
    metrics = {
        row.code: row
        for row in db.scalars(
            select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile.id)
        ).all()
    }
    wanted = subject_key(person)
    tiles: list[dict[str, Any]] = []
    for module in modules:
        stem = str(module.module_name or "").rsplit(".", 1)[-1].strip()
        code = str(module.metric_code or "").strip()
        metric = metrics.get(code)
        folder = day_dir / stem
        if not stem or metric is None or not folder.is_dir():
            continue
        match = next((path for path in folder.glob("*.json") if subject_key(path.stem) == wanted), None)
        if match is None:
            continue
        try:
            payload = json.loads(match.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(payload, dict) or str(payload.get("status") or "").strip().lower() != "ok":
            continue
        stored = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        parsed = _parse_runner_output(str(payload.get("output") or ""))
        no_base = bool(stored.get("no_base")) or "нет базы" in str(payload.get("output") or "").casefold()
        fact = stored.get("fact")
        if fact is None:
            fact = parsed.get("fact_pct")
        if fact is None and not no_base:
            continue
        score = stored.get("score")
        if score is None:
            score = parsed.get("score_pct")
        contrib = stored.get("contribution")
        if contrib is None:
            contrib = parsed.get("contrib_pct")
        rows = stored.get("rows") if isinstance(stored.get("rows"), list) else []
        evidence = "нет базы" if no_base and fact is None else f"факт {fact}%"
        tiles.append(
            _tile_from_report(
                metric,
                {
                    "fact_pct": None if no_base and fact is None else fact,
                    "score_pct": None if no_base and fact is None else score,
                    "contrib_pct": None if no_base and fact is None else contrib,
                    "rows": rows,
                },
                evidence,
            )
        )
    tiles.sort(key=lambda tile: (metrics[tile["code"]].sort_order, tile["code"]))
    return tiles


def publish_subject_tiles(
    db: Session,
    profile: PositionKpiProfile,
    *,
    fio: str,
    as_of: date,
    date_from: date,
    date_to: date,
    tiles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Личный снимок, который читает экран KPI."""
    person = str(fio or "").strip()
    computed_at = datetime.now(timezone.utc)
    payload = _payload(
        profile=profile,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        tiles=tiles,
        computed_at=computed_at,
    )
    payload["subject"] = person
    _store_subject(
        db,
        profile=profile,
        subject=subject_key(person),
        subject_fio=person,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        payload=payload,
        computed_at=computed_at,
    )
    return {**payload, "cached": True, "stale": False}


def read_today_position_kpi(
    db: Session,
    position: str,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    subject: str = "",
    department: str | None = None,
) -> dict[str, Any]:
    """Сегодняшний снимок из кэша. Нет строки — плитки из кэша агента, иначе пустые, без расчёта."""
    as_of = as_of or date.today()
    profile = resolve_profile(db, position, as_of=as_of, department=department)
    if profile is None:
        raise PositionKpiNotFound(str(position or "").strip())
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds(as_of.year, as_of.month)
    cached = _cached_snapshot(
        db,
        profile=profile,
        subject=subject_key(subject),
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        allow_stale=False,
    )
    if cached is not None:
        return cached
    person = str(subject or "").strip()
    if person:
        imported = tiles_from_runner_cache(db, profile, fio=person, as_of=as_of)
        if imported:
            return publish_subject_tiles(
                db,
                profile,
                fio=person,
                as_of=as_of,
                date_from=date_from,
                date_to=date_to,
                tiles=imported,
            )
    payload = _payload(
        profile=profile,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        tiles=[],
        computed_at=datetime.now(timezone.utc),
    )
    if str(subject or "").strip():
        payload["subject"] = str(subject).strip()
    return {**payload, "cached": False, "stale": False}


def read_position_kpi_snapshot(
    db: Session,
    position: str,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    subject: str = "",
    department: str | None = None,
) -> dict[str, Any] | None:
    """Только кэш, без расчёта. None — снимка ещё нет."""
    as_of = as_of or msk_today()
    profile = resolve_profile(db, position, as_of=as_of, department=department)
    if profile is None:
        return None
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds(as_of.year, as_of.month)
    return _cached_snapshot(
        db,
        profile=profile,
        subject=subject_key(subject),
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        allow_stale=True,
    )


def get_or_compute_position_kpi(
    db: Session,
    position: str,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    refresh: bool = False,
    allow_stale: bool = False,
    subject: str = "",
    department: str | None = None,
) -> dict[str, Any]:
    """KPI должности. subject — ФИО сотрудника: модули общие, а цифры и кэш у каждого свои.

    department — подразделение сотрудника: у одной должности в разных подразделениях
    может быть своя методика.
    """
    as_of = as_of or msk_today()
    profile = resolve_profile(db, position, as_of=as_of, department=department)
    if profile is None:
        raise PositionKpiNotFound(str(position or "").strip())
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds(as_of.year, as_of.month)
    from app.services.position_kpi.connect import ensure_generated_modules

    if ensure_generated_modules(db, profile.id):
        db.commit()
        profile = resolve_profile(db, position, as_of=as_of, department=department)
        if profile is None:
            raise PositionKpiNotFound(str(position or "").strip())
    key = subject_key(subject)
    if refresh and key:
        published = _subject_row(
            db,
            profile_id=profile.id,
            subject=key,
            day=as_of,
            period_from=date_from,
            period_to=date_to,
        )
        if published is not None and _is_agent_payload(published.payload):
            return _from_cache(published, stale=False)
    if not refresh:
        cached = _cached_snapshot(
            db,
            profile=profile,
            subject=key,
            as_of=as_of,
            date_from=date_from,
            date_to=date_to,
            allow_stale=allow_stale,
        )
        if cached is not None and (cached.get("tiles") or not _profile_has_calculator(db, profile.id)):
            return cached

    ctx = SourceBundle(
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        subject_fio=str(subject or "").strip(),
        subject_position=profile.position_name,
        db=db,
    )
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
    failed_run = bool(tiles) and all((tile.get("detail") or {}).get("module_error") for tile in tiles)
    if failed_run or (not tiles and _profile_has_calculator(db, profile.id)):
        return {**payload, "cached": False, "stale": False}
    if key:
        payload["subject"] = str(subject or "").strip()
        _store_subject(
            db,
            profile=profile,
            subject=key,
            subject_fio=str(subject or "").strip(),
            as_of=as_of,
            date_from=date_from,
            date_to=date_to,
            payload=payload,
            computed_at=computed_at,
        )
    else:
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


def attach_tile_history(db: Session, payload: dict[str, Any], *, subject: str = "") -> dict[str, Any]:
    """Факт каждого показателя по дням месяца из дневного кэша — для графика на плитке."""
    try:
        period_from = date.fromisoformat(str(payload.get("period_from") or ""))
        period_to = date.fromisoformat(str(payload.get("period_to") or ""))
    except ValueError:
        return payload
    profile_id = str(payload.get("profile_id") or "")
    key = subject_key(subject)
    if key:
        query = select(PositionKpiSubjectFact.day, PositionKpiSubjectFact.payload).where(
            PositionKpiSubjectFact.profile_id == profile_id,
            PositionKpiSubjectFact.subject == key,
            PositionKpiSubjectFact.period_from == period_from,
            PositionKpiSubjectFact.period_to == period_to,
        )
    else:
        query = select(PositionKpiDailyFact.day, PositionKpiDailyFact.payload).where(
            PositionKpiDailyFact.profile_id == profile_id,
            PositionKpiDailyFact.period_from == period_from,
            PositionKpiDailyFact.period_to == period_to,
        )
    series: dict[str, dict[str, float]] = {}
    for day, row_payload in db.execute(query).all():
        tiles = row_payload.get("tiles") if isinstance(row_payload, dict) else None
        for tile in tiles or []:
            if isinstance(tile, dict) and tile.get("code") and tile.get("fact") is not None:
                series.setdefault(str(tile["code"]), {})[day.isoformat()] = float(tile["fact"])
    as_of = str(payload.get("as_of") or "")
    tiles_out: list[dict[str, Any]] = []
    for tile in payload.get("tiles") or []:
        if not isinstance(tile, dict):
            continue
        points = dict(series.get(str(tile.get("code") or ""), {}))
        if as_of and tile.get("fact") is not None:
            points[as_of] = float(tile["fact"])
        tiles_out.append({**tile, "history": [{"day": d, "value": v} for d, v in sorted(points.items())]})
    return {**payload, "tiles": tiles_out}


def _known_subjects(
    db: Session,
    *,
    profile_id: str,
    period_from: date,
    period_to: date,
) -> list[tuple[str, str]]:
    """Сотрудники, у которых уже открывали KPI за этот период: их снимки держим свежими."""
    rows = db.execute(
        select(PositionKpiSubjectFact.subject, PositionKpiSubjectFact.subject_fio).where(
            PositionKpiSubjectFact.profile_id == profile_id,
            PositionKpiSubjectFact.period_from == period_from,
            PositionKpiSubjectFact.period_to == period_to,
        )
    ).all()
    seen: dict[str, str] = {}
    for subject, fio in rows:
        if subject and subject not in seen:
            seen[subject] = fio or subject
    return list(seen.items())


def refresh_all_profiles(
    db: Session,
    *,
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    force: bool = True,
) -> dict[str, Any]:
    as_of = as_of or msk_today()
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
                department=profile.department,
            )
            computed.append(profile.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("position kpi warmup failed for %s", profile.id)
            failed.append({"profile_id": profile.id, "error": str(exc)})
    subjects = 0
    for profile in profiles:
        for key, fio in _known_subjects(db, profile_id=profile.id, period_from=date_from, period_to=date_to):
            if not force and _subject_row(
                db,
                profile_id=profile.id,
                subject=key,
                day=as_of,
                period_from=date_from,
                period_to=date_to,
            ):
                continue
            try:
                get_or_compute_position_kpi(
                    db,
                    profile.position_name,
                    as_of=as_of,
                    date_from=date_from,
                    date_to=date_to,
                    refresh=True,
                    subject=fio,
                    department=profile.department,
                )
                subjects += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("position kpi warmup failed for %s / %s", profile.id, key)
                failed.append({"profile_id": profile.id, "subject": key, "error": str(exc)})
    return {
        "ok": not failed,
        "as_of": as_of.isoformat(),
        "period_from": date_from.isoformat(),
        "period_to": date_to.isoformat(),
        "computed": computed,
        "skipped": skipped,
        "subjects": subjects,
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
    subject: str = "",
    department: str | None = None,
) -> None:
    """Досчитать сегодняшний снимок в фоне, не блокируя GET."""

    day = as_of or date.today()
    start = date_from
    end = date_to
    key = f"{position}|{department}|{subject_key(subject)}|{day.isoformat()}|{start}|{end}"
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
                subject=subject,
                department=department,
            )
        except Exception:
            logger.warning("background position kpi fill failed for %s", position, exc_info=True)
        finally:
            db.close()
            with _FILL_LOCK:
                _FILL_STARTED.discard(key)

    threading.Thread(target=_run, name="position-kpi-today-fill", daemon=True).start()

"""Дневной прогон агента «Запуск модулей KPI».

Считает компьютер того, кто первым за день открыл вкладку KPI. Сервер раздаёт
должности (claim), чтобы два компьютера не считали одно и то же, и хранит
итог: плитки по сотрудникам в position_kpi_subject_facts и отчёты ИЦПП.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.jwt import AuthContext
from app.models.position_kpi import (
    PositionKpiDailyReport,
    PositionKpiDailyRun,
    PositionKpiMetric,
    PositionKpiModule,
    PositionKpiProfile,
    PositionKpiSubjectFact,
)
from app.services.position_kpi.daily import (
    _payload,
    _profile_for_day,
    _store_subject,
    _tile_from_report,
    department_key,
    month_bounds,
    normalize_position_name,
    resolve_profile,
    subject_key,
)

logger = logging.getLogger(__name__)

AGENT_SOURCE = "kpi_launch_agent"
CLAIM_TTL = timedelta(minutes=45)
MAX_REPORT_BYTES = 10 * 1024 * 1024
_MSK = ZoneInfo("Europe/Moscow")


class DailyRunError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def msk_today() -> date:
    return datetime.now(_MSK).date()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _profile_out(profile: PositionKpiProfile) -> dict[str, str]:
    return {
        "profile_id": profile.id,
        "position": profile.position_name,
        "department": profile.department or "",
    }


def _module_profile_ids(db: Session) -> set[str]:
    return {
        row.profile_id
        for row in db.scalars(select(PositionKpiModule)).all()
        if (row.source or "").strip()
    }


def _own_profile(db: Session, auth: AuthContext, day: date) -> PositionKpiProfile | None:
    position = (auth.position or "").strip()
    if not position:
        return None
    return resolve_profile(db, position, as_of=day, department=(auth.department or "").strip())


def _active_profiles(db: Session, day: date) -> list[PositionKpiProfile]:
    """Одна действующая методика на пару «должность + подразделение»."""
    groups: dict[tuple[str, str], list[PositionKpiProfile]] = {}
    for row in db.scalars(select(PositionKpiProfile)).all():
        if (row.status or "active") != "active":
            continue
        key = (normalize_position_name(row.position_name), department_key(row.department))
        groups.setdefault(key, []).append(row)
    picked: list[PositionKpiProfile] = []
    for rows in groups.values():
        profile = _profile_for_day(rows, day)
        if profile is not None:
            picked.append(profile)
    return sorted(picked, key=lambda row: (row.position_name, row.department))


def _run_row(db: Session, profile_id: str, day: date) -> PositionKpiDailyRun | None:
    return db.execute(
        select(PositionKpiDailyRun).where(
            PositionKpiDailyRun.profile_id == profile_id,
            PositionKpiDailyRun.day == day,
        )
    ).scalar_one_or_none()


def _is_stale(row: PositionKpiDailyRun, now: datetime) -> bool:
    claimed = _as_utc(row.claimed_at)
    return claimed is None or now - claimed > CLAIM_TTL


def _report_row(db: Session, profile_id: str, subject: str, day: date) -> PositionKpiDailyReport | None:
    return db.execute(
        select(PositionKpiDailyReport).where(
            PositionKpiDailyReport.profile_id == profile_id,
            PositionKpiDailyReport.subject == subject,
            PositionKpiDailyReport.day == day,
        )
    ).scalar_one_or_none()


def _agent_subject_row(db: Session, profile_id: str, subject: str, day: date) -> PositionKpiSubjectFact | None:
    rows = db.scalars(
        select(PositionKpiSubjectFact).where(
            PositionKpiSubjectFact.profile_id == profile_id,
            PositionKpiSubjectFact.subject == subject,
            PositionKpiSubjectFact.day == day,
        )
    ).all()
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        if payload.get("source") == AGENT_SOURCE:
            return row
    return None


def _run_out(row: PositionKpiDailyRun | None) -> dict[str, Any] | None:
    if row is None:
        return None
    claimed = _as_utc(row.claimed_at)
    finished = _as_utc(row.finished_at)
    return {
        "status": row.status,
        "claimed_by_user_id": row.claimed_by_user_id,
        "claimed_at": claimed.isoformat() if claimed else "",
        "finished_at": finished.isoformat() if finished else "",
        "error": row.error or "",
        "people": list(row.people_json or []),
    }


def today_status(db: Session, auth: AuthContext, *, day: date | None = None) -> dict[str, Any]:
    """ready / running_here / running_elsewhere / missing / failed / no_modules / no_profile."""
    day = day or msk_today()
    now = _now()
    base: dict[str, Any] = {"day": day.isoformat(), "fio": (auth.fio or "").strip()}
    profile = _own_profile(db, auth, day)
    if profile is None:
        return {**base, "status": "no_profile", "profile": None, "run": None, "report_available": False}
    base["profile"] = _profile_out(profile)
    if profile.id not in _module_profile_ids(db):
        return {**base, "status": "no_modules", "run": None, "report_available": False}
    row = _run_row(db, profile.id, day)
    subject = subject_key(auth.fio or "")
    report_available = bool(subject) and _report_row(db, profile.id, subject, day) is not None
    own_facts = bool(subject) and _agent_subject_row(db, profile.id, subject, day) is not None
    extra = {"run": _run_out(row), "report_available": report_available, "own_facts": own_facts}
    if row is None:
        return {**base, **extra, "status": "missing"}
    if row.status == "done":
        return {**base, **extra, "status": "ready"}
    if row.status == "failed":
        return {**base, **extra, "status": "failed"}
    if row.status == "skipped":
        return {**base, **extra, "status": "no_modules"}
    if _is_stale(row, now):
        return {**base, **extra, "status": "missing"}
    status = "running_here" if row.claimed_by_user_id == auth.user_id else "running_elsewhere"
    return {**base, **extra, "status": status}


def _try_claim(
    db: Session,
    profile: PositionKpiProfile,
    day: date,
    user_id: str,
    *,
    retry_failed: bool,
) -> bool:
    now = _now()
    row = _run_row(db, profile.id, day)
    if row is None:
        db.add(
            PositionKpiDailyRun(
                id=str(uuid.uuid4()),
                profile_id=profile.id,
                day=day,
                status="running",
                claimed_by_user_id=user_id,
                claimed_at=now,
                people_json=[],
            )
        )
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False
    if row.status == "done" or row.status == "skipped":
        return False
    if row.status == "failed" and not retry_failed:
        return False
    if row.status == "running" and not _is_stale(row, now) and row.claimed_by_user_id != user_id:
        return False
    row.status = "running"
    row.claimed_by_user_id = user_id
    row.claimed_at = now
    row.finished_at = None
    row.error = ""
    db.commit()
    return True


def _mark_skipped(db: Session, profile: PositionKpiProfile, day: date) -> None:
    if _run_row(db, profile.id, day) is not None:
        return
    db.add(
        PositionKpiDailyRun(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            day=day,
            status="skipped",
            error="У должности нет модулей KPI",
            finished_at=_now(),
            people_json=[],
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def claim(
    db: Session,
    auth: AuthContext,
    scope: str,
    *,
    retry_failed: bool = False,
    day: date | None = None,
) -> dict[str, Any]:
    """own — должность пользователя; others — все остальные должности с модулями."""
    day = day or msk_today()
    scope = (scope or "").strip().casefold()
    own = _own_profile(db, auth, day)
    with_modules = _module_profile_ids(db)
    if scope == "own":
        if own is None:
            raise DailyRunError("У пользователя нет методики KPI", 404)
        if own.id not in with_modules:
            _mark_skipped(db, own, day)
            return {"day": day.isoformat(), "scope": "own", "granted": False, "profiles": [], "reason": "no_modules"}
        granted = _try_claim(db, own, day, auth.user_id, retry_failed=retry_failed)
        out = _profile_out(own)
        if not (out["department"] or "").strip():
            out["department"] = (auth.department or "").strip()
        return {
            "day": day.isoformat(),
            "scope": "own",
            "granted": granted,
            "profiles": [out] if granted else [],
            "reason": "" if granted else "taken",
        }
    if scope != "others":
        raise DailyRunError("scope: own или others")
    claimed: list[dict[str, str]] = []
    skipped: list[str] = []
    for profile in _active_profiles(db, day):
        if own is not None and profile.id == own.id:
            continue
        if profile.id not in with_modules:
            _mark_skipped(db, profile, day)
            skipped.append(profile.id)
            continue
        if _try_claim(db, profile, day, auth.user_id, retry_failed=False):
            claimed.append(_profile_out(profile))
    return {
        "day": day.isoformat(),
        "scope": "others",
        "granted": bool(claimed),
        "profiles": claimed,
        "skipped": skipped,
    }


_JSON_TAIL = re.compile(r"\{.*\}", re.DOTALL)


def _report_from_output(output: Any) -> tuple[dict[str, Any], str]:
    """Вывод модуля → отчёт с fact_pct/score_pct/contrib_pct и строка-обоснование."""
    if isinstance(output, dict):
        inner = output.get("report")
        report = inner if isinstance(inner, dict) and "fact_pct" not in output else output
        return dict(report), str(output.get("evidence") or "").strip()
    text = str(output or "").strip()
    if not text:
        return {}, ""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
        match = _JSON_TAIL.search(text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except ValueError:
                parsed = None
    if isinstance(parsed, dict):
        report, evidence = _report_from_output(parsed)
        return report, evidence
    from app.services.position_kpi.daily import module_pcts

    pcts = module_pcts({"text": text}, text)
    report = {"text": text, **{key: value for key, value in pcts.items() if value is not None}}
    evidence = text.splitlines()[-1].strip()
    return report, evidence


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return None


def _metric_tile(metric: PositionKpiMetric, item: dict[str, Any]) -> dict[str, Any]:
    report, evidence = _report_from_output(item.get("output"))
    for key in ("fact_pct", "score_pct", "contrib_pct"):
        explicit = _number(item.get(key))
        if explicit is not None:
            report[key] = explicit
    if not evidence:
        evidence = str(item.get("evidence") or "").strip()
    if not evidence:
        fact = report.get("fact_pct")
        evidence = "нет данных" if fact is None else f"факт {fact}%"
    return _tile_from_report(metric, report, evidence)


def _decode_report(person: dict[str, Any]) -> tuple[bytes | None, str]:
    raw = str(person.get("report_base64") or "").strip()
    if not raw:
        return None, ""
    try:
        content = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DailyRunError(f"Отчёт {person.get('fio') or ''}: не base64") from exc
    if len(content) > MAX_REPORT_BYTES:
        raise DailyRunError("Отчёт больше 10 МБ")
    name = str(person.get("report_filename") or "").strip() or "icpp.xlsx"
    return content, name


def _store_report(
    db: Session,
    *,
    profile_id: str,
    subject: str,
    fio: str,
    day: date,
    content: bytes,
    filename: str,
) -> None:
    row = _report_row(db, profile_id, subject, day)
    if row is None:
        db.add(
            PositionKpiDailyReport(
                id=str(uuid.uuid4()),
                profile_id=profile_id,
                subject=subject,
                subject_fio=fio,
                day=day,
                filename=filename,
                content=content,
            )
        )
    else:
        row.subject_fio = fio
        row.filename = filename
        row.content = content
    db.commit()


def _period(month: str, day: date) -> tuple[date, date]:
    text = str(month or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, mon = (int(part) for part in text.split("-"))
        if 1 <= mon <= 12:
            return month_bounds(year, mon)
    return month_bounds(day.year, day.month)


def publish(db: Session, auth: AuthContext, args: dict[str, Any], *, day: date | None = None) -> dict[str, Any]:
    """Итог агента по одной должности: плитки по каждому сотруднику и их отчёты ИЦПП."""
    day = day or msk_today()
    profile_id = str(args.get("profile_id") or "").strip()
    if not profile_id:
        raise DailyRunError("profile_id обязателен")
    profile = db.get(PositionKpiProfile, profile_id)
    if profile is None:
        raise DailyRunError(f"Методика {profile_id} не найдена", 404)
    status = str(args.get("status") or "done").strip().casefold()
    if status not in {"done", "failed"}:
        raise DailyRunError("status: done или failed")
    date_from, date_to = _period(str(args.get("month") or ""), day)
    metrics = {
        row.code: row
        for row in db.scalars(select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile.id)).all()
    }
    order = {code: (row.sort_order, code) for code, row in metrics.items()}
    people_in = args.get("people") if isinstance(args.get("people"), list) else []
    people_out: list[dict[str, Any]] = []
    unknown: set[str] = set()
    stored_subjects = 0
    stored_reports = 0
    computed_at = _now()
    for person in people_in:
        if not isinstance(person, dict):
            continue
        fio = " ".join(str(person.get("fio") or "").split())
        subject = subject_key(fio)
        if not subject:
            continue
        person_status = str(person.get("status") or "ok").strip().casefold() or "ok"
        tiles: list[dict[str, Any]] = []
        module_cache: list[dict[str, Any]] = []
        for item in person.get("metrics") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("metric_code") or item.get("code") or "").strip()
            metric = metrics.get(code)
            if metric is None:
                if code:
                    unknown.add(code)
                continue
            tiles.append(_metric_tile(metric, item))
            module_cache.append({"metric_code": code, "output": item.get("output")})
        tiles.sort(key=lambda tile: order.get(str(tile.get("code")), (0, "")))
        content, filename = _decode_report(person)
        if tiles or module_cache:
            payload = _payload(
                profile=profile,
                as_of=day,
                date_from=date_from,
                date_to=date_to,
                tiles=tiles,
                computed_at=computed_at,
            )
            payload["subject"] = fio
            payload["source"] = AGENT_SOURCE
            payload["report_available"] = content is not None
            payload["modules"] = module_cache
            _store_subject(
                db,
                profile=profile,
                subject=subject,
                subject_fio=fio,
                as_of=day,
                date_from=date_from,
                date_to=date_to,
                payload=payload,
                computed_at=computed_at,
            )
            stored_subjects += 1
        if content is not None:
            _store_report(
                db,
                profile_id=profile.id,
                subject=subject,
                fio=fio,
                day=day,
                content=content,
                filename=filename,
            )
            stored_reports += 1
        people_out.append(
            {
                "fio": fio,
                "subject": subject,
                "status": person_status,
                "error": str(person.get("error") or "").strip(),
                "tiles": len(tiles),
                "report_filename": filename,
            }
        )
    row = _run_row(db, profile.id, day)
    if row is None:
        row = PositionKpiDailyRun(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            day=day,
            claimed_by_user_id=auth.user_id,
            claimed_at=computed_at,
        )
        db.add(row)
    row.status = status
    row.finished_at = computed_at
    row.error = str(args.get("error") or "").strip()
    row.people_json = people_out
    db.commit()
    logger.info(
        "position kpi daily run published profile=%s status=%s subjects=%s reports=%s",
        profile.id,
        status,
        stored_subjects,
        stored_reports,
    )
    result: dict[str, Any] = {
        "ok": True,
        "profile_id": profile.id,
        "position": profile.position_name,
        "day": day.isoformat(),
        "status": status,
        "subjects": stored_subjects,
        "reports": stored_reports,
    }
    if unknown:
        result["unknown_metric_codes"] = sorted(unknown)
    return result


def own_report(
    db: Session,
    auth: AuthContext,
    *,
    fio: str = "",
    day: date | None = None,
) -> PositionKpiDailyReport | None:
    """Последний отчёт агента по сотруднику за текущий месяц."""
    day = day or msk_today()
    profile = _own_profile(db, auth, day)
    if profile is None:
        return None
    subject = subject_key(fio or auth.fio or "")
    if not subject:
        return None
    first, _last = month_bounds(day.year, day.month)
    return db.execute(
        select(PositionKpiDailyReport)
        .where(
            PositionKpiDailyReport.profile_id == profile.id,
            PositionKpiDailyReport.subject == subject,
            PositionKpiDailyReport.day >= first,
            PositionKpiDailyReport.day <= day,
        )
        .order_by(PositionKpiDailyReport.day.desc())
        .limit(1)
    ).scalar_one_or_none()

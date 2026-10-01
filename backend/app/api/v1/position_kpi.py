from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.models.position_kpi import PositionKpiMetric, PositionKpiModule
from app.schemas.position_kpi import PositionKpiDailyOut, PositionKpiSubjectOut
from app.services.position_kpi.bonus_form import ReportSubjectError, render_bonus_form, resolve_report_subject
from app.services.position_kpi.compensation import (
    CompensationError,
    masked_compensation,
    unlock_compensation,
)
from app.services.position_kpi.daily import (
    PositionKpiNotFound,
    SourceBundle,
    attach_tile_history,
    get_or_compute_position_kpi,
    month_bounds,
    resolve_profile,
    schedule_today_fill,
)
from app.services.position_kpi import pin as kpi_pin
from app.services.position_kpi import protection as kpi_protection
from app.services.position_kpi.explain import PositionKpiMetricNotFound, explain_metric
from app.services.position_kpi.salary import SalaryLookupError
from app.services.position_kpi.sources import SOURCES, catalog, validate_spec
from app.services.position_kpi.sources import load as load_source

router = APIRouter(prefix="/position-kpi", tags=["position-kpi"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _subject_or_http(*, fio: str, position: str) -> dict[str, str]:
    try:
        return resolve_report_subject(fio=fio, position=position)
    except ReportSubjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/subject", response_model=PositionKpiSubjectOut)
def read_position_kpi_subject(
    fio: str = Query(default=""),
    position: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
) -> PositionKpiSubjectOut:
    requested = fio.strip()
    if requested:
        subject = _subject_or_http(fio=requested, position=position.strip())
    else:
        subject = _subject_or_http(fio=(auth.fio or "").strip(), position=position.strip() or (auth.position or ""))
    return PositionKpiSubjectOut.model_validate(subject)


class _ProtectionOut(BaseModel):
    enabled: bool
    has_password: bool


class _ProtectionIn(BaseModel):
    enabled: bool
    password: str | None = Field(default=None, max_length=128)
    current_password: str | None = Field(default=None, max_length=128)


class _UnlockIn(BaseModel):
    password: str = Field(max_length=128)


def _protection_out(state: kpi_protection.ProtectionState) -> _ProtectionOut:
    return _ProtectionOut(enabled=state.enabled, has_password=state.has_password)


@router.get("/protection", response_model=_ProtectionOut)
def read_protection(auth: AuthContext = Depends(get_current_user)) -> _ProtectionOut:
    return _protection_out(kpi_protection.get_state(auth.user_id))


@router.put("/protection", response_model=_ProtectionOut)
def update_protection(body: _ProtectionIn, auth: AuthContext = Depends(get_current_user)) -> _ProtectionOut:
    try:
        state = kpi_protection.update_protection(
            auth.user_id,
            enabled=body.enabled,
            password=body.password,
            current_password=body.current_password,
        )
    except kpi_protection.KpiProtectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _protection_out(state)


@router.post("/unlock")
def unlock_money(body: _UnlockIn, auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    try:
        token, expires = kpi_protection.unlock(auth.user_id, body.password)
    except kpi_protection.KpiProtectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"token": token, "expires_at": expires}


@router.get("/bonus-form")
def download_bonus_form(
    fio: str = Query(default=""),
    position: str = Query(default=""),
    period_from: str | None = Query(default=None, alias="from"),
    period_to: str | None = Query(default=None, alias="to"),
    unlock: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    requested = fio.strip()
    if requested:
        subject_fio, subject_position = requested, position.strip()
    else:
        subject_fio, subject_position = (auth.fio or "").strip(), position.strip() or (auth.position or "")
    date_from = _parse_day(period_from, field="from")
    date_to = _parse_day(period_to, field="to")
    with_money = False
    if unlock.strip():
        if not kpi_protection.token_unlocks(auth.user_id, unlock):
            raise HTTPException(status_code=403, detail="Доступ к суммам истёк. Введите пароль KPI ещё раз.")
        with_money = True
    try:
        content, filename = render_bonus_form(
            db,
            fio=subject_fio,
            position=subject_position,
            date_from=date_from,
            date_to=date_to,
            with_money=with_money,
        )
    except ReportSubjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except SalaryLookupError as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось получить оклад из 1С: {exc}") from exc
    except PositionKpiNotFound as exc:
        name = str(exc) or subject_position or subject_fio
        raise HTTPException(
            status_code=404,
            detail=f"Для должности «{name}» нет каталога KPI, форму премирования собрать нельзя.",
        ) from None
    encoded = quote(filename)
    return Response(
        content=content,
        media_type=_XLSX,
        headers={"Content-Disposition": f"attachment; filename=\"icpp.xlsx\"; filename*=UTF-8''{encoded}"},
    )


def _parse_day(raw: str | None, *, field: str) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректная дата {field}") from exc


class _PinOut(BaseModel):
    has_pin: bool


class _PinSetIn(BaseModel):
    pin: str = Field(max_length=16)
    pin_repeat: str = Field(max_length=16)


class _PinChangeIn(_PinSetIn):
    current_pin: str = Field(max_length=16)


def _pin_http(exc: kpi_pin.KpiPinError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/pin", response_model=_PinOut)
def read_pin(auth: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)) -> _PinOut:
    try:
        return _PinOut(has_pin=kpi_pin.has_pin(db, auth.user_id))
    except kpi_pin.KpiPinError as exc:
        raise _pin_http(exc) from exc


@router.post("/pin", response_model=_PinOut)
def create_pin(
    body: _PinSetIn, auth: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)
) -> _PinOut:
    try:
        kpi_pin.set_pin(db, auth.user_id, body.pin, body.pin_repeat)
    except kpi_pin.KpiPinError as exc:
        raise _pin_http(exc) from exc
    return _PinOut(has_pin=True)


@router.put("/pin", response_model=_PinOut)
def change_pin(
    body: _PinChangeIn, auth: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)
) -> _PinOut:
    try:
        kpi_pin.change_pin(db, auth.user_id, body.current_pin, body.pin, body.pin_repeat)
    except kpi_pin.KpiPinError as exc:
        raise _pin_http(exc) from exc
    return _PinOut(has_pin=True)


class _CompensationUnlockIn(BaseModel):
    pin: str = Field(min_length=1, max_length=32)
    period_from: str | None = None
    period_to: str | None = None


@router.get("/compensation")
def read_compensation(
    period_to: str | None = Query(default=None, alias="to"),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return masked_compensation(db, auth, as_of=_parse_day(period_to, field="to"))


@router.post("/compensation/unlock")
def unlock_compensation_tile(
    body: _CompensationUnlockIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return unlock_compensation(
            db,
            auth,
            pin=body.pin,
            date_from=_parse_day(body.period_from, field="from"),
            date_to=_parse_day(body.period_to, field="to"),
        )
    except CompensationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=PositionKpiDailyOut)
@router.get("/", response_model=PositionKpiDailyOut)
def read_position_kpi(
    position: str = Query(default=""),
    period_from: str | None = Query(default=None, alias="from"),
    period_to: str | None = Query(default=None, alias="to"),
    refresh: bool = Query(default=False),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiDailyOut:
    name = (position or auth.position or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите должность")
    date_from = _parse_day(period_from, field="from")
    date_to = _parse_day(period_to, field="to")
    subject = (auth.fio or "").strip()
    own_position = (auth.position or "").strip().casefold() == name.casefold()
    department = (auth.department or "").strip() if own_position else None
    try:
        payload = get_or_compute_position_kpi(
            db,
            name,
            date_from=date_from,
            date_to=date_to,
            refresh=refresh,
            allow_stale=not refresh,
            subject=subject,
            department=department,
        )
    except PositionKpiNotFound:
        raise HTTPException(status_code=404, detail="Должность не найдена в каталоге KPI") from None
    if payload.get("stale") and not refresh:
        schedule_today_fill(
            name, date_from=date_from, date_to=date_to, subject=subject, department=department
        )
    return PositionKpiDailyOut.model_validate(attach_tile_history(db, payload, subject=subject))


@router.get("/sources")
def list_data_sources(auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    """Реестр источников данных, из которых калькуляторы KPI берут строки."""
    del auth
    return {"sources": catalog()}


@router.get("/methodology")
def read_methodology_status(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    position = (auth.position or "").strip()
    if not position:
        raise HTTPException(status_code=400, detail="У пользователя не указана должность")
    profile = resolve_profile(db, position, department=(auth.department or "").strip())
    if profile is None or not (profile.source_import_id or "").strip():
        return {
            "status": "none",
            "position": position,
            "department": "",
            "profile_id": "",
            "source_title": "",
            "effective_from": "",
            "metrics": [],
        }
    metrics = list(
        db.scalars(
            select(PositionKpiMetric)
            .where(PositionKpiMetric.profile_id == profile.id)
            .order_by(PositionKpiMetric.sort_order, PositionKpiMetric.id)
        ).all()
    )
    from app.services.position_kpi.connect import builtin_metric_codes

    module_codes = set(
        db.scalars(
            select(PositionKpiModule.metric_code).where(
                PositionKpiModule.profile_id == profile.id
            )
        ).all()
    ) | builtin_metric_codes(db, profile.id)
    ready = bool(metrics) and all(metric.code in module_codes for metric in metrics)
    return {
        "status": "ready" if ready else "needs_modules",
        "position": profile.position_name,
        "department": profile.department,
        "profile_id": profile.id,
        "source_title": profile.source_title,
        "effective_from": profile.effective_from.isoformat() if profile.effective_from else "",
        "metrics": [
            {
                "code": metric.code,
                "name": metric.name,
                "weight": metric.weight,
                "formula_human": metric.formula_human,
                "module_ready": metric.code in module_codes,
            }
            for metric in metrics
        ],
    }


class _ProbeIn(BaseModel):
    source: str
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int = 20


@router.post("/sources/probe")
def probe_data_source(
    body: _ProbeIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Живые строки источника для текущего сотрудника — чтобы модуль писали под реальные поля."""
    spec = {"source": body.source, "params": body.params}
    check = validate_spec(spec)
    if check["errors"]:
        raise HTTPException(status_code=400, detail=" ".join(check["errors"]))
    today = date.today()
    start, end = month_bounds(today.year, today.month)
    ctx = SourceBundle(
        as_of=today,
        date_from=start,
        date_to=end,
        subject_fio=(auth.fio or "").strip(),
        subject_position=(auth.position or "").strip(),
        db=db,
    )
    rows = load_source(spec, ctx)
    limit = max(1, min(int(body.limit or 20), 100))
    return {
        "source": body.source,
        "title": SOURCES[body.source].title,
        "count": len(rows),
        "rows": rows[:limit],
        "warnings": check["warnings"],
    }


@router.get("/metrics/{code}")
def read_metric_code(
    code: str,
    position: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Код калькулятора, источник данных и формула показателя — для кнопки «i» на плитке."""
    name = (position or auth.position or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите должность")
    try:
        return explain_metric(db, name, code.strip())
    except PositionKpiNotFound:
        raise HTTPException(status_code=404, detail="Должность не найдена в каталоге KPI") from None
    except PositionKpiMetricNotFound:
        raise HTTPException(status_code=404, detail="У должности нет такого показателя") from None

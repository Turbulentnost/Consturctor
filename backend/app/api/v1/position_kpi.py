from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.position_kpi import PositionKpiDailyOut, PositionKpiSubjectOut
from app.services.position_kpi.bonus_form import ReportSubjectError, render_bonus_form, resolve_report_subject
from app.services.position_kpi.daily import (
    PositionKpiNotFound,
    get_or_compute_position_kpi,
    schedule_today_fill,
)

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


@router.get("/bonus-form")
def download_bonus_form(
    fio: str = Query(default=""),
    position: str = Query(default=""),
    period_from: str | None = Query(default=None, alias="from"),
    period_to: str | None = Query(default=None, alias="to"),
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
    try:
        content, filename = render_bonus_form(
            db,
            fio=subject_fio,
            position=subject_position,
            date_from=date_from,
            date_to=date_to,
        )
    except ReportSubjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
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
    try:
        payload = get_or_compute_position_kpi(
            db,
            name,
            date_from=date_from,
            date_to=date_to,
            refresh=refresh,
            allow_stale=not refresh,
        )
    except PositionKpiNotFound:
        raise HTTPException(status_code=404, detail="Должность не найдена в каталоге KPI") from None
    if payload.get("stale") and not refresh:
        schedule_today_fill(name, date_from=date_from, date_to=date_to)
    return PositionKpiDailyOut.model_validate(payload)

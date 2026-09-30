from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import require_admin_page
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services import auth_service
from app.services.admin import finance

router = APIRouter(prefix="/admin/finance", tags=["admin-finance"])


def _http(exc: finance.FinanceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/employees")
async def employees(
    search: str = Query(default=""),
    department: str = Query(default=""),
    limit: int = Query(default=2000, ge=1, le=2000),
    _auth: AuthContext = Depends(require_admin_page("finance_employees")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        login_fios = await auth_service.list_user_fios(search, limit=limit)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return finance.list_employees(
        db,
        department=department,
        limit=limit,
        login_fios=login_fios,
    )


@router.get("/employees/{person_id}/salaries")
def salaries(
    person_id: str,
    _auth: AuthContext = Depends(require_admin_page("finance_employees")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return finance.employee_salaries(db, person_id)
    except finance.FinanceError as exc:
        raise _http(exc) from exc


@router.get("/positions")
def positions(
    limit: int = Query(default=2000, ge=1, le=5000),
    _auth: AuthContext = Depends(require_admin_page("finance_upload")),
    db: Session = Depends(get_db),
) -> dict:
    return finance.list_positions(db, limit=limit)


@router.get("/employees/{person_id}/kpi")
def employee_kpi(
    person_id: str,
    period_from: date | None = Query(default=None, alias="from"),
    period_to: date | None = Query(default=None, alias="to"),
    _auth: AuthContext = Depends(require_admin_page("finance_employees")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return finance.employee_kpi(
            db,
            person_id,
            period_from=period_from,
            period_to=period_to,
        )
    except finance.FinanceError as exc:
        raise _http(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/imports")
async def upload_import(
    kind: str = Query(...),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_admin_page("finance_upload")),
    db: Session = Depends(get_db),
) -> dict:
    raw = await file.read()
    try:
        return finance.create_import(
            db,
            kind=kind,
            filename=file.filename or "file",
            raw=raw,
            user_id=auth.user_id,
            user_fio=auth.fio or "",
        )
    except finance.FinanceError as exc:
        raise _http(exc) from exc


@router.get("/imports")
def imports(
    kind: str = Query(default=""),
    status: str = Query(default=""),
    _auth: AuthContext = Depends(require_admin_page("finance_import_history")),
    db: Session = Depends(get_db),
) -> dict:
    return finance.list_imports(db, kind=kind, status=status)


@router.get("/imports/{import_id}")
def import_detail(
    import_id: str,
    _auth: AuthContext = Depends(require_admin_page("finance_import_history")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return finance.serialize_import(finance.get_import(db, import_id))
    except finance.FinanceError as exc:
        raise _http(exc) from exc


@router.patch("/imports/{import_id}")
def update_import(
    import_id: str,
    draft: dict = Body(...),
    _auth: AuthContext = Depends(require_admin_page("finance_upload")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return finance.update_import_draft(db, import_id, draft)
    except finance.FinanceError as exc:
        raise _http(exc) from exc


@router.post("/imports/{import_id}/confirm")
def confirm_import(
    import_id: str,
    _auth: AuthContext = Depends(require_admin_page("finance_upload")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return finance.confirm_import(db, import_id)
    except finance.FinanceError as exc:
        raise _http(exc) from exc


@router.get("/imports/{import_id}/file")
def download_import(
    import_id: str,
    _auth: AuthContext = Depends(require_admin_page("finance_import_history")),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        row = finance.get_import(db, import_id)
    except finance.FinanceError as exc:
        raise _http(exc) from exc
    path = Path(row.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Исходный файл не найден")
    return FileResponse(path, media_type=row.media_type, filename=row.original_name)

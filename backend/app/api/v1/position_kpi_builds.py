from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.position_kpi import (
    PositionKpiBuildConnectIn,
    PositionKpiBuildCreate,
    PositionKpiBuildOut,
    PositionKpiBuildSdkFinishIn,
    PositionKpiBuildTurnIn,
)
from app.services.position_kpi.builder import (
    PositionKpiBuildError,
    attach_files,
    connect_build,
    finish_sdk,
    get_build,
    persist_turn,
    start_build,
)

router = APIRouter(prefix="/position-kpi/builds", tags=["position-kpi-builds"])
logger = logging.getLogger(__name__)


def _http(exc: PositionKpiBuildError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


async def _files_from_request(request: Request) -> list[tuple[str, bytes]]:
    content_type = (request.headers.get("content-type") or "").lower()
    files: list[tuple[str, bytes]] = []
    if "multipart/form-data" not in content_type:
        return files
    form = await request.form()
    uploads = list(form.getlist("files")) + list(form.getlist("file"))
    for item in uploads:
        read = getattr(item, "read", None)
        if read is None:
            continue
        data = await read()
        filename = str(getattr(item, "filename", None) or "file")
        if data:
            files.append((filename, bytes(data)))
    return files


@router.post("", response_model=PositionKpiBuildOut)
def create_build(
    body: PositionKpiBuildCreate | None = None,
    position: str = Query(default=""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiBuildOut:
    name = ((body.position if body else "") or position or auth.position or "").strip()
    try:
        payload = start_build(db, user_id=auth.user_id, position=name)
    except PositionKpiBuildError as exc:
        raise _http(exc) from exc
    return PositionKpiBuildOut.model_validate(payload)


@router.get("/{build_id}", response_model=PositionKpiBuildOut)
def read_build(
    build_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiBuildOut:
    try:
        payload = get_build(db, user_id=auth.user_id, build_id=build_id)
    except PositionKpiBuildError as exc:
        raise _http(exc) from exc
    return PositionKpiBuildOut.model_validate(payload)


@router.post("/{build_id}/files", response_model=PositionKpiBuildOut)
async def upload_build_files(
    build_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiBuildOut:
    files = await _files_from_request(request)
    try:
        payload = attach_files(db, user_id=auth.user_id, build_id=build_id, files=files)
    except PositionKpiBuildError as exc:
        raise _http(exc) from exc
    return PositionKpiBuildOut.model_validate(payload)


@router.post("/{build_id}/turns", response_model=PositionKpiBuildOut)
async def create_build_turn(
    build_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiBuildOut:
    files = await _files_from_request(request)
    content_type = (request.headers.get("content-type") or "").lower()
    message = ""
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw = form.get("message")
        if raw is not None and not hasattr(raw, "filename"):
            message = str(raw or "")
    else:
        body = PositionKpiBuildTurnIn.model_validate(await request.json())
        message = body.message
    try:
        payload = persist_turn(
            db,
            user_id=auth.user_id,
            build_id=build_id,
            message=message,
            files=files or None,
        )
    except PositionKpiBuildError as exc:
        raise _http(exc) from exc
    return PositionKpiBuildOut.model_validate(payload)


@router.post("/{build_id}/sdk-finish", response_model=PositionKpiBuildOut)
def finish_build_sdk(
    build_id: str,
    body: PositionKpiBuildSdkFinishIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiBuildOut:
    try:
        payload = finish_sdk(
            db,
            user_id=auth.user_id,
            build_id=build_id,
            answer=body.answer,
            events=body.events,
            modules=body.modules,
            catalog_draft=body.catalog_draft,
            cursor_agent_id=body.cursor_agent_id,
            connect=body.connect,
        )
    except PositionKpiBuildError as exc:
        raise _http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PositionKpiBuildOut.model_validate(payload)


@router.post("/{build_id}/connect", response_model=PositionKpiBuildOut)
def connect_build_catalog(
    build_id: str,
    body: PositionKpiBuildConnectIn | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionKpiBuildOut:
    payload_in = body or PositionKpiBuildConnectIn()
    try:
        payload = connect_build(
            db,
            user_id=auth.user_id,
            build_id=build_id,
            catalog_draft=payload_in.catalog_draft or None,
            modules=payload_in.modules or None,
        )
    except PositionKpiBuildError as exc:
        raise _http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PositionKpiBuildOut.model_validate(payload)

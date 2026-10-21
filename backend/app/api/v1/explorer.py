from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.services import explorer
from app.services.org_structure import people_in_department

router = APIRouter(prefix="/explorer", tags=["explorer"])


class AccessBody(BaseModel):
    mode: str = "private"
    users: list[dict[str, str]] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    all_permission: str = "write"


class FolderCreate(BaseModel):
    name: str
    parent_id: str | None = None


class BlankFileCreate(BaseModel):
    name: str
    parent_id: str | None = None
    access: AccessBody = Field(default_factory=AccessBody)


def _actor(db: Session, auth: AuthContext) -> explorer.Actor:
    return explorer.actor_for(db, auth.user_id, auth.fio, auth.department)


def _fail(exc: explorer.ExplorerError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _parse_access_json(raw: str) -> explorer.AccessSpec:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise explorer.ExplorerError("Некорректные настройки доступа") from exc
    return explorer.parse_access(payload if isinstance(payload, dict) else {})


@router.get("/items")
def list_items(
    folder_id: str | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return explorer.list_folder(db, _actor(db, auth), folder_id or None)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.post("/folders")
def create_folder(
    body: FolderCreate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return explorer.create_folder(db, _actor(db, auth), body.parent_id or None, body.name)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.post("/files/blank")
def create_blank_file(
    body: BlankFileCreate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        access = explorer.parse_access(body.access.model_dump())
        return explorer.create_file(db, _actor(db, auth), body.parent_id or None, body.name, None, access)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.post("/files/upload")
def upload_file(
    file: UploadFile = File(...),
    parent_id: str = Form(""),
    name: str = Form(""),
    access: str = Form(""),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        spec = _parse_access_json(access)
        data = file.file.read()
        return explorer.create_file(
            db, _actor(db, auth), parent_id or None, name or file.filename or "", data, spec
        )
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.get("/files/{file_id}/content")
def download_file(
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        entry, data = explorer.read_file(db, _actor(db, auth), file_id)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc
    return Response(
        content=data,
        media_type=entry.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(entry.name)}"},
    )


@router.post("/files/{file_id}/content")
def replace_file_content(
    file_id: str,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return explorer.write_file(db, _actor(db, auth), file_id, file.file.read())
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.get("/files/{file_id}/access")
def read_access(
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return explorer.read_access(db, _actor(db, auth), file_id)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.put("/files/{file_id}/access")
def update_access(
    file_id: str,
    body: AccessBody,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        spec = explorer.parse_access(body.model_dump())
        return explorer.update_access(db, _actor(db, auth), file_id, spec)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


class DiskPathBody(BaseModel):
    path: str


@router.get("/department-people")
def department_people(
    name: str,
    _auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": people_in_department(db, name)}


@router.post("/open-path")
def open_by_disk_path(
    body: DiskPathBody,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        return explorer.resolve_disk_path(db, _actor(db, auth), body.path)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc


@router.delete("/items/{entry_id}")
def delete_item(
    entry_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        explorer.delete_entry(db, _actor(db, auth), entry_id)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc
    return {"ok": True}


class SuggestionDecision(BaseModel):
    accept: bool = True


@router.get("/access-suggestions")
def list_access_suggestions(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.server_agents.access_advisor import list_pending

    return {"items": list_pending(db, auth.user_id)}


@router.post("/access-suggestions/{suggestion_id}")
def decide_access_suggestion(
    suggestion_id: str,
    body: SuggestionDecision,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    from app.services.server_agents.access_advisor import decide

    try:
        decide(db, auth.user_id, suggestion_id, body.accept)
    except explorer.ExplorerError as exc:
        raise _fail(exc) from exc
    return {"ok": True}

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.workflow import (
    ArtifactItem,
    ArtifactsDownloadRequest,
    ExecuteRequest,
    LocalRunUpdate,
    WorkflowHealth,
    WorkflowListItem,
    WorkflowSchema,
)
from app.services.workflows import (
    WorkflowError,
    build_artifacts_zip,
    clarify_workflow,
    create_workflow,
    delete_workflow,
    execute_workflow,
    get_workflow,
    list_artifacts_for_workflow,
    list_workflows,
    plan_workflow,
    update_local_run,
    workflow_health,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _raise(exc: WorkflowError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/health", response_model=WorkflowHealth)
async def read_workflow_health(
    auth: AuthContext = Depends(get_current_user),
) -> WorkflowHealth:
    _ = auth
    return workflow_health()


@router.get("", response_model=list[WorkflowListItem])
async def read_workflows(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowListItem]:
    return list_workflows(db, user_id=auth.user_id)


@router.post("", response_model=WorkflowSchema)
async def create_workflow_endpoint(
    notes: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        raw = await upload.read()
        payloads.append((upload.filename or "file", raw))
    try:
        return create_workflow(db, user_id=auth.user_id, notes=notes, files=payloads)
    except WorkflowError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{workflow_id}", response_model=WorkflowSchema)
async def read_workflow(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return get_workflow(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.delete("/{workflow_id}")
async def remove_workflow(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    try:
        delete_workflow(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise
    return {"ok": True}


@router.post("/{workflow_id}/plan", response_model=WorkflowSchema)
async def plan_workflow_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return plan_workflow(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/clarify", response_model=WorkflowSchema)
async def clarify_workflow_endpoint(
    workflow_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    content_type = (request.headers.get("content-type") or "").lower()
    answers: dict[str, str] = {}
    files: list[tuple[str, bytes]] = []
    file_question_ids: list[str] = []
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            raw_answers = form.get("answers") or "{}"
            parsed = json.loads(str(raw_answers))
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400, detail="answers должен быть JSON-объектом")
            answers = {str(k): str(v or "") for k, v in parsed.items()}
            qids_raw = form.get("file_question_ids") or "[]"
            qids = json.loads(str(qids_raw))
            if isinstance(qids, list):
                file_question_ids = [str(x or "") for x in qids]
            uploads = form.getlist("files")
            for upload in uploads:
                if not hasattr(upload, "read"):
                    continue
                raw = await upload.read()
                files.append((getattr(upload, "filename", None) or "file", raw))
        else:
            body = await request.json()
            raw = (body or {}).get("answers") or {}
            if not isinstance(raw, dict):
                raise HTTPException(status_code=400, detail="answers должен быть объектом")
            answers = {str(k): str(v or "") for k, v in raw.items()}
        return clarify_workflow(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            answers=answers,
            files=files,
            file_question_ids=file_question_ids,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Некорректный JSON в clarify") from exc
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/execute", response_model=WorkflowSchema)
async def execute_workflow_endpoint(
    workflow_id: str,
    request: ExecuteRequest | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    body = request or ExecuteRequest()
    try:
        return execute_workflow(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            reexecute=body.reexecute,
        )
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.get("/{workflow_id}/artifacts", response_model=list[ArtifactItem])
async def read_artifacts(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ArtifactItem]:
    try:
        return list_artifacts_for_workflow(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/artifacts/download")
async def download_artifacts_endpoint(
    workflow_id: str,
    request: ArtifactsDownloadRequest | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    body = request or ArtifactsDownloadRequest()
    try:
        zip_path = build_artifacts_zip(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            paths=body.paths,
        )
    except WorkflowError as exc:
        _raise(exc)
        raise
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"workflow-{workflow_id}-artifacts.zip",
    )


@router.patch("/{workflow_id}/local-run", response_model=WorkflowSchema)
async def patch_local_run(
    workflow_id: str,
    request: LocalRunUpdate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return update_local_run(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            local_run=request.local_run,
        )
    except WorkflowError as exc:
        _raise(exc)
        raise

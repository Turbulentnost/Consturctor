from __future__ import annotations

import json
from queue import Queue
from threading import Thread

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import SessionLocal, get_db
from app.schemas.workflow import (
    ArtifactItem,
    ArtifactsDownloadRequest,
    ExecuteRequest,
    LocalRunUpdate,
    WorkflowHealth,
    WorkflowListItem,
    WorkflowSchema,
)
from app.services.agent_runtime import AgentRuntimeError, available_tools, run_agent_task
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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _workflow_stream(action):
    queue: Queue[dict | None] = Queue()

    def emit(event_type: str, text: str) -> None:
        queue.put({"type": event_type, "text": text})

    def run() -> None:
        db = SessionLocal()
        try:
            record = action(db, emit)
            queue.put({"type": "workflow", "workflow": record.model_dump(mode="json")})
        except WorkflowError as exc:
            queue.put({"type": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            queue.put({"type": "error", "message": str(exc)})
        finally:
            db.close()
            queue.put(None)

    Thread(target=run, daemon=True).start()
    while True:
        item = queue.get()
        if item is None:
            break
        yield _sse(item)


def _agent_run_stream(*, user_id: str, workflow_id: str, message: str):
    queue: Queue[dict | None] = Queue()

    def emit(payload: dict) -> None:
        queue.put(payload)

    def run() -> None:
        db = SessionLocal()
        try:
            result = run_agent_task(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                message=message,
                emit=emit,
            )
            queue.put({"type": "done", "result": result})
        except AgentRuntimeError as exc:
            queue.put({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            queue.put({"type": "error", "message": str(exc)})
        finally:
            db.close()
            queue.put(None)

    Thread(target=run, daemon=True).start()
    while True:
        item = queue.get()
        if item is None:
            break
        yield _sse(item)


async def _parse_clarify_request(request: Request) -> tuple[dict[str, str], list[tuple[str, bytes]], list[str]]:
    content_type = (request.headers.get("content-type") or "").lower()
    answers: dict[str, str] = {}
    files: list[tuple[str, bytes]] = []
    file_question_ids: list[str] = []
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
        return answers, files, file_question_ids
    body = await request.json()
    raw = (body or {}).get("answers") or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="answers должен быть объектом")
    return {str(k): str(v or "") for k, v in raw.items()}, files, file_question_ids


@router.get("/health", response_model=WorkflowHealth)
async def read_workflow_health(
    auth: AuthContext = Depends(get_current_user),
) -> WorkflowHealth:
    _ = auth
    return workflow_health()


@router.get("/agent-tools")
async def read_agent_tools(
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, list[dict]]:
    _ = auth
    return {"tools": available_tools()}


@router.get("", response_model=list[WorkflowListItem])
async def read_workflows(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowListItem]:
    return list_workflows(db, user_id=auth.user_id)


@router.post("/{workflow_id}/agent-runs/stream")
async def run_workflow_agent_stream(
    workflow_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    body = await request.json()
    message = str((body or {}).get("message") or "").strip()
    return StreamingResponse(
        _agent_run_stream(
            user_id=auth.user_id,
            workflow_id=workflow_id,
            message=message,
        ),
        media_type="text/event-stream",
    )


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


@router.post("/{workflow_id}/plan/stream")
async def plan_workflow_stream_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    user_id = auth.user_id
    return StreamingResponse(
        _workflow_stream(
            lambda db, emit: plan_workflow(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                on_event=emit,
            )
        ),
        media_type="text/event-stream",
    )


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


@router.post("/{workflow_id}/clarify/stream")
async def clarify_workflow_stream_endpoint(
    workflow_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    answers, files, file_question_ids = await _parse_clarify_request(request)
    user_id = auth.user_id
    return StreamingResponse(
        _workflow_stream(
            lambda db, emit: clarify_workflow(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                answers=answers,
                files=files,
                file_question_ids=file_question_ids,
                on_event=emit,
            )
        ),
        media_type="text/event-stream",
    )


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


@router.post("/{workflow_id}/execute/stream")
async def execute_workflow_stream_endpoint(
    workflow_id: str,
    request: ExecuteRequest | None = None,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    body = request or ExecuteRequest()
    user_id = auth.user_id
    return StreamingResponse(
        _workflow_stream(
            lambda db, emit: execute_workflow(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                reexecute=body.reexecute,
                on_event=emit,
            )
        ),
        media_type="text/event-stream",
    )


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

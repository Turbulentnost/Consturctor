from __future__ import annotations

import json
import logging
from queue import Queue
from threading import Event, Thread
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import SessionLocal, get_db
from app.schemas.trigger import ScheduleDraftOut
from app.schemas.workflow import (
    AgentKpiSchema,
    AgentRunCreate,
    AgentRunEventsUpdate,
    AgentRunFinish,
    AgentRunOut,
    AgentToolResultSubmit,
    ArtifactItem,
    ArtifactsDownloadRequest,
    AutoRunStopResult,
    ExecuteRequest,
    LocalRunUpdate,
    LocalDemoFinish,
    PlatformFilesResponse,
    WorkflowBoard,
    WorkflowFilesResponse,
    WorkflowHealth,
    WorkflowListItem,
    WorkflowSchema,
)
from app.services.agent_runs import (
    answer_from_result,
    finish_agent_run,
    get_agent_run,
    list_agent_runs,
    save_run_events,
    start_agent_run,
)
from app.services.agent_runtime import AgentRuntimeError, available_tools, run_agent_task
from app.services.tool_bridge import ToolBridgeError, tool_bridge
from app.services.workflows import (
    WorkflowError,
    build_local_design_prompt,
    build_artifacts_zip,
    clarify_workflow,
    confirm_agent_kpi,
    create_workflow,
    delete_workflow,
    demo_workflow,
    execute_workflow,
    finish_local_design_workflow,
    finish_local_demo_workflow,
    generate_agent_kpi,
    get_agent_kpi,
    get_workflow,
    list_artifacts_for_workflow,
    list_workflows,
    plan_workflow,
    publish_workflow,
    resume_auto_run,
    stop_auto_run,
    update_local_run,
    workflow_health,
)
from app.services.workflows.board import get_workflow_board
from app.services.workflows.schedule_draft import propose_schedule_draft
from app.services.workflow_files import (
    WorkflowFileError,
    add_user_files_to_workflow,
    delete_workflow_file,
    ensure_workflow_files_table,
    get_workflow_file,
    list_user_platform_files,
    list_workflow_files,
    register_agent_files,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _raise(exc: WorkflowError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _raise_file(exc: WorkflowFileError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_SSE_PAD = ":" + (" " * 2048) + "\n"
_HEARTBEAT_S = 2.0


def _sse(payload: dict) -> str:
    # Padding forces proxies/uvicorn to flush so Thinking/tools appear immediately.
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n{_SSE_PAD}\n"


def _iter_sse_queue(queue: Queue[dict | None], stop: Event):
    def heartbeat() -> None:
        while not stop.wait(_HEARTBEAT_S):
            queue.put({"type": "heartbeat"})

    Thread(target=heartbeat, daemon=True).start()
    while True:
        item = queue.get()
        if item is None:
            stop.set()
            break
        yield _sse(item)


def _workflow_stream(action, *, user_id: str = ""):
    from app.services.workflows.cursor_tools import clear_tool_context, set_tool_context

    queue: Queue[dict | None] = Queue()
    stop = Event()
    run_id = tool_bridge.new_run_id() if user_id else ""

    def emit(event_type: str, text: str = "", extra: dict | None = None) -> None:
        payload = {"type": event_type}
        if text:
            payload["text"] = text
        if extra:
            payload.update(extra)
        queue.put(payload)

    def run() -> None:
        db = SessionLocal()
        if run_id:
            tool_bridge.register_run(run_id, user_id)
            set_tool_context(run_id, user_id)
            queue.put({"type": "run", "run_id": run_id})
        try:
            record = action(db, emit)
            queue.put({"type": "workflow", "workflow": record.model_dump(mode="json")})
        except WorkflowError as exc:
            queue.put({"type": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            queue.put({"type": "error", "message": str(exc)})
        finally:
            if run_id:
                clear_tool_context()
                tool_bridge.unregister_run(run_id)
            db.close()
            stop.set()
            queue.put(None)

    Thread(target=run, daemon=True).start()
    yield from _iter_sse_queue(queue, stop)


def _record_and_emit(payload: dict, events: list[dict], emit) -> None:
    if isinstance(payload, dict):
        events.append(payload)
    emit(payload)


def _agent_run_stream(
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    source: str = "chat",
    trigger_id: str = "",
    evidence: str = "",
):
    queue: Queue[dict | None] = Queue()
    stop = Event()
    run_id = tool_bridge.new_run_id()
    tool_bridge.register_run(run_id, user_id)

    def emit(payload: dict) -> None:
        queue.put(payload)

    def run() -> None:
        db = SessionLocal()
        history_id = ""
        status = "error"
        answer = ""
        events: list[dict] = []
        try:
            history = start_agent_run(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                message=message,
                source=source,
                trigger_id=trigger_id,
                evidence=evidence,
            )
            history_id = history.id
            emit({"type": "run", "run_id": run_id})
            result = run_agent_task(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                message=message,
                emit=lambda payload: _record_and_emit(payload, events, emit),
                run_id=run_id,
                history_id=history_id,
            )
            status = "ok"
            answer = answer_from_result(result)
            queue.put({"type": "done", "result": result})
        except AgentRuntimeError as exc:
            answer = str(exc)
            events.append({"type": "error", "message": str(exc)})
            queue.put({"type": "error", "message": str(exc)})
        except WorkflowError as exc:
            answer = exc.message
            events.append({"type": "error", "message": exc.message})
            queue.put({"type": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            answer = str(exc)
            events.append({"type": "error", "message": str(exc)})
            queue.put({"type": "error", "message": str(exc)})
        finally:
            if history_id:
                try:
                    db.rollback()
                    finish_agent_run(
                        db,
                        run_id=history_id,
                        status=status,
                        answer=answer,
                        events=events,
                        message=message,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to persist agent run history id=%s", history_id)
            tool_bridge.unregister_run(run_id)
            db.close()
            stop.set()
            queue.put(None)

    Thread(target=run, daemon=True).start()
    yield from _iter_sse_queue(queue, stop)


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


@router.get("/board", response_model=WorkflowBoard)
async def read_workflow_board(
    window_from: str = "",
    window_to: str = "",
    workflow_id: str = "",
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowBoard:
    return get_workflow_board(
        db,
        user_id=auth.user_id,
        window_from=window_from,
        window_to=window_to,
        workflow_id=workflow_id,
    )


@router.get("/files", response_model=PlatformFilesResponse)
async def read_platform_files(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlatformFilesResponse:
    return list_user_platform_files(db, user_id=auth.user_id)


@router.post("/{workflow_id}/agent-runs/stream")
async def run_workflow_agent_stream(
    workflow_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    body = await request.json()
    message = str((body or {}).get("message") or "").strip()
    source = str((body or {}).get("source") or "chat").strip() or "chat"
    trigger_id = str((body or {}).get("trigger_id") or "").strip()
    evidence = str((body or {}).get("evidence") or "").strip()
    return StreamingResponse(
        _agent_run_stream(
            user_id=auth.user_id,
            workflow_id=workflow_id,
            message=message,
            source=source,
            trigger_id=trigger_id,
            evidence=evidence,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent-runs/{run_id}/tool-results")
async def submit_agent_tool_result(
    run_id: str,
    body: AgentToolResultSubmit,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, bool]:
    try:
        tool_bridge.submit_result(
            run_id=run_id,
            request_id=body.request_id,
            user_id=auth.user_id,
            ok=body.ok,
            result=body.result,
            error=body.error,
        )
    except ToolBridgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True}


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


@router.post("/{workflow_id}/schedule-draft", response_model=ScheduleDraftOut)
def create_schedule_draft(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScheduleDraftOut:
    try:
        return propose_schedule_draft(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.get("/{workflow_id}/runs", response_model=list[AgentRunOut])
def read_agent_runs(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AgentRunOut]:
    try:
        return list_agent_runs(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/runs/local", response_model=AgentRunOut)
def create_local_agent_run(
    workflow_id: str,
    body: AgentRunCreate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunOut:
    try:
        row = start_agent_run(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            message=body.message,
            source=body.source,
            trigger_id=body.trigger_id,
            evidence=body.evidence,
        )
        return get_agent_run(db, user_id=auth.user_id, workflow_id=workflow_id, run_id=row.id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.patch("/{workflow_id}/runs/{run_id}/events", response_model=AgentRunOut)
def update_local_agent_run_events(
    workflow_id: str,
    run_id: str,
    body: AgentRunEventsUpdate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunOut:
    try:
        get_agent_run(db, user_id=auth.user_id, workflow_id=workflow_id, run_id=run_id)
        save_run_events(db, run_id=run_id, events=body.events)
        return get_agent_run(db, user_id=auth.user_id, workflow_id=workflow_id, run_id=run_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/runs/{run_id}/finish", response_model=AgentRunOut)
def finish_local_agent_run(
    workflow_id: str,
    run_id: str,
    body: AgentRunFinish,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunOut:
    try:
        get_agent_run(db, user_id=auth.user_id, workflow_id=workflow_id, run_id=run_id)
        finish_agent_run(
            db,
            run_id=run_id,
            status=body.status,
            answer=body.answer,
            events=body.events,
            message=body.message,
        )
        return get_agent_run(db, user_id=auth.user_id, workflow_id=workflow_id, run_id=run_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.get("/{workflow_id}/runs/{run_id}", response_model=AgentRunOut)
def read_agent_run(
    workflow_id: str,
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunOut:
    try:
        return get_agent_run(db, user_id=auth.user_id, workflow_id=workflow_id, run_id=run_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.get("/{workflow_id}/files", response_model=WorkflowFilesResponse)
async def read_workflow_files(
    workflow_id: str,
    run_id: str = "",
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowFilesResponse:
    try:
        row = ensure_workflow_files_table(db, user_id=auth.user_id, workflow_id=workflow_id)
        return list_workflow_files(db, row=row, run_id=run_id)
    except WorkflowFileError as exc:
        _raise_file(exc)
        raise


@router.post("/{workflow_id}/files", response_model=WorkflowFilesResponse)
async def upload_workflow_files(
    workflow_id: str,
    files: list[UploadFile] = File(default=[]),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowFilesResponse:
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        raw = await upload.read()
        payloads.append((upload.filename or "file", raw))
    try:
        row = ensure_workflow_files_table(db, user_id=auth.user_id, workflow_id=workflow_id)
        add_user_files_to_workflow(db, row=row, files=payloads, origin="user_upload")
        db.commit()
        db.refresh(row)
        return list_workflow_files(db, row=row)
    except WorkflowFileError as exc:
        db.rollback()
        _raise_file(exc)
        raise


@router.post("/{workflow_id}/runs/{run_id}/files", response_model=WorkflowFilesResponse)
async def upload_workflow_run_files(
    workflow_id: str,
    run_id: str,
    files: list[UploadFile] = File(default=[]),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowFilesResponse:
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        raw = await upload.read()
        payloads.append((upload.filename or "file", raw))
    try:
        row = ensure_workflow_files_table(db, user_id=auth.user_id, workflow_id=workflow_id)
        register_agent_files(db, row=row, files=payloads, run_id=run_id)
        db.commit()
        return list_workflow_files(db, row=row, run_id=run_id)
    except WorkflowFileError as exc:
        db.rollback()
        _raise_file(exc)
        raise


@router.get("/{workflow_id}/files/{file_id}/text")
async def read_workflow_file_text(
    workflow_id: str,
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        row = ensure_workflow_files_table(db, user_id=auth.user_id, workflow_id=workflow_id)
        item = get_workflow_file(db, row=row, file_id=file_id)
        return {"text": item.extracted_text or "", "summary": item.summary or ""}
    except WorkflowFileError as exc:
        _raise_file(exc)
        raise


@router.get("/{workflow_id}/files/{file_id}/download")
async def download_workflow_file(
    workflow_id: str,
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        row = ensure_workflow_files_table(db, user_id=auth.user_id, workflow_id=workflow_id)
        item = get_workflow_file(db, row=row, file_id=file_id)
    except WorkflowFileError as exc:
        _raise_file(exc)
        raise
    filename = item.filename or "file"
    encoded = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    return Response(
        content=item.content or b"",
        media_type=item.mime_type or "application/octet-stream",
        headers=headers,
    )


@router.delete("/{workflow_id}/files/{file_id}")
async def remove_workflow_file(
    workflow_id: str,
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    try:
        row = ensure_workflow_files_table(db, user_id=auth.user_id, workflow_id=workflow_id)
        delete_workflow_file(db, row=row, file_id=file_id)
        db.commit()
    except WorkflowFileError as exc:
        db.rollback()
        _raise_file(exc)
        raise
    return {"ok": True}


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


@router.post("/{workflow_id}/stop-auto-run", response_model=AutoRunStopResult)
async def stop_workflow_auto_run(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutoRunStopResult:
    try:
        return stop_auto_run(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/resume-auto-run", response_model=AutoRunStopResult)
async def resume_workflow_auto_run(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutoRunStopResult:
    try:
        return resume_auto_run(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/demo", response_model=WorkflowSchema)
async def demo_workflow_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return demo_workflow(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/demo/local-finish", response_model=WorkflowSchema)
async def finish_local_demo_workflow_endpoint(
    workflow_id: str,
    body: LocalDemoFinish,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return finish_local_demo_workflow(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            answer=body.answer,
            events=body.events,
        )
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/design/local-context")
async def local_design_context_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        prompt = build_local_design_prompt(db, user_id=auth.user_id, workflow_id=workflow_id)
        return {"prompt": prompt}
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/design/local-finish", response_model=WorkflowSchema)
async def finish_local_design_workflow_endpoint(
    workflow_id: str,
    body: LocalDemoFinish,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return finish_local_design_workflow(
            db,
            user_id=auth.user_id,
            workflow_id=workflow_id,
            answer=body.answer,
            events=body.events,
        )
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/demo/stream")
async def demo_workflow_stream_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    user_id = auth.user_id
    return StreamingResponse(
        _workflow_stream(
            lambda db, emit: demo_workflow(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                on_event=emit,
            ),
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


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
            ),
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
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
            ),
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
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
            ),
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
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


@router.post("/{workflow_id}/publish", response_model=WorkflowSchema)
async def publish_workflow_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return publish_workflow(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/kpi/generate/stream")
async def generate_workflow_kpi_stream_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    user_id = auth.user_id
    return StreamingResponse(
        _workflow_stream(
            lambda db, emit: generate_agent_kpi(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                on_event=emit,
            ),
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/{workflow_id}/kpi", response_model=AgentKpiSchema)
async def read_workflow_kpi(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentKpiSchema:
    try:
        return get_agent_kpi(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise


@router.post("/{workflow_id}/kpi/confirm", response_model=WorkflowSchema)
async def confirm_workflow_kpi_endpoint(
    workflow_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowSchema:
    try:
        return confirm_agent_kpi(db, user_id=auth.user_id, workflow_id=workflow_id)
    except WorkflowError as exc:
        _raise(exc)
        raise

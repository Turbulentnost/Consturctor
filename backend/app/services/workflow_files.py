from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.workflow import Workflow, WorkflowFile
from app.schemas.workflow import (
    AttachmentMetaSchema,
    PlatformFileSchema,
    PlatformFilesResponse,
    WorkflowFileSchema,
    WorkflowFilesResponse,
)
from app.services.triggers.service import workflow_is_deleted
from app.services.workflows.document import DocumentError, compose_document, load_attachment_bytes

SUMMARY_CHARS = 700
PREVIEW_CHARS = 500
SOURCE_USER = "user"
SOURCE_AGENT = "agent"
SCOPE_KNOWLEDGE = "knowledge"
SCOPE_RUN_OUTPUT = "run_output"
# Temporary per-run inputs the user attaches on a given run. Kept out of the
# permanent knowledge base and tied to a specific run_id.
SCOPE_RUN_ATTACHMENT = "run_attachment"
ORIGIN_KEEP_KNOWLEDGE = "keep_knowledge"
ORIGIN_RUN_ATTACHMENT = "run_attachment"


class WorkflowFileError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PreparedWorkflowFile:
    file_id: str
    original_name: str
    raw: bytes
    loaded: dict[str, Any]
    sha256: str


def prepare_workflow_file(original_name: str, raw: bytes) -> PreparedWorkflowFile:
    try:
        loaded = load_attachment_bytes(original_name, raw)
    except DocumentError as exc:
        raise WorkflowFileError(str(exc)) from exc
    return PreparedWorkflowFile(
        file_id=str(uuid4()),
        original_name=Path(original_name or "file").name or "file",
        raw=raw,
        loaded=loaded,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def prepare_workflow_files(files: list[tuple[str, bytes]]) -> list[PreparedWorkflowFile]:
    return [prepare_workflow_file(name, raw) for name, raw in files]


def _find_existing_file(
    db: Session,
    *,
    workflow_id: str,
    scope: str,
    sha256: str,
    run_id: str,
) -> WorkflowFile | None:
    """Return a stored file with identical content in the same bucket, if any.

    Dedup key is (workflow_id, scope, sha256) plus run_id for run-scoped files.
    This stops the same document from being written to the DB again on every
    run (for example when the agent calls keepKnowledgeFile repeatedly).
    """
    if not sha256:
        return None
    query = db.query(WorkflowFile).filter(
        WorkflowFile.workflow_id == workflow_id,
        WorkflowFile.scope == scope,
        WorkflowFile.sha256 == sha256,
    )
    if (run_id or "").strip():
        query = query.filter(WorkflowFile.run_id == (run_id or "").strip())
    return query.first()


def save_prepared_files(
    db: Session,
    *,
    workflow_id: str,
    prepared: list[PreparedWorkflowFile],
    source: str = SOURCE_USER,
    scope: str = SCOPE_KNOWLEDGE,
    run_id: str = "",
    origin: str = "",
) -> list[WorkflowFile]:
    rows: list[WorkflowFile] = []
    scope_norm = (scope or SCOPE_KNOWLEDGE).strip() or SCOPE_KNOWLEDGE
    run_norm = (run_id or "").strip()
    for item in prepared:
        existing = _find_existing_file(
            db,
            workflow_id=workflow_id,
            scope=scope_norm,
            sha256=item.sha256,
            run_id=run_norm,
        )
        if existing is not None:
            # Identical content already stored in this bucket: reuse it instead
            # of inserting a duplicate blob.
            rows.append(existing)
            continue
        loaded = dict(item.loaded)
        text = str(loaded.get("text") or "").strip()
        row = WorkflowFile(
            id=item.file_id,
            workflow_id=workflow_id,
            run_id=run_norm,
            source=(source or SOURCE_USER).strip() or SOURCE_USER,
            scope=scope_norm,
            origin=(origin or "").strip(),
            filename=str(loaded.get("name") or item.original_name or "file"),
            mime_type=str(loaded.get("mime_type") or _guess_mime(item.original_name)),
            kind=str(loaded.get("kind") or "text"),
            size=len(item.raw),
            sha256=item.sha256,
            content=item.raw,
            extracted_text=text,
            summary=_summarize_text(str(loaded.get("name") or item.original_name), text),
            file_metadata={
                "original_name": item.original_name,
                "stored_name": item.file_id,
            },
        )
        db.add(row)
        rows.append(row)
    return rows


def add_user_files_to_workflow(
    db: Session,
    *,
    row: Workflow,
    files: list[tuple[str, bytes]],
    origin: str,
) -> tuple[list[str], list[PreparedWorkflowFile]]:
    prepared = prepare_workflow_files(files)
    if not prepared:
        return [], []
    save_prepared_files(
        db,
        workflow_id=row.id,
        prepared=prepared,
        source=SOURCE_USER,
        scope=SCOPE_KNOWLEDGE,
        origin=origin,
    )
    db.flush()
    _refresh_workflow_document_from_files(db, row)
    return [str(item.loaded.get("name") or item.original_name) for item in prepared], prepared


def register_run_attachments(
    db: Session,
    *,
    row: Workflow,
    files: list[tuple[str, bytes]],
    run_id: str = "",
    origin: str = ORIGIN_RUN_ATTACHMENT,
) -> list[WorkflowFile]:
    """Store temporary per-run user attachments (not permanent knowledge)."""
    prepared = prepare_workflow_files(files)
    if not prepared:
        return []
    rows = save_prepared_files(
        db,
        workflow_id=row.id,
        prepared=prepared,
        source=SOURCE_USER,
        scope=SCOPE_RUN_ATTACHMENT,
        run_id=run_id,
        origin=origin,
    )
    db.flush()
    return rows


def register_agent_files(
    db: Session,
    *,
    row: Workflow,
    files: list[tuple[str, bytes]],
    run_id: str = "",
    origin: str = "sdk_output",
) -> list[WorkflowFile]:
    prepared = prepare_workflow_files(files)
    if not prepared:
        return []
    rows = save_prepared_files(
        db,
        workflow_id=row.id,
        prepared=prepared,
        source=SOURCE_AGENT,
        scope=SCOPE_RUN_OUTPUT,
        run_id=run_id,
        origin=origin,
    )
    db.flush()
    return rows


def list_user_platform_files(db: Session, *, user_id: str) -> PlatformFilesResponse:
    rows = (
        db.query(
            WorkflowFile.id,
            WorkflowFile.workflow_id,
            WorkflowFile.run_id,
            WorkflowFile.source,
            WorkflowFile.scope,
            WorkflowFile.origin,
            WorkflowFile.filename,
            WorkflowFile.mime_type,
            WorkflowFile.kind,
            WorkflowFile.size,
            WorkflowFile.sha256,
            WorkflowFile.summary,
            WorkflowFile.created_at,
            WorkflowFile.updated_at,
            Workflow.title,
            Workflow.phase,
            Workflow.local_run,
        )
        .join(Workflow, Workflow.id == WorkflowFile.workflow_id)
        .filter(Workflow.user_id == user_id)
        .order_by(WorkflowFile.created_at.desc(), WorkflowFile.filename.asc())
        .all()
    )
    files: list[PlatformFileSchema] = []
    for item in rows:
        workflow = type("W", (), {"phase": item.phase, "local_run": item.local_run})()
        if workflow_is_deleted(workflow):
            continue
        files.append(
            PlatformFileSchema(
                id=item.id,
                workflow_id=item.workflow_id,
                run_id=item.run_id or "",
                source=item.source or SOURCE_USER,
                scope=item.scope or SCOPE_KNOWLEDGE,
                origin=item.origin or "",
                filename=item.filename or "file",
                mime_type=item.mime_type or "",
                kind=item.kind or "text",
                size=int(item.size or 0),
                sha256=item.sha256 or "",
                summary=item.summary or "",
                text_preview="",
                created_at=_iso(item.created_at),
                updated_at=_iso(item.updated_at),
                agent_title=item.title or "Агент",
            )
        )
    return PlatformFilesResponse(files=files)


def list_workflow_files(
    db: Session,
    *,
    row: Workflow,
    run_id: str = "",
) -> WorkflowFilesResponse:
    rows = (
        db.query(WorkflowFile)
        .filter(WorkflowFile.workflow_id == row.id)
        .order_by(WorkflowFile.created_at.asc(), WorkflowFile.filename.asc())
        .all()
    )
    requested_run = (run_id or "").strip()
    user_files: list[WorkflowFileSchema] = []
    agent_files: list[WorkflowFileSchema] = []
    run_attachments: list[WorkflowFileSchema] = []
    for item in rows:
        schema = _to_file_schema(item)
        if item.source == SOURCE_AGENT:
            if requested_run and item.run_id != requested_run:
                continue
            agent_files.append(schema)
        elif item.scope == SCOPE_RUN_ATTACHMENT:
            if requested_run and item.run_id != requested_run:
                continue
            run_attachments.append(schema)
        elif item.scope == SCOPE_KNOWLEDGE:
            user_files.append(schema)
    return WorkflowFilesResponse(
        user_files=user_files,
        agent_files=agent_files,
        run_attachments=run_attachments,
    )


def get_workflow_file(
    db: Session,
    *,
    row: Workflow,
    file_id: str,
) -> WorkflowFile:
    item = (
        db.query(WorkflowFile)
        .filter(WorkflowFile.workflow_id == row.id, WorkflowFile.id == file_id)
        .first()
    )
    if item is None:
        raise WorkflowFileError("Файл не найден", status_code=404)
    return item


def delete_workflow_file(db: Session, *, row: Workflow, file_id: str) -> None:
    item = get_workflow_file(db, row=row, file_id=file_id)
    if item.source != SOURCE_USER:
        raise WorkflowFileError("Можно удалить только файл пользователя")
    db.delete(item)
    _refresh_workflow_document_from_files(db, row)


def attachment_meta_for_workflow(db: Session, row: Workflow) -> list[AttachmentMetaSchema]:
    rows = (
        db.query(WorkflowFile)
        .filter(
            WorkflowFile.workflow_id == row.id,
            WorkflowFile.source == SOURCE_USER,
            WorkflowFile.scope == SCOPE_KNOWLEDGE,
        )
        .order_by(WorkflowFile.created_at.asc(), WorkflowFile.filename.asc())
        .all()
    )
    if not rows:
        return [
            AttachmentMetaSchema.model_validate(x)
            for x in (row.attachments_meta or [])
            if isinstance(x, dict)
        ]
    return [
        AttachmentMetaSchema(
            name=item.filename,
            kind=item.kind,
            mime_type=item.mime_type,
            stored_name=item.id,
            text_preview=(item.extracted_text or "")[:PREVIEW_CHARS],
        )
        for item in rows
    ]


def payload_attachments_for_workflow(db: Session, row: Workflow) -> list[dict[str, Any]]:
    rows = (
        db.query(WorkflowFile)
        .filter(
            WorkflowFile.workflow_id == row.id,
            WorkflowFile.source == SOURCE_USER,
            WorkflowFile.scope == SCOPE_KNOWLEDGE,
        )
        .order_by(WorkflowFile.created_at.asc(), WorkflowFile.filename.asc())
        .all()
    )
    if not rows:
        return []
    payloads: list[dict[str, Any]] = []
    for item in rows:
        payload: dict[str, Any] = {
            "name": item.filename,
            "text": item.extracted_text or "",
            "kind": item.kind,
            "mime_type": item.mime_type,
            "stored_name": item.id,
        }
        if item.kind == "image":
            payload["data_b64"] = base64.b64encode(item.content or b"").decode("ascii")
        else:
            payload["data_b64"] = ""
        payloads.append(payload)
    return payloads


def ensure_workflow_files_table(db: Session, *, user_id: str, workflow_id: str) -> Workflow:
    row = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user_id).first()
    if row is None:
        raise WorkflowFileError("Workflow не найден", status_code=404)
    if workflow_is_deleted(row) or str(row.phase or "") == "deleted":
        raise WorkflowFileError("Агент удалён", status_code=404)
    return row


def _refresh_workflow_document_from_files(db: Session, row: Workflow) -> None:
    payloads = payload_attachments_for_workflow(db, row)
    if not payloads:
        return
    document_name, document_text = compose_document(payloads, notes=row.notes or "")
    row.document_name = document_name or row.document_name
    row.document_text = document_text
    row.attachments_meta = [item.model_dump() for item in attachment_meta_for_workflow(db, row)]


def _to_file_schema(item: WorkflowFile) -> WorkflowFileSchema:
    return WorkflowFileSchema(
        id=item.id,
        workflow_id=item.workflow_id,
        run_id=item.run_id or "",
        source=item.source or SOURCE_USER,
        scope=item.scope or SCOPE_KNOWLEDGE,
        origin=item.origin or "",
        filename=item.filename or "file",
        mime_type=item.mime_type or "",
        kind=item.kind or "text",
        size=int(item.size or 0),
        sha256=item.sha256 or "",
        summary=item.summary or "",
        text_preview=(item.extracted_text or "")[:PREVIEW_CHARS],
        created_at=_iso(item.created_at),
        updated_at=_iso(item.updated_at),
    )


def _summarize_text(name: str, text: str) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return f"{name}: файл без извлечённого текста"
    return clean[:SUMMARY_CHARS]


def _guess_mime(name: str) -> str:
    return mimetypes.guess_type(name or "")[0] or "application/octet-stream"


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)

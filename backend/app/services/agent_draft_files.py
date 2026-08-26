from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.regulation import AgentDraft, AgentDraftFile
from app.models.workflow import Workflow
from app.schemas.regulation import AgentDraftFileItem, AgentDraftFilesResponse
from app.services.workflow_files import (
    SOURCE_USER,
    SCOPE_KNOWLEDGE,
    WorkflowFileError,
    prepare_workflow_files,
    save_prepared_files,
)


def add_files_to_draft(
    db: Session,
    *,
    draft: AgentDraft,
    files: list[tuple[str, bytes]],
    function_id: str = "",
) -> AgentDraftFilesResponse:
    prepared = prepare_workflow_files(files)
    for item in prepared:
        loaded = dict(item.loaded)
        text = str(loaded.get("text") or "").strip()
        db.add(
            AgentDraftFile(
                id=item.file_id,
                draft_id=draft.id,
                user_id=draft.user_id,
                function_id=(function_id or "").strip(),
                filename=str(loaded.get("name") or item.original_name or "file"),
                mime_type=str(loaded.get("mime_type") or ""),
                kind=str(loaded.get("kind") or "text"),
                size=len(item.raw),
                sha256=item.sha256,
                content=item.raw,
                extracted_text=text,
                summary=_summarize(str(loaded.get("name") or item.original_name), text),
                file_metadata={
                    "original_name": item.original_name,
                    "stored_name": item.file_id,
                },
            )
        )
    db.flush()
    return list_draft_files(db, draft=draft)


def list_draft_files(db: Session, *, draft: AgentDraft) -> AgentDraftFilesResponse:
    rows = (
        db.query(AgentDraftFile)
        .filter(AgentDraftFile.draft_id == draft.id, AgentDraftFile.user_id == draft.user_id)
        .order_by(AgentDraftFile.created_at.asc(), AgentDraftFile.filename.asc())
        .all()
    )
    return AgentDraftFilesResponse(files=[_to_schema(row) for row in rows])


def copy_draft_files_to_workflow(
    db: Session,
    *,
    draft: AgentDraft,
    workflow: Workflow,
) -> int:
    rows = (
        db.query(AgentDraftFile)
        .filter(AgentDraftFile.draft_id == draft.id, AgentDraftFile.user_id == draft.user_id)
        .order_by(AgentDraftFile.created_at.asc(), AgentDraftFile.filename.asc())
        .all()
    )
    if not rows:
        return 0
    prepared = prepare_workflow_files([(row.filename, bytes(row.content or b"")) for row in rows])
    saved = save_prepared_files(
        db,
        workflow_id=workflow.id,
        prepared=prepared,
        source=SOURCE_USER,
        scope=SCOPE_KNOWLEDGE,
        origin="draft_readiness",
    )
    by_name = {row.filename: row for row in rows}
    for item in saved:
        source = by_name.get(item.filename)
        if source is not None:
            metadata = dict(item.file_metadata or {})
            metadata["draft_id"] = draft.id
            metadata["draft_file_id"] = source.id
            metadata["function_id"] = source.function_id
            item.file_metadata = metadata
            db.add(item)
    return len(saved)


def _to_schema(row: AgentDraftFile) -> AgentDraftFileItem:
    return AgentDraftFileItem(
        fileId=row.id,
        draftId=row.draft_id,
        functionId=row.function_id or "",
        filename=row.filename or "file",
        mimeType=row.mime_type or "",
        kind=row.kind or "text",
        size=int(row.size or 0),
        sha256=row.sha256 or "",
        summary=row.summary or "",
        textPreview=(row.extracted_text or "")[:500],
        createdAt=row.created_at,
    )


def _summarize(name: str, text: str) -> str:
    clean = " ".join((text or "").split())
    if clean:
        return clean[:700]
    return f"Файл {name or 'file'} прикреплен к уточнению регламента."


__all__ = [
    "WorkflowFileError",
    "add_files_to_draft",
    "copy_draft_files_to_workflow",
    "list_draft_files",
]

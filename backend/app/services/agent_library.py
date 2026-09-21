"""Published agents from all users — catalog cards and adoption (clone)."""

from __future__ import annotations

import copy
import logging
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import AppUser
from app.models.workflow import Workflow, WorkflowFile
from app.services.triggers.service import sync_recurring_triggers_from_draft, workflow_is_deleted
from app.services.workflows.board import _agent_description

logger = logging.getLogger(__name__)

PERSONAL_AGENT_PREFIX = "personal-agent:"


class AgentLibraryError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _is_published_row(row: Workflow) -> bool:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    status = str(local.get("status") or "").strip().casefold()
    if local.get("published") is True:
        return True
    if status in {"published", "active", "ready"}:
        return True
    return (row.phase or "").strip().casefold() == "done"


def _is_catalog_workflow(row: Workflow) -> bool:
    if (row.id or "").startswith(PERSONAL_AGENT_PREFIX):
        return False
    if workflow_is_deleted(row):
        return False
    if (row.phase or "").strip().casefold() == "deleted":
        return False
    local = row.local_run if isinstance(row.local_run, dict) else {}
    if local.get("unformed"):
        return False
    if local.get("kind") == "draft":
        return False
    return _is_published_row(row)


def _tools_from_row(row: Workflow) -> list[str]:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    raw = local.get("tools")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()][:12]
    plan = row.plan_json if isinstance(row.plan_json, dict) else {}
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    rt_tools = runtime.get("tools")
    if isinstance(rt_tools, list):
        return [str(item).strip() for item in rt_tools if str(item).strip()][:12]
    return []


def _goal_from_row(row: Workflow) -> str:
    plan = row.plan_json if isinstance(row.plan_json, dict) else {}
    return str(plan.get("goal") or "").strip()


def _library_source_id(row: Workflow) -> str:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    return str(local.get("library_source_id") or "").strip()


def _purpose_from_row(row: Workflow) -> str:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    raw = str(local.get("purpose") or local.get("agent_purpose") or "").strip().casefold()
    if raw in {"positional", "position", "role", "долностной", "positionally"}:
        return "positional"
    if (row.id or "").startswith(PERSONAL_AGENT_PREFIX):
        return "positional"
    return "functional"


def _card_from_row(row: Workflow, *, owner_id: str = "", owner_fio: str = "") -> dict:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    return {
        "type": "agent_card",
        "workflow_id": row.id,
        "title": (row.title or "ИИ-агент").strip(),
        "description": _agent_description(row),
        "goal": _goal_from_row(row),
        "trigger_summary": str(local.get("trigger_summary") or "").strip(),
        "trigger_kind": str(local.get("trigger_kind") or "").strip(),
        "status": str(local.get("status") or "published"),
        "phase": row.phase or "done",
        "tools": _tools_from_row(row),
        "owner_id": owner_id,
        "owner_fio": owner_fio,
        "purpose": _purpose_from_row(row),
    }


def _owner_map(db: Session, user_ids: list[str]) -> dict[str, AppUser]:
    unique = [item for item in dict.fromkeys(user_ids) if item]
    if not unique:
        return {}
    rows = db.query(AppUser).filter(AppUser.id.in_(unique)).all()
    return {row.id: row for row in rows}


def _adopted_index(db: Session, *, user_id: str) -> dict[str, Workflow]:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.phase == "done")
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    out: dict[str, Workflow] = {}
    for row in rows:
        if workflow_is_deleted(row):
            continue
        source = _library_source_id(row)
        if source and source not in out:
            out[source] = row
    return out


def list_agent_library(db: Session, *, user_id: str) -> dict:
    rows = (
        db.query(Workflow)
        .filter(Workflow.phase != "deleted")
        .order_by(Workflow.updated_at.desc())
        .limit(1200)
        .all()
    )
    catalog_rows = [row for row in rows if _is_catalog_workflow(row)]
    owners = _owner_map(db, [row.user_id for row in catalog_rows])
    adopted_by_source = _adopted_index(db, user_id=user_id)

    catalog: list[dict] = []
    for row in catalog_rows:
        owner = owners.get(row.user_id)
        owner_fio = (owner.fio if owner else "").strip()
        adopted = adopted_by_source.get(row.id)
        already_added = adopted is not None or row.user_id == user_id
        if already_added:
            continue
        card = _card_from_row(row, owner_id=row.user_id, owner_fio=owner_fio)
        catalog.append(
            {
                **card,
                "already_added": False,
                "adopted_workflow_id": "",
            }
        )

    adopted: list[dict] = []
    for source_id, row in adopted_by_source.items():
        src = db.get(Workflow, source_id)
        owner = owners.get(src.user_id) if src else None
        owner_fio = (owner.fio if owner else "").strip()
        card = _card_from_row(row, owner_id=user_id, owner_fio=owner_fio)
        if src:
            card["description"] = card["description"] or _agent_description(src)
            card["goal"] = card["goal"] or _goal_from_row(src)
        adopted.append({**card, "already_added": True, "adopted_workflow_id": row.id})

    own_published = [row for row in catalog_rows if row.user_id == user_id]
    for row in own_published:
        if row.id in adopted_by_source:
            continue
        card = _card_from_row(row, owner_id=user_id, owner_fio=(owners.get(user_id).fio if owners.get(user_id) else ""))
        adopted.append({**card, "already_added": True, "adopted_workflow_id": row.id})

    return {"catalog": catalog, "adopted": adopted}


def _copy_files(db: Session, *, src_id: str, dst_id: str) -> int:
    count = 0
    existing = {
        (item.filename, item.scope or "")
        for item in db.query(WorkflowFile).filter(WorkflowFile.workflow_id == dst_id).all()
    }
    for item in db.query(WorkflowFile).filter(WorkflowFile.workflow_id == src_id).all():
        key = (item.filename, item.scope or "")
        if key in existing:
            continue
        db.add(
            WorkflowFile(
                id=str(uuid4()),
                workflow_id=dst_id,
                run_id=item.run_id or "",
                source=item.source or "user",
                scope=item.scope or "knowledge",
                origin=item.origin or "",
                filename=item.filename,
                mime_type=item.mime_type or "",
                kind=item.kind or "text",
                size=item.size or 0,
                sha256=item.sha256 or "",
                content=item.content,
                extracted_text=item.extracted_text or "",
                summary=item.summary or "",
                file_metadata=copy.deepcopy(item.file_metadata or {}),
            )
        )
        count += 1
    return count


def adopt_library_agent(db: Session, *, user_id: str, source_workflow_id: str) -> dict:
    source_id = (source_workflow_id or "").strip()
    if not source_id:
        raise AgentLibraryError("Не указан агент", status_code=400)

    src = db.get(Workflow, source_id)
    if src is None or not _is_catalog_workflow(src):
        raise AgentLibraryError("Агент не найден в библиотеке", status_code=404)

    if src.user_id == user_id:
        owners = _owner_map(db, [user_id])
        owner_fio = (owners.get(user_id).fio if owners.get(user_id) else "").strip()
        card = _card_from_row(src, owner_id=user_id, owner_fio=owner_fio)
        return {"ok": True, "workflow_id": src.id, "title": card["title"], "card": card}

    adopted = _adopted_index(db, user_id=user_id)
    if source_id in adopted:
        row = adopted[source_id]
        card = _card_from_row(row, owner_id=user_id, owner_fio="")
        return {"ok": True, "workflow_id": row.id, "title": card["title"], "card": card}

    title = (src.title or "ИИ-агент").strip()
    hit = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.title == title, Workflow.phase == "done")
        .order_by(Workflow.updated_at.desc())
        .first()
    )
    if hit is not None and not workflow_is_deleted(hit) and _library_source_id(hit) == source_id:
        card = _card_from_row(hit, owner_id=user_id, owner_fio="")
        return {"ok": True, "workflow_id": hit.id, "title": card["title"], "card": card}

    workflow_id = str(uuid4())
    local = copy.deepcopy(src.local_run or {})
    if not isinstance(local, dict):
        local = {}
    local["library_source_id"] = source_id
    local["library_adopted_at"] = local.get("library_adopted_at") or ""
    local["published"] = True
    local["status"] = local.get("status") or "published"
    local["phase"] = "done"

    row = Workflow(
        id=workflow_id,
        user_id=user_id,
        title=title,
        phase="done",
        notes=src.notes or "",
        document_name=src.document_name or "",
        document_text=src.document_text or "",
        plan_json=copy.deepcopy(src.plan_json or {}),
        attachments_meta=copy.deepcopy(src.attachments_meta or []),
        local_run=local,
        last_result=src.last_result or "",
    )
    db.add(row)
    db.flush()
    _copy_files(db, src_id=src.id, dst_id=workflow_id)
    try:
        sync_recurring_triggers_from_draft(db, user_id=user_id, workflow=row)
    except Exception:  # noqa: BLE001
        logger.exception("library adopt: trigger sync failed wf=%s", workflow_id)
    flag_modified(row, "local_run")
    db.commit()
    db.refresh(row)
    card = _card_from_row(row, owner_id=user_id, owner_fio="")
    logger.info("Agent library adopt user=%s source=%s -> %s", user_id, source_id, workflow_id)
    return {"ok": True, "workflow_id": workflow_id, "title": card["title"], "card": card}

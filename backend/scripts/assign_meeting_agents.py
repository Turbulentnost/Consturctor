"""Copy published RK / SD meeting agents from one user to another (full workflow clone).

Usage (from backend/):
  py -3.12 scripts/assign_meeting_agents.py --from-fio "Жалыбин Максим Дмитриевич" --to-fio "Ильченко Екатерина Александровна"
  py -3.12 scripts/assign_meeting_agents.py --from-user 885434321E82D8094E17EAE8D9276D36 --to-user A2DCC949FEDEC70D40318ABA83C618F4
  py -3.12 scripts/assign_meeting_agents.py --dry-run
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal, init_db
from app.models.user import AppUser
from app.models.workflow import Workflow, WorkflowFile
from app.services.triggers.service import sync_recurring_triggers_from_draft
from app.services.workflows.meeting_agent_config import (
    apply_meeting_agent_config,
    apply_meeting_plan_runtime,
)
from app.services.workflows.rk_meeting_playbook import is_rk_meeting_agent, rk_local_playbook
from app.services.workflows.sd_meeting_playbook import is_sd_meeting_agent, sd_local_playbook

DEFAULT_FROM_FIO = "Жалыбин Максим Дмитриевич"
DEFAULT_TO_FIO = "Ильченко Екатерина Александровна"

# Canonical published agents on Zhalybin (newest done + published).
DEFAULT_SRC_RK = "96c34f87-3776-4ebf-960a-c5089d551d1d"
DEFAULT_SRC_SD = "622388eb-b81e-4471-89a0-46979f5926b0"


def _resolve_user(db, *, user_id: str, fio: str) -> AppUser:
    if user_id.strip():
        row = db.query(AppUser).filter(AppUser.id == user_id.strip()).first()
        if row is None:
            raise SystemExit(f"User not found: {user_id}")
        return row
    row = db.query(AppUser).filter(AppUser.fio == fio.strip()).first()
    if row is None:
        row = (
            db.query(AppUser)
            .filter(AppUser.fio.ilike(f"%{(fio.strip().split() or [''])[0]}%"))
            .first()
        )
    if row is None:
        raise SystemExit(f"User not found: {fio}")
    return row


def _find_published_meeting(db, user_id: str, *, kind: str) -> Workflow | None:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.phase == "done")
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    for row in rows:
        local = row.local_run if isinstance(row.local_run, dict) else {}
        if not local.get("published"):
            continue
        title = row.title or ""
        notes = row.notes or ""
        if kind == "rk" and is_rk_meeting_agent(title, notes):
            return row
        if kind == "sd" and is_sd_meeting_agent(title):
            return row
    return None


def _find_target_by_title(db, user_id: str, title: str) -> Workflow | None:
    return (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.title == title)
        .order_by(Workflow.updated_at.desc())
        .first()
    )


def _copy_files(db, *, src_id: str, dst_id: str) -> int:
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


def _apply_meeting_playbook(row: Workflow, *, kind: str) -> None:
    title = (row.title or "").strip()
    notes = (row.notes or row.document_text or title).strip()
    row.plan_json = apply_meeting_plan_runtime(
        dict(row.plan_json or {}),
        title=title,
        notes=notes,
    )
    local = dict(row.local_run or {})
    if kind == "rk":
        local["playbook"] = rk_local_playbook(title=title, demo_text=notes, answered_scope=title)
    else:
        local["playbook"] = sd_local_playbook(title=title, demo_text=notes, answered_scope=title)
    local["published"] = True
    local["phase"] = "done"
    local["tests_status"] = local.get("tests_status") or "pass"
    local["demo_ok"] = True
    local["status"] = "published"
    local["can_publish"] = False
    row.local_run = apply_meeting_agent_config(local, title=title, notes=notes)
    row.phase = "done"
    flag_modified(row, "local_run")
    flag_modified(row, "plan_json")


def _clone_or_update(
    db,
    *,
    src: Workflow,
    target_user_id: str,
    kind: str,
    dry_run: bool,
) -> dict:
    title = (src.title or "").strip()
    hit = _find_target_by_title(db, target_user_id, title)
    if hit is not None and hit.phase not in {"deleted"}:
        workflow_id = hit.id
        action = "updated"
        hit.notes = src.notes or ""
        hit.document_name = src.document_name or ""
        hit.document_text = src.document_text or ""
        hit.plan_json = copy.deepcopy(src.plan_json or {})
        hit.attachments_meta = copy.deepcopy(src.attachments_meta or [])
        hit.local_run = copy.deepcopy(src.local_run or {})
        hit.last_result = src.last_result or ""
        row = hit
    else:
        workflow_id = str(uuid4())
        action = "created"
        row = Workflow(
            id=workflow_id,
            user_id=target_user_id,
            title=title,
            phase="done",
            notes=src.notes or "",
            document_name=src.document_name or "",
            document_text=src.document_text or "",
            plan_json=copy.deepcopy(src.plan_json or {}),
            attachments_meta=copy.deepcopy(src.attachments_meta or []),
            local_run=copy.deepcopy(src.local_run or {}),
            last_result=src.last_result or "",
        )
        db.add(row)

    _apply_meeting_playbook(row, kind=kind)

    if dry_run:
        return {
            "action": action,
            "kind": kind,
            "workflowId": workflow_id,
            "title": title,
            "sourceId": src.id,
            "dryRun": True,
        }

    db.flush()
    files = _copy_files(db, src_id=src.id, dst_id=workflow_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    sync_recurring_triggers_from_draft(db, user_id=target_user_id, workflow=row)
    db.commit()
    return {
        "action": action,
        "kind": kind,
        "workflowId": workflow_id,
        "title": title,
        "sourceId": src.id,
        "filesCopied": files,
    }


def assign_meeting_agents(
    *,
    from_user_id: str,
    to_user_id: str,
    src_rk_id: str = DEFAULT_SRC_RK,
    src_sd_id: str = DEFAULT_SRC_SD,
    dry_run: bool = False,
) -> list[dict]:
    init_db()
    db = SessionLocal()
    results: list[dict] = []
    try:
        src_rk = db.get(Workflow, src_rk_id)
        src_sd = db.get(Workflow, src_sd_id)
        if src_rk is None or src_rk.user_id != from_user_id:
            found = _find_published_meeting(db, from_user_id, kind="rk")
            if found is None:
                raise SystemExit("RK source workflow not found")
            src_rk = found
        if src_sd is None or src_sd.user_id != from_user_id:
            found = _find_published_meeting(db, from_user_id, kind="sd")
            if found is None:
                raise SystemExit("SD source workflow not found")
            src_sd = found

        for kind, src in (("rk", src_rk), ("sd", src_sd)):
            info = _clone_or_update(
                db,
                src=src,
                target_user_id=to_user_id,
                kind=kind,
                dry_run=dry_run,
            )
            results.append(info)
            print(
                f"{'DRY-RUN' if dry_run else info['action'].upper()} {kind.upper()} "
                f"{info['workflowId']} <- {info['sourceId']} | {info['title']}"
            )
        return results
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign RK/SD meeting agents to another user")
    parser.add_argument("--from-user", default="")
    parser.add_argument("--to-user", default="")
    parser.add_argument("--from-fio", default=DEFAULT_FROM_FIO)
    parser.add_argument("--to-fio", default=DEFAULT_TO_FIO)
    parser.add_argument("--src-rk", default=DEFAULT_SRC_RK)
    parser.add_argument("--src-sd", default=DEFAULT_SRC_SD)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        src_user = _resolve_user(db, user_id=args.from_user, fio=args.from_fio)
        dst_user = _resolve_user(db, user_id=args.to_user, fio=args.to_fio)
        print(f"From: {src_user.fio} ({src_user.id})")
        print(f"To:   {dst_user.fio} ({dst_user.id})")
    finally:
        db.close()

    assign_meeting_agents(
        from_user_id=src_user.id,
        to_user_id=dst_user.id,
        src_rk_id=args.src_rk,
        src_sd_id=args.src_sd,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

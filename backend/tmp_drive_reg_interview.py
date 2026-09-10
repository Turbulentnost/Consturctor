"""Copy PSD agent to Komarkova and dump her SD workflow."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal, init_db
from app.models.workflow import Workflow, WorkflowFile
from app.services.triggers.service import sync_recurring_triggers_from_draft

SRC_ID = "c6507926-74ec-4606-ab68-5a4bfcea76a7"
KOMARKOVA = "82FBCC3C4322D93A44439708C0DDC7B5"
OUT = BACKEND_ROOT / "tmp_interview_state.json"


def brief(row: Workflow) -> dict:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    draft = local.get("playbook_draft") if isinstance(local.get("playbook_draft"), dict) else {}
    plan = row.plan_json if isinstance(row.plan_json, dict) else {}
    qs = []
    for item in plan.get("open_questions") or []:
        if isinstance(item, dict):
            qs.append({
                "id": item.get("id"),
                "question": item.get("question") or item.get("prompt"),
                "answer": item.get("answer"),
            })
    return {
        "id": row.id,
        "title": row.title,
        "phase": row.phase,
        "updated_at": str(row.updated_at),
        "published": bool(local.get("published")),
        "demo_ok": local.get("demo_ok"),
        "tests_status": local.get("tests_status"),
        "notes": (row.notes or "")[:2500],
        "document_text": (row.document_text or "")[:8000],
        "last_result": (row.last_result or "")[:4000],
        "open_questions": qs,
        "draft_goal": draft.get("goal"),
        "draft_answers": draft.get("answers"),
        "when_to_run": draft.get("when_to_run"),
        "draft_steps": draft.get("steps") or [],
        "playbook": local.get("playbook") if isinstance(local.get("playbook"), dict) else {},
        "schedule_draft": local.get("schedule_draft"),
        "design_answers": local.get("design_answers"),
        "validation": local.get("validation"),
        "answered_questions": plan.get("answered_questions") or [],
    }


def copy_psd(db) -> str:
    src = db.get(Workflow, SRC_ID)
    if src is None:
        raise SystemExit("source missing")
    hit = (
        db.query(Workflow)
        .filter(Workflow.user_id == KOMARKOVA, Workflow.title == src.title, Workflow.phase == "done")
        .first()
    )
    if hit is not None:
        return hit.id
    new_id = str(uuid4())
    row = Workflow(
        id=new_id,
        user_id=KOMARKOVA,
        title=src.title,
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
    for item in db.query(WorkflowFile).filter(WorkflowFile.workflow_id == src.id).all():
        db.add(WorkflowFile(
            id=str(uuid4()),
            workflow_id=new_id,
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
        ))
    db.flush()
    sync_recurring_triggers_from_draft(db, user_id=KOMARKOVA, workflow=row)
    db.commit()
    return new_id


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        copied = copy_psd(db)
        rows = (
            db.query(Workflow)
            .filter(Workflow.user_id == KOMARKOVA)
            .order_by(Workflow.updated_at.desc())
            .all()
        )
        sd = [r for r in rows if "заседаний" in (r.title or "").casefold() and "совет" in (r.title or "").casefold()]
        payload = {
            "copied_psd_id": copied,
            "titles": [{"id": r.id, "title": r.title, "phase": r.phase, "published": bool((r.local_run or {}).get("published"))} for r in rows],
            "sd": [brief(r) for r in sd],
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("copied", copied, "count", len(rows), "sd", len(sd))
        for r in rows:
            print(r.phase, r.id, r.title)
    finally:
        db.close()


if __name__ == "__main__":
    main()

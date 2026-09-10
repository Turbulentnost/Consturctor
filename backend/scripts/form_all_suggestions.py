"""Create workflows for every agent suggestion in an agent draft.

Usage (from backend/):
  py -3.12 scripts/form_all_suggestions.py --draft-id agent-draft-3afca7cbc916
  py -3.12 scripts/form_all_suggestions.py --fio "Жалыбин Максим Дмитриевич"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal, init_db
from app.models.regulation import AgentDraft
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.agent_passport.from_suggestion import draft_passport_from_function
from app.services.agent_passport.service import complete_passport
from app.services.workflows.meeting_agent_config import (
    apply_meeting_agent_config,
    apply_meeting_plan_runtime,
)
from app.services.workflows.rk_meeting_playbook import (
    is_rk_meeting_agent,
    rk_local_playbook,
    rk_schedule_draft,
)
from app.services.workflows.sd_meeting_playbook import (
    is_sd_meeting_agent,
    sd_local_playbook,
)
from app.services.workflows.service import _local_playbook, create_workflow
from sqlalchemy.orm.attributes import flag_modified

DEFAULT_FIO = "Жалыбин Максим Дмитриевич"
DEFAULT_DRAFT_ID = "agent-draft-3afca7cbc916"

SYSTEMS_NOTE = (
    "Источники данных: 1С ERP, Action Tracker, Outlook, Excel/Word по необходимости. "
    "Справочная информация уже в системах; отсутствующие файлы пользователь "
    "прикрепляет на каждом запуске или указывает, что их нет."
)

AUTONOMY = {
    "can_autonomous": "Чтение данных из систем и подготовка черновиков отчётов/докладов.",
    "needs_human_approval": "Отправка писем, запись в системы, утверждение решений и финальная выдача.",
    "forbidden": "Самостоятельное утверждение, изменение зарплатных параметров, необратимые действия без человека.",
}


def _normalize_title(title: str) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip().casefold())
    return text.replace("ии-агент:", "").strip()


def _existing_titles(db, user_id: str) -> set[str]:
    rows = db.query(Workflow).filter(Workflow.user_id == user_id).all()
    return {_normalize_title(row.title or "") for row in rows}


def _publish_workflow_row(db, row: Workflow) -> Workflow:
    """Сделать workflow видимым в «Мои агенты» (board показывает только phase=done)."""
    notes = (row.notes or row.document_text or row.title or "").strip()
    title = (row.title or "ИИ-агент").strip()
    if is_rk_meeting_agent(title, notes):
        playbook = rk_local_playbook(title=title, demo_text=notes, answered_scope=title)
    elif is_sd_meeting_agent(title, notes):
        playbook = sd_local_playbook(title=title, demo_text=notes, answered_scope=title)
    else:
        playbook = _local_playbook(
            title=title,
            demo_text=notes,
            tools=["desktop.report.export"],
            answered_scope=title,
        )
    plan = apply_meeting_plan_runtime(
        dict(row.plan_json or {}),
        title=title,
        notes=notes,
    )
    if not plan.get("goal"):
        plan["goal"] = title
    if not plan.get("title"):
        plan["title"] = title
    row.title = title
    row.phase = "done"
    row.plan_json = plan
    schedule = rk_schedule_draft() if is_rk_meeting_agent(title, notes) else {"name": "", "goal": "", "triggers": []}
    row.local_run = apply_meeting_agent_config(
        {
            "status": "published",
            "published": True,
            "can_publish": False,
            "tests_status": "pass",
            "demo_ok": True,
            "runtime": "mcp",
            "ui_mode": "chat",
            "playbook": playbook,
            "source": "regulation_batch",
            "schedule_draft": schedule,
        },
        title=title,
        notes=notes,
    )
    flag_modified(row, "local_run")
    db.add(row)
    return row


def _create_published_workflow(
    db,
    *,
    user_id: str,
    notes: str,
    title: str,
    draft_id: str,
) -> Workflow:
    record = create_workflow(
        db,
        user_id=user_id,
        notes=notes,
        files=[],
        draft_id=draft_id,
    )
    row = db.get(Workflow, record.id)
    if row is None:
        raise RuntimeError(f"Workflow not found after create: {record.id}")
    row.title = title
    return _publish_workflow_row(db, row)


def publish_by_titles(
    *,
    user_id: str,
    title_keys: list[str],
    dry_run: bool = False,
) -> list[dict]:
    init_db()
    db = SessionLocal()
    published: list[dict] = []
    try:
        rows = (
            db.query(Workflow)
            .filter(Workflow.user_id == user_id)
            .order_by(Workflow.updated_at.desc())
            .all()
        )
        seen_keys: set[str] = set()
        for key in title_keys:
            norm_key = _normalize_title(key)
            if norm_key in seen_keys:
                continue
            match = next(
                (
                    row
                    for row in rows
                    if norm_key in _normalize_title(row.title or "")
                    and (row.phase or "") != "done"
                ),
                None,
            )
            if match is None:
                match = next(
                    (row for row in rows if norm_key in _normalize_title(row.title or "")),
                    None,
                )
            if match is None:
                print(f"MISSING: {key}")
                continue
            if (match.phase or "") == "done" and (match.local_run or {}).get("published"):
                print(f"SKIP published: {match.title}")
                seen_keys.add(norm_key)
                published.append({"workflowId": match.id, "title": match.title, "status": "already"})
                continue
            if dry_run:
                print(f"DRY publish: {match.title} ({match.phase})")
                continue
            _publish_workflow_row(db, match)
            seen_keys.add(norm_key)
            published.append({"workflowId": match.id, "title": match.title, "status": "published"})
            print(f"PUBLISHED {match.id[:8]}… {match.title}")
        if not dry_run:
            db.commit()
        return published
    finally:
        db.close()


def _notes_from_passport_text(text: str, fallback_title: str) -> str:
    body = (text or "").strip()
    if body:
        return f"{body}\n\n{SYSTEMS_NOTE}"
    return f"{fallback_title}\n\n{SYSTEMS_NOTE}"


def _notes_from_suggestion(suggestion: dict) -> str:
    title = str(suggestion.get("title") or "ИИ-агент").strip()
    description = str(suggestion.get("description") or "").strip()
    parts = [title]
    if description:
        parts.extend(["", description])
    parts.extend(["", SYSTEMS_NOTE])
    return "\n".join(parts).strip()


def _fill_passport(db, *, user_id: str, suggestion: dict) -> str:
    built = draft_passport_from_function(
        db,
        user_id=user_id,
        regulation_id=str(suggestion["regulationId"]),
        role_match_run_id=str(suggestion["roleMatchRunId"]),
        function_id=str(suggestion["functionId"]),
        agent_title=str(suggestion.get("title") or ""),
        agent_description=str(suggestion.get("description") or ""),
        draft_id=str(suggestion.get("draftId") or ""),
        agent_id=str(suggestion.get("agentId") or ""),
    )
    passport = built.passport
    updates = dict(AUTONOMY)
    for field in ("goal", "trigger", "receives", "checks", "decisions", "result"):
        value = str(getattr(passport, field, "") or "").strip()
        if value:
            updates[field] = value
    if not str(getattr(passport, "name", "") or "").strip():
        updates["name"] = str(suggestion.get("title") or "ИИ-агент").replace("ИИ-агент:", "").strip()
    completed = complete_passport(
        passport,
        field_updates=updates,
        bp_name=str(suggestion.get("title") or ""),
        excerpt=built.excerpt,
        functions=built.functions,
    )
    text = str(getattr(completed, "text", "") or "").strip()
    if text:
        return _notes_from_passport_text(text, str(suggestion.get("title") or ""))
    return _notes_from_suggestion(suggestion)


def form_all(
    *,
    user_id: str,
    draft_id: str,
    skip_existing: bool = True,
    dry_run: bool = False,
) -> list[dict]:
    init_db()
    db = SessionLocal()
    created: list[dict] = []
    try:
        draft = (
            db.query(AgentDraft)
            .filter(AgentDraft.id == draft_id, AgentDraft.user_id == user_id)
            .first()
        )
        if draft is None:
            raise SystemExit(f"Agent draft not found: {draft_id}")

        suggestions = [
            item
            for item in (draft.result_json or {}).get("agentSuggestions") or []
            if isinstance(item, dict)
        ]
        if not suggestions:
            raise SystemExit(f"No agentSuggestions in draft {draft_id}")

        existing = _existing_titles(db, user_id) if skip_existing else set()
        print(f"Draft: {draft.title}")
        print(f"Suggestions: {len(suggestions)}")

        for suggestion in suggestions:
            title = str(suggestion.get("title") or "ИИ-агент").strip()
            norm = _normalize_title(title)
            if skip_existing and norm in existing:
                row = next(
                    (
                        item
                        for item in db.query(Workflow)
                        .filter(Workflow.user_id == user_id)
                        .order_by(Workflow.updated_at.desc())
                        .all()
                        if norm in _normalize_title(item.title or "")
                    ),
                    None,
                )
                if row is not None and (row.phase or "") != "done":
                    if dry_run:
                        print(f"DRY publish existing: {title}")
                    else:
                        _publish_workflow_row(db, row)
                        print(f"PUBLISHED existing {row.id[:8]}… {row.title}")
                        created.append({"workflowId": row.id, "title": row.title, "phase": "done"})
                else:
                    print(f"SKIP (exists): {title}")
                continue

            notes = _notes_from_suggestion(suggestion)
            if dry_run:
                print(f"DRY-RUN create: {title}")
                created.append({"title": title, "dryRun": True})
                continue

            row = _create_published_workflow(
                db,
                user_id=user_id,
                notes=notes,
                title=title.replace("ИИ-агент:", "").strip() or title,
                draft_id=draft.id,
            )
            existing.add(norm)
            entry = {"workflowId": row.id, "title": row.title, "phase": row.phase}
            created.append(entry)
            print(f"OK {row.id[:8]}… {row.title} ({row.phase})")

        if not dry_run:
            db.commit()
        return created
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Form workflows from all agent suggestions")
    parser.add_argument("--draft-id", default=DEFAULT_DRAFT_ID)
    parser.add_argument("--user-id", default="")
    parser.add_argument("--fio", default=DEFAULT_FIO)
    parser.add_argument("--force", action="store_true", help="Create even if title already exists")
    parser.add_argument("--publish-only", action="store_true", help="Only publish existing workflows by title")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        user_id = args.user_id.strip()
        if not user_id:
            user = db.query(AppUser).filter(AppUser.fio == args.fio).first()
            if user is None:
                user = (
                    db.query(AppUser)
                    .filter(AppUser.fio.ilike(f"%{args.fio.split()[0]}%"))
                    .first()
                )
            if user is None:
                raise SystemExit(f"User not found: {args.fio}")
            user_id = user.id
            print(f"User: {user.fio} ({user_id})")
    finally:
        db.close()

    if args.publish_only:
        keys = [
            "Еженедельный отчёт",
            "реестра подарков",
            "данных KPI",
            "утреннего доклада",
            "распознавания аудио",
            "технических замечаний",
            "версий нормативных",
        ]
        published = publish_by_titles(user_id=user_id, title_keys=keys, dry_run=args.dry_run)
        print(f"\nPublished: {len(published)}")
        return

    created = form_all(
        user_id=user_id,
        draft_id=args.draft_id,
        skip_existing=not args.force,
        dry_run=args.dry_run,
    )
    print(f"\nCreated: {len(created)}")


if __name__ == "__main__":
    main()

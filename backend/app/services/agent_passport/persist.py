"""Сохранение паспорта в result_json черновика агента."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.regulation import AgentDraft
from app.services.agent_passport.service import AgentPassport, passport_from_dict
from app.services.agent_passport.types import ExtractedFunction
from app.services.agents import AgentDraftError, create_or_get_draft, get_draft_row

_PASSPORTS_KEY = "passports"


def store_key(function_id: str, agent_id: str = "") -> str:
    return (function_id or agent_id or "").strip()


def read_saved(result_json: dict | None, key: str) -> dict | None:
    if not key:
        return None
    store = (result_json or {}).get(_PASSPORTS_KEY) or {}
    if not isinstance(store, dict):
        return None
    item = store.get(key)
    return item if isinstance(item, dict) else None


def write_saved(result_json: dict | None, key: str, payload: dict) -> dict:
    data = dict(result_json or {})
    store = dict(data.get(_PASSPORTS_KEY) or {}) if isinstance(data.get(_PASSPORTS_KEY), dict) else {}
    store[key] = payload
    data[_PASSPORTS_KEY] = store
    return data


def session_payload(
    passport: AgentPassport,
    *,
    excerpt: str,
    functions: list[ExtractedFunction],
    bp_name: str,
    qa_history: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "passport": passport.as_dict(),
        "excerpt": excerpt,
        "bp_name": bp_name,
        "functions": [
            {
                "name": item.name,
                "description": item.description,
                "action_level": item.action_level,
                "requires_human_approval": item.requires_human_approval,
                "automation_kind": item.automation_kind,
            }
            for item in functions
        ],
        "qa_history": list(qa_history or []),
    }


def functions_from_payload(payload: dict) -> list[ExtractedFunction]:
    items: list[ExtractedFunction] = []
    for raw in payload.get("functions") or []:
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            continue
        items.append(
            ExtractedFunction(
                name=str(raw.get("name") or ""),
                description=str(raw.get("description") or ""),
                action_level=str(raw.get("action_level") or "read"),
                requires_human_approval=bool(raw.get("requires_human_approval")),
                automation_kind=str(raw.get("automation_kind") or "auto"),
            )
        )
    return items


def passport_from_payload(payload: dict) -> AgentPassport | None:
    raw = payload.get("passport")
    if not isinstance(raw, dict):
        return None
    return passport_from_dict(raw)


def resolve_draft(
    db: Session,
    *,
    user_id: str,
    draft_id: str = "",
    regulation_id: str = "",
    role_match_run_id: str = "",
) -> AgentDraft | None:
    if draft_id.strip():
        try:
            return get_draft_row(db, user_id=user_id, draft_id=draft_id.strip())
        except AgentDraftError:
            return None
    if regulation_id.strip() and role_match_run_id.strip():
        try:
            detail = create_or_get_draft(
                db,
                user_id=user_id,
                regulation_id=regulation_id.strip(),
                role_match_run_id=role_match_run_id.strip(),
            )
            return get_draft_row(db, user_id=user_id, draft_id=detail.draftId)
        except AgentDraftError:
            return None
    return None


def load_saved_session(
    draft: AgentDraft,
    *,
    function_id: str,
    agent_id: str = "",
) -> dict | None:
    key = store_key(function_id, agent_id)
    return read_saved(draft.result_json, key)


def save_session(
    db: Session,
    draft: AgentDraft,
    *,
    function_id: str,
    agent_id: str = "",
    payload: dict,
) -> None:
    key = store_key(function_id, agent_id)
    if not key:
        return
    draft.result_json = write_saved(draft.result_json, key, payload)
    db.add(draft)
    db.commit()
    db.refresh(draft)

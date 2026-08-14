from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.regulation import RoleFunction, RoleMatchResult
from app.services.agent_passport.service import AgentPassport, draft_passport
from app.services.agent_passport.types import ExtractedFunction
from app.services.regulation.storage import get_document
from app.services.role_matching.service import RoleMatchError, get_role_match_run


class PassportBuildError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def draft_passport_from_function(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    role_match_run_id: str,
    function_id: str,
    agent_title: str = "",
    agent_description: str = "",
) -> tuple[AgentPassport, str, list[ExtractedFunction]]:
    """Собрать паспорт по функции из role-match + текст фрагмента регламента."""
    try:
        role_result = get_role_match_run(
            db,
            user_id=user_id,
            regulation_id=regulation_id,
            run_id=role_match_run_id,
        )
    except RoleMatchError as exc:
        raise PassportBuildError(exc.message, status_code=exc.status_code) from exc

    function = _find_function(role_result, function_id)
    if function is None:
        raise PassportBuildError("Функция для агента не найдена", status_code=404)

    doc = get_document(db, regulation_id=regulation_id, user_id=user_id)
    if doc is None:
        raise PassportBuildError("Регламент не найден", status_code=404)
    result_json = doc.result_json or {}
    fragments = result_json.get("fragments") or []
    excerpt = _excerpt_for_function(fragments, function, agent_description)
    extracted = [_to_extracted(function, agent_title)]
    bp_name = (agent_title or _title_from_function(function)).strip() or "ИИ-агент"
    passport = draft_passport(
        bp_name=bp_name,
        excerpt=excerpt,
        functions=extracted,
        agent_name=bp_name,
    )
    return passport, excerpt, extracted


def _find_function(role_result: RoleMatchResult, function_id: str) -> RoleFunction | None:
    for item in role_result.functions or []:
        if item and item.functionId == function_id:
            return item
    for match in role_result.matches or []:
        if match.function is not None and match.function.functionId == function_id:
            return match.function
    return None


def _to_extracted(function: RoleFunction, agent_title: str) -> ExtractedFunction:
    name = _title_from_function(function)
    if agent_title:
        name = agent_title.removeprefix("ИИ-агент:").strip() or name
    description_parts = [
        part
        for part in [
            function.explanation,
            f"Действие: {function.action}" if function.action else "",
            f"Объект: {function.object}" if function.object else "",
            f"Адресат: {function.recipient}" if function.recipient else "",
        ]
        if part
    ]
    return ExtractedFunction(
        name=name,
        description=". ".join(description_parts)[:1200],
        action_level="read",
        requires_human_approval=bool(function.requiresUserConfirmation),
        automation_kind="auto",
    ).with_derived_approval()


def _title_from_function(function: RoleFunction) -> str:
    action = (function.action or "").strip()
    obj = (function.object or "").strip()
    if action and obj:
        return f"{action} {obj}"[:180]
    return action or obj or "Бизнес-процесс"


def _excerpt_for_function(fragments: list, function: RoleFunction, fallback: str) -> str:
    by_id = {
        str(item.get("fragmentId") or ""): item
        for item in fragments
        if isinstance(item, dict)
    }
    block_ids = [function.targetBlockId]
    for item in function.evidence or []:
        if item.fragmentId:
            block_ids.append(item.fragmentId)
    for item in function.proofChain or []:
        if item.blockId:
            block_ids.append(item.blockId)
    chunks: list[str] = []
    seen: set[str] = set()
    for block_id in block_ids:
        frag = by_id.get(block_id or "")
        if not frag:
            continue
        text = str(frag.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        chunks.append(text)
        if len("\n\n".join(chunks)) > 2500:
            break
    if chunks:
        return "\n\n".join(chunks)[:3500]
    return (fallback or "")[:3500]

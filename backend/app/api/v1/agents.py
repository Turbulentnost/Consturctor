from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.regulation import (
    AgentDraftDetail,
    AgentDraftListResult,
    AgentDraftStatusRequest,
    QuestionChatSendRequest,
    QuestionChatSessionResult,
)
from app.services.agents import (
    AgentDraftError,
    create_or_get_draft,
    ensure_draft_readiness,
    get_draft,
    list_drafts,
    update_draft_status,
)
from app.services.agent_platform import list_allowed_tools
from app.services.readiness.chat import (
    create_or_get_question_chat,
    get_question_chat,
    send_question_chat_message,
)
from app.services.readiness.service import ReadinessError

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/drafts", response_model=AgentDraftListResult)
async def list_agent_drafts(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentDraftListResult:
    return list_drafts(db, user_id=auth.user_id)


@router.get("/drafts/{draft_id}", response_model=AgentDraftDetail)
async def get_agent_draft(
    draft_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentDraftDetail:
    try:
        return get_draft(db, user_id=auth.user_id, draft_id=draft_id)
    except AgentDraftError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/drafts/{draft_id}/readiness", response_model=AgentDraftDetail)
async def ensure_agent_draft_readiness(
    draft_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentDraftDetail:
    try:
        return ensure_draft_readiness(db, user_id=auth.user_id, draft_id=draft_id)
    except (AgentDraftError, ReadinessError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/drafts/{draft_id}/status", response_model=AgentDraftDetail)
async def update_agent_draft_status(
    draft_id: str,
    request: AgentDraftStatusRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentDraftDetail:
    try:
        return update_draft_status(db, user_id=auth.user_id, draft_id=draft_id, request=request)
    except AgentDraftError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/drafts/{draft_id}/questions/{question_id}/chat",
    response_model=QuestionChatSessionResult,
)
async def create_question_chat(
    draft_id: str,
    question_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionChatSessionResult:
    try:
        return create_or_get_question_chat(
            db,
            user_id=auth.user_id,
            draft_id=draft_id,
            question_id=question_id,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get(
    "/drafts/{draft_id}/questions/{question_id}/chat",
    response_model=QuestionChatSessionResult,
)
async def read_question_chat(
    draft_id: str,
    question_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionChatSessionResult:
    try:
        return get_question_chat(db, user_id=auth.user_id, draft_id=draft_id, question_id=question_id)
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/drafts/{draft_id}/questions/{question_id}/chat/messages",
    response_model=QuestionChatSessionResult,
)
async def send_question_chat(
    draft_id: str,
    question_id: str,
    request: QuestionChatSendRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionChatSessionResult:
    try:
        return send_question_chat_message(
            db,
            user_id=auth.user_id,
            draft_id=draft_id,
            question_id=question_id,
            request=request,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/drafts/{draft_id}/tools")
async def list_draft_tools(
    draft_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        draft = get_draft(db, user_id=auth.user_id, draft_id=draft_id)
    except AgentDraftError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    department = draft.department or auth.department or ""
    tools = list_allowed_tools(department)
    return {
        "agent_id": draft.id,
        "department": department,
        "platform_agent_id": draft.id,
        "items": tools,
    }


@router.post("/drafts/from-regulation/{regulation_id}/role-matches/{run_id}", response_model=AgentDraftDetail)
async def create_draft_from_role_match(
    regulation_id: str,
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentDraftDetail:
    try:
        return create_or_get_draft(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            role_match_run_id=run_id,
        )
    except AgentDraftError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

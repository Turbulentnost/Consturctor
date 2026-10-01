from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin_page
from app.core.jwt import AuthContext
from app.schemas.admin import (
    AdminAiAgentsOut,
    AdminHistoryOut,
    AdminKnowledgeBaseOut,
    AdminKpiOut,
    AdminLaunchCalendarOut,
    AdminOverviewOut,
    AdminSettingsOut,
    AdminUsersOut,
)
from app.services.admin import agents as admin_agents_service
from app.services.admin import calendar as admin_calendar_service
from app.services.admin import history as admin_history_service
from app.services.admin import knowledge as admin_knowledge_service
from app.services.admin import kpi as admin_kpi_service
from app.services.admin import overview as overview_service
from app.services.admin import settings as admin_settings_service
from app.services.admin import users as admin_users_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewOut, response_model_by_alias=True)
async def admin_overview(_auth: AuthContext = Depends(require_admin_page("overview"))) -> AdminOverviewOut:
    return overview_service.build_admin_overview()


@router.get("/history", response_model=AdminHistoryOut, response_model_by_alias=True)
async def admin_history(_auth: AuthContext = Depends(require_admin_page("history"))) -> AdminHistoryOut:
    return admin_history_service.build_admin_history()


@router.get("/launch-calendar", response_model=AdminLaunchCalendarOut, response_model_by_alias=True)
async def admin_launch_calendar(
    _auth: AuthContext = Depends(require_admin_page("launch_calendar")),
) -> AdminLaunchCalendarOut:
    return admin_calendar_service.build_admin_launch_calendar()


@router.get("/kpi", response_model=AdminKpiOut, response_model_by_alias=True)
async def admin_kpi(_auth: AuthContext = Depends(require_admin_page("kpi"))) -> AdminKpiOut:
    return admin_kpi_service.build_admin_kpi()


@router.get("/users", response_model=AdminUsersOut, response_model_by_alias=True)
async def admin_users(_auth: AuthContext = Depends(require_admin_page("users"))) -> AdminUsersOut:
    return admin_users_service.build_admin_users()


@router.get("/ai-agents", response_model=AdminAiAgentsOut, response_model_by_alias=True)
async def admin_ai_agents(_auth: AuthContext = Depends(require_admin_page("ai_agents"))) -> AdminAiAgentsOut:
    return admin_agents_service.build_admin_ai_agents()


@router.get("/knowledge-base", response_model=AdminKnowledgeBaseOut, response_model_by_alias=True)
async def admin_knowledge_base(
    _auth: AuthContext = Depends(require_admin_page("knowledge_base")),
) -> AdminKnowledgeBaseOut:
    return admin_knowledge_service.build_admin_knowledge_base()


@router.get("/settings", response_model=AdminSettingsOut, response_model_by_alias=True)
async def admin_settings(_auth: AuthContext = Depends(require_admin_page("settings"))) -> AdminSettingsOut:
    return admin_settings_service.build_admin_settings()

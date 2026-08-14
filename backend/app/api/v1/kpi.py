from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.kpi_metrics import (
    AgentCardKpiListResponse,
    AgentCardKpiOut,
    KpiMetricTemplateListResponse,
    UpdateAgentKpiMetricsRequest,
    UpdateAgentCardTitleRequest,
)
from app.services import kpi_metrics, platform_proxy
from platform_contracts.agent_card import AgentTaskReport
from platform_contracts.kpi import (
    AgentExecutionHistoryListResponse,
    AgentExecutionHistoryOut,
    AgentExecutionHistoryStart,
    KpiSummary,
    ReviewEvent,
    ReviewEventCreate,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/kpi", tags=["kpi"])


@router.get("/summary", response_model=KpiSummary)
async def kpi_summary(
    auth: AuthContext = Depends(get_current_user),
    department: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=24 * 30),
) -> KpiSummary:
    params: list[str] = []
    dept = (department or auth.department or "").strip()
    if dept:
        params.append(f"department={dept}")
    agent = (agent_id or "").strip()
    if agent:
        params.append(f"agent_id={agent}")
    if hours != 24:
        params.append(f"hours={hours}")
    path = "/api/v1/kpi/summary"
    if params:
        path = f"{path}?{'&'.join(params)}"
    try:
        data = await platform_proxy.proxy_get(settings.kpi_service_url, path)
        return KpiSummary.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/metric-templates", response_model=KpiMetricTemplateListResponse)
async def metric_templates(
    _: AuthContext = Depends(get_current_user),
) -> KpiMetricTemplateListResponse:
    return KpiMetricTemplateListResponse(items=kpi_metrics.list_metric_templates())


@router.get("/agent-cards", response_model=AgentCardKpiListResponse)
async def list_agent_cards_kpi(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentCardKpiListResponse:
    try:
        items = kpi_metrics.list_agent_cards(db, department=auth.department or "")
    except kpi_metrics.KpiMetricsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return AgentCardKpiListResponse(items=items)


@router.get("/agent-cards/{agent_id}", response_model=AgentCardKpiOut)
async def get_agent_card_kpi(
    agent_id: str,
    _: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentCardKpiOut:
    try:
        return kpi_metrics.get_agent_card_metrics(db, agent_id)
    except kpi_metrics.KpiMetricsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/agent-cards/{agent_id}/title", response_model=AgentCardKpiOut)
async def update_agent_card_title_kpi(
    agent_id: str,
    body: UpdateAgentCardTitleRequest,
    _: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentCardKpiOut:
    try:
        return kpi_metrics.update_agent_card_title(
            db,
            agent_id=agent_id,
            title=body.title,
        )
    except kpi_metrics.KpiMetricsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.put("/agent-cards/{agent_id}/metrics", response_model=AgentCardKpiOut)
async def update_agent_card_kpi(
    agent_id: str,
    body: UpdateAgentKpiMetricsRequest,
    _: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentCardKpiOut:
    try:
        return kpi_metrics.update_agent_card_metrics(
            db,
            agent_id=agent_id,
            metrics=body.kpi_metrics,
        )
    except kpi_metrics.KpiMetricsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/agent-tasks/report")
async def agent_task_report(
    body: AgentTaskReport,
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    _ = auth
    try:
        return await platform_proxy.proxy_post(
            settings.kpi_service_url,
            "/api/v1/kpi/agent-tasks/report",
            body.model_dump(mode="json"),
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/review", response_model=ReviewEvent)
async def kpi_review(
    body: ReviewEventCreate,
    auth: AuthContext = Depends(get_current_user),
) -> ReviewEvent:
    payload = body.model_dump(mode="json")
    if not payload.get("department"):
        payload["department"] = auth.department
    try:
        data = await platform_proxy.proxy_post(
            settings.kpi_service_url,
            "/api/v1/kpi/review",
            payload,
        )
        return ReviewEvent.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/execution-history", response_model=AgentExecutionHistoryListResponse)
async def list_execution_history(
    auth: AuthContext = Depends(get_current_user),
    agent_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> AgentExecutionHistoryListResponse:
    _ = auth
    params: list[str] = [f"limit={limit}"]
    agent = (agent_id or "").strip()
    if agent:
        params.append(f"agent_id={agent}")
    path = f"/api/v1/kpi/execution-history?{'&'.join(params)}"
    try:
        data = await platform_proxy.proxy_get(settings.kpi_service_url, path)
        return AgentExecutionHistoryListResponse.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/execution-history/start", response_model=AgentExecutionHistoryOut)
async def start_execution_history(
    body: AgentExecutionHistoryStart,
    auth: AuthContext = Depends(get_current_user),
) -> AgentExecutionHistoryOut:
    _ = auth
    try:
        data = await platform_proxy.proxy_post(
            settings.kpi_service_url,
            "/api/v1/kpi/execution-history/start",
            body.model_dump(mode="json"),
        )
        return AgentExecutionHistoryOut.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/execution-history/{history_id}/complete",
    response_model=AgentExecutionHistoryOut,
)
async def complete_execution_history(
    history_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> AgentExecutionHistoryOut:
    _ = auth
    try:
        data = await platform_proxy.proxy_post(
            settings.kpi_service_url,
            f"/api/v1/kpi/execution-history/{history_id}/complete",
            {},
        )
        return AgentExecutionHistoryOut.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

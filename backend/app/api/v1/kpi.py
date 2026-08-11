from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.agent_card import AgentTaskReport
from platform_contracts.kpi import KpiSummary, ReviewEvent, ReviewEventCreate

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

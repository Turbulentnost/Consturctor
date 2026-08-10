from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.kpi import KpiSummary, ReviewEvent, ReviewEventCreate

router = APIRouter(prefix="/kpi", tags=["kpi"])


@router.get("/summary", response_model=KpiSummary)
async def kpi_summary(
    auth: AuthContext = Depends(get_current_user),
    department: str | None = Query(default=None),
) -> KpiSummary:
    dept = (department or auth.department or "").strip()
    path = f"/api/v1/kpi/summary?department={dept}" if dept else "/api/v1/kpi/summary"
    try:
        data = await platform_proxy.proxy_get(settings.kpi_service_url, path)
        return KpiSummary.model_validate(data)
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

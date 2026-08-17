from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.runs import RunStartRequest, RunStatus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunStatus)
async def start_run(
    body: RunStartRequest,
    auth: AuthContext = Depends(get_current_user),
) -> RunStatus:
    payload = body.model_dump(mode="json")
    if not payload.get("department"):
        payload["department"] = auth.department
    if not payload.get("user_id"):
        payload["user_id"] = auth.user_id
    try:
        data = await platform_proxy.proxy_post(
            settings.orchestrator_url,
            "/api/v1/runs",
            payload,
        )
        return RunStatus.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{run_id}", response_model=RunStatus)
async def get_run(
    run_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> RunStatus:
    try:
        data = await platform_proxy.proxy_get(
            settings.orchestrator_url,
            f"/api/v1/runs/{run_id}",
        )
        return RunStatus.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    try:
        return await platform_proxy.proxy_get(
            settings.orchestrator_url,
            f"/api/v1/runs/{run_id}/events",
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

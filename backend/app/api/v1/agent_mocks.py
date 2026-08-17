from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.runs import RunStartRequest, RunStatus

router = APIRouter(prefix="/agent/mocks", tags=["agent-mocks"])


@router.get("")
async def list_mocks(auth: AuthContext = Depends(get_current_user)) -> dict:
    try:
        return await platform_proxy.proxy_get(
            settings.orchestrator_url,
            "/api/v1/agent/mocks",
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{scenario_id}/run", response_model=RunStatus)
async def run_mock(
    scenario_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> RunStatus:
    payload = RunStartRequest(
        agent_id=f"mock-{scenario_id}",
        department=auth.department,
        user_id=auth.user_id,
    ).model_dump(mode="json")
    try:
        data = await platform_proxy.proxy_post(
            settings.orchestrator_url,
            f"/api/v1/agent/mocks/{scenario_id}/run",
            payload,
        )
        return RunStatus.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{scenario_id}/simulate")
async def simulate_mock(
    scenario_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    payload = RunStartRequest(
        agent_id=f"mock-{scenario_id}",
        department=auth.department,
        user_id=auth.user_id,
    ).model_dump(mode="json")
    try:
        return await platform_proxy.proxy_post(
            settings.orchestrator_url,
            f"/api/v1/agent/mocks/{scenario_id}/simulate",
            payload,
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

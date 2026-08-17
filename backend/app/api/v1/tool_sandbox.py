from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.runs import RunStartRequest

router = APIRouter(prefix="/tools/sandbox", tags=["tool-sandbox"])


def _run_payload(auth: AuthContext) -> dict:
    return RunStartRequest(
        agent_id="sandbox",
        department=auth.department,
        user_id=auth.user_id,
    ).model_dump(mode="json")


@router.get("")
async def list_sandbox(auth: AuthContext = Depends(get_current_user)) -> dict:
    try:
        return await platform_proxy.proxy_get(
            settings.orchestrator_url,
            "/api/v1/tools/sandbox",
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/run-all")
async def run_all_sandbox(auth: AuthContext = Depends(get_current_user)) -> dict:
    try:
        return await platform_proxy.proxy_post(
            settings.orchestrator_url,
            "/api/v1/tools/sandbox/run-all",
            _run_payload(auth),
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{test_id}/run")
async def run_sandbox_test(
    test_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    try:
        return await platform_proxy.proxy_post(
            settings.orchestrator_url,
            f"/api/v1/tools/sandbox/{test_id}/run",
            _run_payload(auth),
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

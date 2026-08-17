from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.cron import CronJobCreate, CronJobOut, CronJobUpdate
from platform_contracts.runs import RunStatus

router = APIRouter(prefix="/cron", tags=["cron"])


@router.get("/templates")
async def list_cron_templates(auth: AuthContext = Depends(get_current_user)) -> dict:
    try:
        return await platform_proxy.proxy_get(settings.orchestrator_url, "/api/v1/cron/templates")
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/jobs")
async def list_jobs(
    auth: AuthContext = Depends(get_current_user),
    mine: bool = Query(default=True),
    enabled_only: bool = Query(default=False),
) -> dict:
    params = f"?enabled_only={'true' if enabled_only else 'false'}"
    if mine:
        params += f"&user_id={auth.user_id}"
    try:
        return await platform_proxy.proxy_get(settings.orchestrator_url, f"/api/v1/cron/jobs{params}")
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/jobs", response_model=CronJobOut)
async def create_job(
    body: CronJobCreate,
    auth: AuthContext = Depends(get_current_user),
) -> CronJobOut:
    payload = body.model_dump(mode="json")
    if not payload.get("department"):
        payload["department"] = auth.department
    if not payload.get("user_id"):
        payload["user_id"] = auth.user_id
    try:
        data = await platform_proxy.proxy_post(
            settings.orchestrator_url,
            "/api/v1/cron/jobs",
            payload,
        )
        return CronJobOut.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/jobs/{job_id}", response_model=CronJobOut)
async def get_job(job_id: UUID, auth: AuthContext = Depends(get_current_user)) -> CronJobOut:
    try:
        data = await platform_proxy.proxy_get(
            settings.orchestrator_url,
            f"/api/v1/cron/jobs/{job_id}",
        )
        return CronJobOut.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/jobs/{job_id}", response_model=CronJobOut)
async def update_job(
    job_id: UUID,
    body: CronJobUpdate,
    auth: AuthContext = Depends(get_current_user),
) -> CronJobOut:
    try:
        data = await platform_proxy.proxy_patch(
            settings.orchestrator_url,
            f"/api/v1/cron/jobs/{job_id}",
            body.model_dump(mode="json", exclude_none=True),
        )
        return CronJobOut.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: UUID, auth: AuthContext = Depends(get_current_user)) -> dict:
    try:
        return await platform_proxy.proxy_delete(
            settings.orchestrator_url,
            f"/api/v1/cron/jobs/{job_id}",
        )
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/jobs/{job_id}/run", response_model=RunStatus)
async def run_job_now(job_id: UUID, auth: AuthContext = Depends(get_current_user)) -> RunStatus:
    try:
        data = await platform_proxy.proxy_post(
            settings.orchestrator_url,
            f"/api/v1/cron/jobs/{job_id}/run",
            {},
        )
        return RunStatus.model_validate(data)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

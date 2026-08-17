from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.clients.erp_sql import ErpSqlError, ping
from app.config import settings
from app.schemas.health import HealthResponse, PlatformServiceHealth
from app.services import auth_service, platform_proxy

logger = logging.getLogger(__name__)
router = APIRouter()

_PLATFORM_SERVICES = (
    ("kpi", settings.kpi_service_url),
    ("imap", settings.tool_imap_url),
    ("onec", settings.tool_onec_url),
    ("shell", settings.tool_shell_url),
    ("shell-native", settings.tool_shell_native_url),
    ("browser", settings.tool_browser_url),
    ("com", settings.tool_com_url),
    ("fs", settings.tool_fs_url),
    ("desktop-host", settings.tool_desktop_host_url),
    ("desktop-launcher", settings.tool_desktop_launcher_url),
    ("orchestrator", settings.orchestrator_url),
)


async def _check_platform_services() -> list[PlatformServiceHealth]:
    results: list[PlatformServiceHealth] = []

    async def _one(name: str, url: str) -> PlatformServiceHealth:
        data = await platform_proxy.check_service_health(url)
        return PlatformServiceHealth(
            name=name,
            reachable=bool(data.get("reachable")),
            status=str(data.get("status", "unknown")),
        )

    checks = await asyncio.gather(*[_one(name, url) for name, url in _PLATFORM_SERVICES])
    results.extend(checks)
    return results


@router.get("/health", response_model=HealthResponse)
@router.get("/api/v1/health", response_model=HealthResponse, include_in_schema=True)
async def health() -> HealthResponse:
    erp_reachable = False
    if not settings.auth_stub:
        try:
            erp_reachable = await asyncio.to_thread(ping)
        except ErpSqlError as exc:
            logger.warning("ERP health check failed: %s", exc)
        except Exception as exc:
            logger.warning("Unexpected ERP health check error: %s", exc)

    platform_services = await _check_platform_services()
    platform_ok = all(s.reachable for s in platform_services) if platform_services else True

    if settings.auth_stub:
        status = "ok" if platform_ok else "degraded"
    elif erp_reachable and platform_ok:
        status = "ok"
    else:
        status = "degraded"

    return HealthResponse(
        status=status,
        erp_reachable=erp_reachable,
        erp_server=settings.erp_sql_server,
        llm_provider=settings.llm_provider,
        auth_stub=settings.auth_stub,
        registration_enabled=auth_service.registration_enabled(),
        dev_mode=settings.dev_mode,
        platform_services=platform_services,
    )

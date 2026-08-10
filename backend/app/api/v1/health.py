from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.clients.erp_sql import ErpSqlError, ping
from app.config import settings
from app.schemas.health import HealthResponse, PlatformServiceHealth
from app.services import platform_proxy

logger = logging.getLogger(__name__)
router = APIRouter()

_PLATFORM_SERVICES = (
    ("kpi", settings.kpi_service_url),
    ("imap", settings.tool_imap_url),
    ("onec", settings.tool_onec_url),
    ("shell", settings.tool_shell_url),
    ("browser", settings.tool_browser_url),
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
async def health() -> HealthResponse:
    erp_reachable = False
    try:
        erp_reachable = await asyncio.to_thread(ping)
    except ErpSqlError:
        logger.warning("ERP health check failed", exc_info=True)
    except Exception:
        logger.warning("Unexpected ERP health check error", exc_info=True)

    platform_services = await _check_platform_services()
    platform_ok = all(s.reachable for s in platform_services) if platform_services else True

    if erp_reachable and platform_ok:
        status = "ok"
    elif erp_reachable or platform_ok:
        status = "degraded"
    else:
        status = "degraded"

    return HealthResponse(
        status=status,
        erp_reachable=erp_reachable,
        erp_server=settings.erp_sql_server,
        llm_provider=settings.llm_provider,
        platform_services=platform_services,
    )

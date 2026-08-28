from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter

from app.clients.erp_sql import ErpSqlError, ping
from app.config import settings
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_ERP_PING_TTL_SEC = 60.0
_erp_ping_cache: tuple[float, bool] | None = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    global _erp_ping_cache
    now = time.monotonic()
    cached = _erp_ping_cache
    if cached is not None and now - cached[0] < _ERP_PING_TTL_SEC:
        erp_reachable = cached[1]
    else:
        erp_reachable = False
        try:
            erp_reachable = await asyncio.to_thread(ping)
        except ErpSqlError:
            logger.warning("ERP health check failed", exc_info=True)
        except Exception:
            logger.warning("Unexpected ERP health check error", exc_info=True)
        _erp_ping_cache = (time.monotonic(), erp_reachable)

    return HealthResponse(
        status="ok" if erp_reachable else "degraded",
        erp_reachable=erp_reachable,
        erp_server=settings.erp_sql_server,
        llm_provider=settings.llm_provider,
    )

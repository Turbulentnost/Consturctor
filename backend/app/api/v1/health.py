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

# Every desktop client polls /health; an unreachable ERP costs a 3s timeout per
# call, so the last verdict is reused for a few seconds.
_PING_TTL = 15.0
_ping_cache: tuple[float, bool] | None = None


async def _erp_reachable() -> bool:
    global _ping_cache
    now = time.monotonic()
    if _ping_cache is not None and now - _ping_cache[0] < _PING_TTL:
        return _ping_cache[1]
    reachable = False
    try:
        reachable = await asyncio.wait_for(asyncio.to_thread(ping), timeout=3.0)
    except TimeoutError:
        logger.warning("ERP health check timed out")
    except ErpSqlError:
        logger.warning("ERP health check failed", exc_info=True)
    except Exception:
        logger.warning("Unexpected ERP health check error", exc_info=True)
    _ping_cache = (now, bool(reachable))
    return bool(reachable)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    erp_reachable = await _erp_reachable()

    return HealthResponse(
        status="ok" if erp_reachable else "degraded",
        erp_reachable=erp_reachable,
        erp_server=settings.erp_sql_server,
        llm_provider=settings.llm_provider,
    )

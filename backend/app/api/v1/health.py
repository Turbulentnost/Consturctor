from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.clients.erp_sql import ErpSqlError, ping
from app.config import settings
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    erp_reachable = False
    try:
        erp_reachable = await asyncio.to_thread(ping)
    except ErpSqlError:
        logger.warning("ERP health check failed", exc_info=True)
    except Exception:
        logger.warning("Unexpected ERP health check error", exc_info=True)

    return HealthResponse(
        status="ok" if erp_reachable else "degraded",
        erp_reachable=erp_reachable,
        erp_server=settings.erp_sql_server,
        llm_provider=settings.llm_provider,
    )

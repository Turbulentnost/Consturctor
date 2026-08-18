from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.session import init_db

    logger.info(
        "Constructor backend starting (ERP=%s/%s, LLM=%s, DB=%s)",
        settings.erp_sql_server,
        settings.erp_sql_database,
        settings.llm_provider,
        settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url,
    )
    scheduler_tasks: list[asyncio.Task] = []
    try:
        init_db()
        logger.info("App Postgres schema ready")
        from app.api.v1.notifications import notification_scheduler
        from app.api.v1.triggers import trigger_scheduler
        from app.services.workflows.kpi_calc import kpi_scheduler

        scheduler_tasks = [
            asyncio.create_task(notification_scheduler()),
            asyncio.create_task(trigger_scheduler()),
            asyncio.create_task(kpi_scheduler()),
        ]
    except Exception:
        logger.exception("Failed to initialize app Postgres")
        raise
    yield
    for task in scheduler_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Constructor Backend",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()

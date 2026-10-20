from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import tool_settings
from app.agents.registry import load_catalog as load_agents
from app.api.router import api_router
from app.config import settings
from app.constructor.catalog import constructor_catalog
from app.platform.history import start_backfill as start_history_backfill
from app.skills.registry import load_catalog as load_skills
from app.tools.registry import load_catalog as load_tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tool_settings.apply()
    load_agents()
    load_tools()
    load_skills()
    if settings.constructor_sync_enabled:
        constructor_catalog.start(settings.constructor_sync_seconds)
    start_history_backfill()
    logger.info(
        "TurboTester backend on %s:%s, Constructor DB %s",
        settings.api_host,
        settings.api_port,
        constructor_catalog.source,
    )
    yield
    constructor_catalog.stop()


app = FastAPI(title="TurboTester Backend", version="0.1.0", lifespan=lifespan)
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

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()

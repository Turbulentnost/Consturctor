from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import BACKEND_ROOT, settings
from app.core.console import configure_logging

_LOG_FILE = BACKEND_ROOT / "logs" / "backend.log"


def _configure_console_encoding() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass


def _configure_logging(*, to_file: bool = False) -> None:
    """Keep Cursor/httpx/app logs visible; the running server also writes backend/logs/backend.log.

    Uvicorn may already attach handlers, so basicConfig is a no-op and httpx
    stays at WARNING — that's why the terminal looks empty during a run.
    """
    configure_logging(_LOG_FILE if to_file else None)
    for name in (
        "httpx",
        "httpcore",
        "httpcore.http11",
        "app",
        "app.clients.cursor",
        "app.services.workflows",
        "app.services.workflows.service",
        "app.services.workflows.cursor_tools",
        "uvicorn.access",
    ):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        log.propagate = True


_configure_console_encoding()
_configure_logging()
from app.services.upstream_error_log import install_httpx_capture

install_httpx_capture()
logger = logging.getLogger(__name__)
http_logger = logging.getLogger("app.http")


def _http_trace(message: str) -> None:
    try:
        http_logger.info(message)
    except OSError:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.session import init_db

    _configure_logging(to_file=True)
    logger.info(
        "Constructor backend starting (ERP=%s/%s, LLM=%s, DB=%s)",
        settings.erp_sql_server,
        settings.erp_sql_database,
        settings.llm_provider,
        settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url,
    )
    scheduler_tasks: list[asyncio.Task] = []
    try:
        db_ready = True
        try:
            init_db()
            logger.info("App Postgres schema ready")
        except Exception:
            if not settings.app_db_optional:
                raise
            db_ready = False
            logger.warning(
                "App Postgres unavailable — starting without it (APP_DB_OPTIONAL=1): %s",
                settings.database_url.split("@")[-1],
                exc_info=True,
            )
        from app.api.v1.notifications import board_live_subscriber, notification_scheduler
        from app.services.triggers.tick import tick_due_triggers
        from app.modules.chat.realtime import dispatch_event

        def _erp_warmup() -> None:
            try:
                from app.clients.erp_sql import warmup

                warmup()
                logger.info("ERP SQL warmup ok")
            except Exception:
                logger.warning("ERP SQL warmup failed", exc_info=True)

        def _chat_outbound_loop() -> None:
            try:
                from app.modules.chat.bus.outbound import consume_outbound

                consume_outbound(dispatch_event)
            except Exception as exc:
                # RabbitMQ optional on dev PC (docker compose constructor-rabbit).
                if "ConnectionRefusedError" in type(exc).__name__ or "AMQPConnectionError" in type(
                    exc
                ).__name__:
                    logger.info(
                        "Chat outbound skipped (RabbitMQ not on 127.0.0.1:5672). "
                        "Run: docker compose up -d constructor-rabbit"
                    )
                else:
                    logger.warning("chat outbound consumer not started", exc_info=True)

        import threading

        threading.Thread(target=_erp_warmup, name="erp-warmup", daemon=True).start()
        threading.Thread(target=_chat_outbound_loop, name="chat-outbound", daemon=True).start()

        async def trigger_scheduler() -> None:
            await asyncio.sleep(8)
            while True:
                try:
                    await asyncio.to_thread(tick_due_triggers)
                except Exception:
                    logger.exception("Trigger scheduler tick failed")
                await asyncio.sleep(20)

        async def kpi_scheduler() -> None:
            from app.services.workflows.kpi_calc import run_due_kpi_calculations

            await asyncio.sleep(15)
            while True:
                try:
                    await asyncio.to_thread(run_due_kpi_calculations)
                except Exception:
                    logger.exception("KPI scheduler tick failed")
                await asyncio.sleep(60)

        from app.api.v1.platform_tasks import platform_task_scheduler

        async def position_kpi_cache_scheduler() -> None:
            from app.services.position_kpi.daily import run_daily_position_kpi_cache

            await asyncio.sleep(25)
            while True:
                try:
                    await asyncio.to_thread(run_daily_position_kpi_cache)
                except Exception:
                    logger.exception("Position KPI daily cache tick failed")
                await asyncio.sleep(300)

        if db_ready:
            scheduler_tasks = [
                asyncio.create_task(platform_task_scheduler()),
                asyncio.create_task(notification_scheduler()),
                asyncio.create_task(board_live_subscriber()),
                asyncio.create_task(trigger_scheduler()),
                asyncio.create_task(kpi_scheduler()),
                asyncio.create_task(position_kpi_cache_scheduler()),
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


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled backend exception")
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.middleware("http")
async def _log_http_requests(request: Request, call_next):
    started = time.perf_counter()
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    client = request.client.host if request.client else "-"
    _http_trace(f"API request {request.method} {path}{query} client={client}")
    try:
        response = await call_next(request)
    except Exception:
        _http_trace(f"API error {request.method} {path}{query}")
        http_logger.exception("API error %s %s%s", request.method, path, query)
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _http_trace(
        f"API response {request.method} {path}{query} -> {getattr(response, 'status_code', '-')}"
        f" in {elapsed_ms:.1f}ms"
    )
    return response
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
        log_config=None,
    )


if __name__ == "__main__":
    run()

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
from app.config import settings


def _configure_console_encoding() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass


def _configure_logging() -> None:
    """Keep Cursor/httpx/app logs visible under uvicorn --reload.

    Uvicorn may already attach handlers, so basicConfig is a no-op and httpx
    stays at WARNING — that's why the terminal looks empty during a run.
    """
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setLevel(logging.INFO)
        handler.setFormatter(fmt)
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
logger = logging.getLogger(__name__)
http_logger = logging.getLogger("app.http")


def _http_trace(message: str) -> None:
    print(message, flush=True)
    http_logger.info(message)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.session import init_db

    _configure_logging()
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
        from app.api.v1.notifications import board_live_subscriber, notification_scheduler
        from app.services.triggers.tick import tick_due_triggers
        from app.modules.chat.realtime import dispatch_event

        def _chat_outbound_loop() -> None:
            try:
                from app.modules.chat.bus.outbound import consume_outbound

                consume_outbound(dispatch_event)
            except Exception:
                logger.warning("chat outbound consumer not started", exc_info=True)

        import threading

        threading.Thread(target=_chat_outbound_loop, name="chat-outbound", daemon=True).start()

        async def trigger_scheduler() -> None:
            await asyncio.sleep(8)
            while True:
                try:
                    await asyncio.to_thread(tick_due_triggers)
                except Exception:
                    logger.exception("Trigger scheduler tick failed")
                await asyncio.sleep(20)

        scheduler_tasks = [
            asyncio.create_task(notification_scheduler()),
            asyncio.create_task(board_live_subscriber()),
            asyncio.create_task(trigger_scheduler()),
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
    )


if __name__ == "__main__":
    run()

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic_settings import BaseSettings, SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest, ToolResult


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
    )
    use_stubs: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 7820
    service_name: str = "platform-service"


ToolHandler = Callable[[ToolInvokeRequest], dict[str, Any]]


def create_tool_app(
    settings: ServiceSettings,
    handlers: dict[str, ToolHandler],
    stub_handlers: dict[str, ToolHandler] | None = None,
) -> FastAPI:
    app = FastAPI(title=settings.service_name, version="0.1.0")
    stubs = stub_handlers or handlers

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "use_stubs": settings.use_stubs,
        }

    @app.post("/api/v1/tools/{tool_name}/invoke", response_model=ToolResult)
    def invoke_tool(tool_name: str, body: ToolInvokeRequest, request: Request) -> ToolResult:
        table = stubs if settings.use_stubs else handlers
        handler = table.get(tool_name)
        if handler is None:
            raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

        department = body.department or request.headers.get("X-Department", "")
        user_id = body.user_id or request.headers.get("X-User-Id", "")
        if not body.run_id:
            header_run = request.headers.get("X-Run-Id")
            if header_run:
                try:
                    body = body.model_copy(update={"run_id": uuid.UUID(header_run)})
                except ValueError:
                    pass

        started = time.perf_counter()
        status = "ok"
        error_message: str | None = None
        data: dict[str, Any] = {}
        try:
            data = handler(body)
        except Exception as exc:
            status = "error"
            error_message = str(exc)
            duration_ms = int((time.perf_counter() - started) * 1000)
            audit_id = _audit(
                tool_name=tool_name,
                body=body,
                department=department,
                user_id=user_id,
                output_summary=error_message or "",
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            return ToolResult(
                ok=False,
                tool_name=tool_name,
                data={},
                error=error_message,
                duration_ms=duration_ms,
                audit_id=audit_id,
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _audit(
            tool_name=tool_name,
            body=body,
            department=department,
            user_id=user_id,
            output_summary=str(data.get("summary") or data.get("message") or "")[:500],
            status=status,
            error_message=None,
            duration_ms=duration_ms,
            payload=body.payload,
        )
        return ToolResult(
            ok=True,
            tool_name=tool_name,
            data=data,
            duration_ms=duration_ms,
            audit_id=audit_id,
        )

    return app


def _audit(
    *,
    tool_name: str,
    body: ToolInvokeRequest,
    department: str,
    user_id: str,
    output_summary: str,
    status: str,
    error_message: str | None,
    duration_ms: int,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    try:
        from platform_db.audit import log_tool_event
        from platform_db.session import get_session_factory

        factory = get_session_factory()
        with factory() as session:
            row = log_tool_event(
                session,
                tool_name=tool_name,
                run_id=body.run_id,
                department=department,
                user_id=user_id,
                payload=payload or body.payload,
                output_summary=output_summary,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            session.commit()
            return row.id
    except Exception:
        return None


def run_app(app: FastAPI, settings: ServiceSettings) -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)

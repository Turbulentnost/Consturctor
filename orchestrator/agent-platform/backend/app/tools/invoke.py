"""Вызов инструмента из каталога: так его исполняет агент на стенде и ручной запуск в UI."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError

from app import tool_settings
from app.tools.registry import get_invoker, get_tool

logger = logging.getLogger(__name__)


class ToolCallResult(BaseModel):
    tool: str
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: int = 0


async def invoke_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    agent_id: str | None = None,
) -> ToolCallResult:
    started = time.perf_counter()

    def done(ok: bool, result: Any = None, error: str | None = None) -> ToolCallResult:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ToolCallResult(tool=name, ok=ok, result=result, error=error, duration_ms=elapsed)

    tool_settings.ensure_applied()
    spec = get_tool(name)
    if spec is None:
        return done(False, error=f"Неизвестный инструмент: {name}")
    invoker = get_invoker(name)
    if not spec.available or invoker is None:
        return done(False, error=f"Инструмент недоступен: {spec.unavailable_reason or name}")

    args = dict(arguments or {})
    # Файловые инструменты Constructor выбирают рабочую папку по agent_id.
    if agent_id and not args.get("agent_id"):
        args["agent_id"] = agent_id
    try:
        result = await asyncio.wait_for(invoker(args), timeout=spec.timeout_seconds)
    except TimeoutError:
        return done(False, error=f"Таймаут {spec.timeout_seconds} с")
    except ValidationError as exc:
        return done(False, error=f"Неверные параметры: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.info("Tool %s failed: %s", name, exc)
        return done(False, error=str(exc) or type(exc).__name__)
    return done(True, result=jsonable_encoder(result))

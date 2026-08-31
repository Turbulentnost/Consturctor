"""Compatibility shim: regulation creation uses shared Cursor client."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError, TERMINAL_RUN_STATUSES, get_run, wait_for_run
from app.config import settings

__all__ = [
    "CursorAgentError",
    "TERMINAL_RUN_STATUSES",
    "archive_agent",
    "cancel_run",
    "create_agent",
    "create_run",
    "get_run",
    "stream_run_events",
    "wait_for_run",
]


def create_agent(prompt: str) -> tuple[str, str]:
    data = cursor_client.create_agent(
        prompt=prompt,
        model_id=settings.cursor_regulation_creation_model,
        name="Создание регламента",
        mode="agent",
        model_params=[
            {"id": "effort", "value": settings.cursor_regulation_creation_effort},
            {"id": "fast", "value": "true"},
        ],
    )
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or "")
    if not agent_id or not run_id:
        raise CursorAgentError("Cursor API не вернул agent/run id")
    return agent_id, run_id


def create_run(agent_id: str, prompt: str) -> str:
    run = cursor_client.create_run(agent_id, prompt=prompt, mode="agent")
    run_id = str(run.get("id") or "")
    if not run_id:
        raise CursorAgentError("Cursor API не вернул run id")
    return run_id


def stream_run_events(agent_id: str, run_id: str) -> Iterator[dict[str, Any]]:
    yield from cursor_client.stream_run_events(agent_id, run_id)


def cancel_run(agent_id: str, run_id: str) -> None:
    cursor_client.cancel_run(agent_id, run_id)


def archive_agent(agent_id: str) -> None:
    cursor_client.archive_agent(agent_id)

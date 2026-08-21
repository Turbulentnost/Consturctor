from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.config import cursor_api_key, cursor_model

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]

_disposed_prompts: list[str] = []


def run_oneshot_prompt(
    prompt: str,
    *,
    cwd: str,
    on_event: EventCallback | None = None,
) -> str:
    """Agent.prompt one-shot — create, send, wait, close."""
    api_key = cursor_api_key()
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY не задан в .env")

    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

    if on_event:
        on_event({"type": "status", "text": "Запрос к Cursor SDK…"})

    opts = AgentOptions(
        api_key=api_key,
        model=cursor_model(),
        local=LocalAgentOptions(cwd=cwd or "."),
    )
    result = Agent.prompt(prompt, opts)
    text = str(result.result or "").strip()
    if on_event and text:
        on_event({"type": "agent_message", "text": text[:2000]})
    return text


def mark_prompt_disposed(agent_id: str) -> None:
    if agent_id:
        _disposed_prompts.append(agent_id)


def was_prompt_disposed(agent_id: str) -> bool:
    return agent_id in _disposed_prompts

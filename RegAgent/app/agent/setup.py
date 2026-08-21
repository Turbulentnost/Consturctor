from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.agent.json_parse import clarifications_to_text, fallback_ui_spec, parse_ui_spec
from app.agent.prompts import build_setup_prompt
from app.config import cursor_api_key, cursor_model
from app.models import UiSpec

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]


class SetupAgentError(RuntimeError):
    pass


def run_setup(
    *,
    regulation_text: str,
    file_name: str = "",
    clarifications: dict[str, str] | None = None,
    on_event: EventCallback | None = None,
) -> UiSpec:
    clar_text = clarifications_to_text(clarifications or {})
    prompt = build_setup_prompt(
        regulation_text=regulation_text,
        file_name=file_name,
        clarifications=clar_text,
    )

    api_key = cursor_api_key()
    if not api_key:
        if on_event:
            on_event({"type": "status", "text": "CURSOR_API_KEY не задан — черновик UI локально"})
        return fallback_ui_spec(regulation_text, file_name)

    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

    if on_event:
        on_event({"type": "status", "text": "Анализирую регламент через Cursor SDK…"})

    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=cursor_model(),
                local=LocalAgentOptions(cwd="."),
            ),
        )
        text = str(result.result or "")
        if on_event:
            on_event({"type": "agent_message", "text": text[:2000]})
        return parse_ui_spec(text)
    except Exception as exc:
        logger.warning("Setup agent failed: %s", exc)
        if on_event:
            on_event({"type": "error", "message": str(exc)})
        spec = fallback_ui_spec(regulation_text, file_name)
        spec.summary = f"Черновик (ошибка setup: {exc})"
        return spec

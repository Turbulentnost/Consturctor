"""Единая точка вызова LLM для runtime (Cursor / Claude / Chad / stub)."""

from __future__ import annotations

from app.services.llm_provider import effective_llm_provider


def generate(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    quick: bool = False,
) -> str | None:
    provider = effective_llm_provider()
    if provider == "cursor":
        from app.services import cursor_llm

        return cursor_llm.generate(prompt, system=system, max_tokens=max_tokens, quick=quick)
    if provider in {"claudehub", "chad", "lm_studio"}:
        from app.services.agent_passport import llm as passport_llm

        return passport_llm.generate(prompt, system=system, max_tokens=max_tokens, quick=quick)
    return None


def last_error() -> str:
    provider = effective_llm_provider()
    if provider == "cursor":
        from app.services import cursor_llm

        return cursor_llm.last_error()
    if provider in {"claudehub", "chad", "lm_studio"}:
        from app.services.agent_passport import llm as passport_llm

        return passport_llm.last_error()
    return "LLM provider is stub"

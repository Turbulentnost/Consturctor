"""Определение доступного LLM-провайдера (боевой vs stub)."""

from __future__ import annotations

from app.config import settings


def effective_llm_provider() -> str:
    """Вернуть имя провайдера, который реально может ответить."""
    requested = (settings.llm_provider or "stub").strip().lower()
    if requested in {"stub", "none", "disabled"}:
        return "stub"
    if requested == "cursor" and settings.cursor_api_key.strip():
        return "cursor"
    if requested == "claudehub" and settings.claude_api_key.strip():
        return "claudehub"
    if requested == "chad" and settings.chad_api_key.strip():
        return "chad"
    if requested == "lm_studio" and settings.lm_studio_base_url.strip():
        return "lm_studio"
    # Автовыбор: Cursor при наличии ключа (основной провайдер платформы)
    if settings.cursor_api_key.strip() and requested not in {"claudehub", "chad", "lm_studio"}:
        return "cursor"
    if settings.claude_api_key.strip():
        return "claudehub"
    if settings.chad_api_key.strip():
        return "chad"
    return "stub"


def llm_ready() -> bool:
    return effective_llm_provider() != "stub"

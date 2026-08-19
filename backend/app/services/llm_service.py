from __future__ import annotations

from app.config import settings
from app.schemas.llm import ChatMessage, ChatRequest, ChatResponse
from app.services.llm_provider import effective_llm_provider
from app.services import runtime_llm


def chat(request: ChatRequest) -> ChatResponse:
    provider = effective_llm_provider()
    last_user = _last_user_content(request.messages)
    model = request.model or _default_model(provider)

    if provider == "stub":
        content = (
            "[stub] LLM не настроен. Задайте CURSOR_API_KEY в infra/.env "
            f"и LLM_PROVIDER=cursor. Последнее сообщение: {last_user!r}"
        )
        return ChatResponse(provider=provider, model=model, content=content)

    system = _system_message(request.messages)
    reply = runtime_llm.generate(last_user, system=system, max_tokens=2048)
    if not reply:
        err = runtime_llm.last_error() or "LLM unavailable"
        return ChatResponse(
            provider=provider,
            model=model,
            content=f"[{provider}] Ошибка LLM: {err}",
        )
    return ChatResponse(provider=provider, model=model, content=reply.strip())


def _default_model(provider: str) -> str:
    if provider == "cursor":
        return settings.cursor_workflow_model or settings.cursor_regulation_model or "composer-2.5"
    if provider == "claudehub":
        return settings.claudehub_model
    if provider == "chad":
        return settings.chad_model
    if provider == "lm_studio":
        return settings.lm_studio_model
    return "stub-echo"


def _system_message(messages: list[ChatMessage]) -> str | None:
    parts = [m.content.strip() for m in messages if m.role == "system" and m.content.strip()]
    return "\n\n".join(parts) if parts else None


def _last_user_content(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content.strip():
            return msg.content.strip()
    return messages[-1].content.strip() if messages else ""

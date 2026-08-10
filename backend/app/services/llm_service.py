from __future__ import annotations

from app.config import settings
from app.schemas.llm import ChatMessage, ChatRequest, ChatResponse


def chat(request: ChatRequest) -> ChatResponse:
    provider = (settings.llm_provider or "stub").strip().lower()
    if provider != "stub":
        # Future: openai_compat / lm_studio / claude_hub
        provider = "stub"

    last_user = _last_user_content(request.messages)
    model = request.model or "stub-echo"
    content = (
        "[stub] LLM-провайдер ещё не подключён. "
        f"Получено сообщений: {len(request.messages)}. "
        f"Последнее сообщение пользователя: {last_user!r}"
    )
    return ChatResponse(provider=provider, model=model, content=content)


def _last_user_content(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content.strip():
            return msg.content.strip()
    return messages[-1].content.strip() if messages else ""

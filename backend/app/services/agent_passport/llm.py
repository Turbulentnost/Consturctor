from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def generate(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    quick: bool = False,
) -> str | None:
    """Совместимо с Constructor llm_service.generate: None, если LLM недоступна."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    timeout = 35.0 if quick else 90.0
    try:
        return _chat_completions(messages, timeout=timeout, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Passport LLM generate failed: %s", exc)
        return None


def _chat_completions(
    messages: list[dict[str, str]],
    *,
    timeout: float,
    max_tokens: int | None,
) -> str:
    errors: list[str] = []
    if settings.claude_api_key.strip():
        for model in (
            settings.claudehub_model,
            settings.claudehub_fallback_model,
            settings.claudehub_external_fallback_model,
        ):
            if not model:
                continue
            try:
                return _post_openai(
                    f"{settings.claudehub_base_url.rstrip('/')}/v1/chat/completions",
                    messages,
                    model=model,
                    api_key=settings.claude_api_key,
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}: {exc}")
    if settings.chad_api_key.strip():
        for url in (
            "https://api.chadgpt.ru/v1/chat/completions",
            f"{settings.chad_base_url.rstrip('/')}/v1/chat/completions",
        ):
            try:
                return _post_openai(
                    url,
                    messages,
                    model=settings.chad_model,
                    api_key=settings.chad_api_key,
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"chad:{url}: {exc}")
    raise RuntimeError("LLM unavailable: " + " | ".join(errors[:4]))


def _post_openai(
    url: str,
    messages: list[dict[str, str]],
    *,
    model: str,
    api_key: str,
    timeout: float,
    max_tokens: int | None,
) -> str:
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
    data = response.json()
    return str(data["choices"][0]["message"]["content"])

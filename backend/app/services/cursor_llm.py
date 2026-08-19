"""Runtime LLM через Cursor Cloud Agents (composer-2.5)."""

from __future__ import annotations

import logging
import threading

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError
from app.config import settings

logger = logging.getLogger(__name__)

_last_error = ""
_runtime_agent_id = ""
_lock = threading.Lock()


def last_error() -> str:
    return _last_error


def chat_model() -> str:
    model = (settings.cursor_workflow_model or settings.cursor_regulation_model or "composer-2.5").strip()
    return model or "composer-2.5"


def generate(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    quick: bool = False,
) -> str | None:
    """Синхронный ответ Cursor Agent. None + last_error при ошибке."""
    global _last_error
    _last_error = ""
    text = prompt.strip()
    if not text:
        _last_error = "empty prompt"
        return None
    if system and system.strip():
        text = f"{system.strip()}\n\n{text}"
    if max_tokens and max_tokens < 512:
        text = f"{text}\n\n(Ответь кратко, до {max_tokens} токенов.)"
    timeout = 90.0 if quick else 180.0
    try:
        return _run_prompt(text, timeout_seconds=timeout)
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc).strip() or exc.__class__.__name__
        logger.warning("Cursor LLM failed: %s", _last_error)
        return None


def _run_prompt(text: str, *, timeout_seconds: float) -> str:
    if not settings.cursor_api_key.strip():
        raise CursorAgentError("CURSOR_API_KEY не настроен", status_code=500)
    agent_id = _ensure_runtime_agent()
    run = cursor_client.create_run(agent_id, prompt=text, mode="agent")
    run_id = str(run.get("id") or "")
    if not run_id:
        raise CursorAgentError("Cursor API не вернул run id")
    final = cursor_client.wait_for_run(agent_id, run_id, timeout_seconds=timeout_seconds)
    result = str(final.get("result") or "").strip()
    if not result:
        raise CursorAgentError("Cursor Agent вернул пустой ответ")
    return result


def _ensure_runtime_agent() -> str:
    global _runtime_agent_id
    with _lock:
        if _runtime_agent_id:
            return _runtime_agent_id
        model = chat_model()
        created = cursor_client.create_agent(
            prompt=(
                "Ты LLM-помощник платформы Constructor для проверки поручений по SMART "
                "и кратких аналитических ответов на русском языке. "
                "Отвечай по существу, без лишней воды."
            ),
            model_id=model,
            name="Constructor runtime LLM",
            mode="agent",
            model_params=[{"id": "fast", "value": "true"}],
        )
        agent = created.get("agent") if isinstance(created.get("agent"), dict) else {}
        run = created.get("run") if isinstance(created.get("run"), dict) else {}
        agent_id = str(agent.get("id") or "")
        run_id = str(run.get("id") or "")
        if not agent_id or not run_id:
            raise CursorAgentError("Cursor API не вернул agent/run id")
        cursor_client.wait_for_run(agent_id, run_id, timeout_seconds=180.0)
        _runtime_agent_id = agent_id
        logger.info("Cursor runtime LLM agent ready: %s model=%s", agent_id, model)
        return agent_id


def reset_runtime_agent() -> None:
    """Сброс кэша агента (для тестов)."""
    global _runtime_agent_id
    with _lock:
        _runtime_agent_id = ""

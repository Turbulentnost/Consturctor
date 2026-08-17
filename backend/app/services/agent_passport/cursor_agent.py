"""Паспорт ИИ-агента собирает Cursor Cloud Agent, не Claude/Chad."""

from __future__ import annotations

import logging

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError
from app.config import settings

logger = logging.getLogger(__name__)

_last_error = ""


def last_error() -> str:
    return _last_error


def run_prompt(
    prompt: str,
    *,
    system: str = "",
    cursor_agent_id: str = "",
    name: str = "Паспорт ИИ-агента",
) -> tuple[str, str]:
    """Отправить промпт в Cursor Agent. Возвращает (текст, agent_id)."""
    global _last_error
    _last_error = ""
    text = prompt.strip()
    if system.strip():
        text = f"{system.strip()}\n\n{text}"
    if not settings.cursor_api_key.strip():
        raise CursorAgentError("CURSOR_API_KEY не настроен в backend/.env", status_code=500)
    model = settings.cursor_regulation_model
    agent_id = (cursor_agent_id or "").strip()
    run_id = ""
    if agent_id:
        try:
            run = cursor_client.create_run(agent_id, prompt=text, mode="agent")
            run_id = str(run.get("id") or "")
        except CursorAgentError as exc:
            logger.warning("Passport Cursor create_run failed, creating new agent: %s", exc)
            agent_id = ""
    if not agent_id or not run_id:
        created = cursor_client.create_agent(
            prompt=text,
            model_id=model,
            name=name[:100],
            mode="agent",
            model_params=[{"id": "fast", "value": "true"}],
        )
        agent = created.get("agent") if isinstance(created.get("agent"), dict) else {}
        run = created.get("run") if isinstance(created.get("run"), dict) else {}
        agent_id = str(agent.get("id") or "")
        run_id = str(run.get("id") or "")
        if not agent_id or not run_id:
            raise CursorAgentError("Cursor API не вернул agent/run id")
    final = cursor_client.wait_for_run(agent_id, run_id, timeout_seconds=180.0)
    return str(final.get("result") or ""), agent_id


def generate(
    prompt: str,
    *,
    system: str | None = None,
    cursor_agent_id: str = "",
) -> tuple[str | None, str]:
    """Как llm.generate, но через Cursor. None + last_error, если агент недоступен."""
    global _last_error
    try:
        text, agent_id = run_prompt(
            prompt,
            system=system or "",
            cursor_agent_id=cursor_agent_id,
        )
        if not text.strip():
            _last_error = "Cursor Agent вернул пустой ответ"
            return None, agent_id
        return text, agent_id
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc).strip() or exc.__class__.__name__
        logger.warning("Passport Cursor generate failed: %s", _last_error)
        return None, (cursor_agent_id or "").strip()

"""Облачный агент Cursor через REST /v1/agents: один промпт — один ответ, без репозитория."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

TERMINAL = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED", "FAILED"}
CREATE_TIMEOUT = 180.0
POLL_SECONDS = 2.0


class CloudError(RuntimeError):
    pass


@dataclass
class CloudReply:
    agent_id: str
    run_id: str
    text: str


def _request(method: str, path: str, *, json: dict[str, Any] | None = None, timeout: float = 45.0) -> dict[str, Any]:
    key = settings.cursor_api_key.strip()
    if not key:
        raise CloudError("CURSOR_API_KEY не задан в backend/.env")
    url = f"{settings.cursor_api_base_url.rstrip('/')}{path}"
    try:
        response = httpx.request(method, url, json=json, auth=(key, ""), timeout=timeout)
    except httpx.HTTPError as exc:
        raise CloudError(f"Cursor API недоступен: {exc}") from exc
    if response.status_code >= 400:
        raise CloudError(f"Cursor API HTTP {response.status_code}: {response.text[:500]}")
    return response.json() if response.content else {}


def ask(prompt: str, *, name: str, timeout_seconds: float = 300.0) -> CloudReply:
    """Создать облачного агента с промптом, дождаться ответа и отправить агента в архив."""
    body = {
        "prompt": {"text": prompt},
        "mode": "agent",
        "name": name[:100],
        "model": {"id": settings.cursor_cloud_model},
        "skipReviewerRequest": True,
    }
    created = _request("POST", "/v1/agents", json=body, timeout=CREATE_TIMEOUT)
    agent_id = str((created.get("agent") or {}).get("id") or "")
    run_id = str((created.get("run") or {}).get("id") or "")
    if not agent_id or not run_id:
        raise CloudError("Cursor API не вернул id агента и запуска")
    try:
        started = time.monotonic()
        while True:
            run = _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}")
            status = str(run.get("status") or "")
            if status in TERMINAL:
                if status != "FINISHED":
                    raise CloudError(f"Облачный агент завершился со статусом {status}: {run.get('result') or ''}")
                return CloudReply(agent_id=agent_id, run_id=run_id, text=str(run.get("result") or ""))
            if time.monotonic() - started > timeout_seconds:
                raise CloudError("Облачный агент не ответил за отведённое время")
            time.sleep(POLL_SECONDS)
    finally:
        try:
            _request("POST", f"/v1/agents/{agent_id}/archive")
        except CloudError:
            pass

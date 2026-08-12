from __future__ import annotations

import time
import json
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import settings


class CursorAgentError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


TERMINAL_RUN_STATUSES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}


def create_agent(prompt: str) -> tuple[str, str]:
    data = _request(
        "POST",
        "/v1/agents",
        json={
            "name": "Создание регламента",
            "prompt": {"text": prompt},
            "model": {
                "id": settings.cursor_regulation_model,
                "params": [{"id": "fast", "value": "true"}],
            },
            "mode": "agent",
        },
        timeout=90.0,
    )
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or "")
    if not agent_id or not run_id:
        raise CursorAgentError("Cursor API не вернул agent/run id")
    return agent_id, run_id


def create_run(agent_id: str, prompt: str) -> str:
    data = _request(
        "POST",
        f"/v1/agents/{agent_id}/runs",
        json={"prompt": {"text": prompt}, "mode": "agent"},
        timeout=60.0,
    )
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    run_id = str(data.get("id") or run.get("id") or "")
    if not run_id:
        raise CursorAgentError("Cursor API не вернул run id")
    return run_id


def wait_for_run(agent_id: str, run_id: str, *, timeout_seconds: float = 300.0) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        data = get_run(agent_id, run_id)
        status = str(data.get("status") or "")
        if status in TERMINAL_RUN_STATUSES:
            if status != "FINISHED":
                detail = str(data.get("result") or status)
                raise CursorAgentError(f"Cursor Agent завершился со статусом {status}: {detail}")
            return data
        if time.monotonic() - started > timeout_seconds:
            raise CursorAgentError("Cursor Agent не ответил за отведённое время", status_code=504)
        time.sleep(2.0)


def get_run(agent_id: str, run_id: str) -> dict[str, Any]:
    return _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}", timeout=45.0)


def cancel_run(agent_id: str, run_id: str) -> None:
    _request("POST", f"/v1/agents/{agent_id}/runs/{run_id}/cancel", timeout=45.0)


def archive_agent(agent_id: str) -> None:
    _request("POST", f"/v1/agents/{agent_id}/archive", timeout=45.0)


def stream_run_events(agent_id: str, run_id: str) -> Iterator[dict[str, Any]]:
    if not settings.cursor_api_key.strip():
        raise CursorAgentError("CURSOR_API_KEY не настроен в backend/.env", status_code=500)
    url = f"{settings.cursor_api_base_url.rstrip('/')}/v1/agents/{agent_id}/runs/{run_id}/stream"
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "GET",
                url,
                auth=(settings.cursor_api_key, ""),
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", errors="replace")
                    raise CursorAgentError(
                        f"Cursor stream HTTP {response.status_code}: {body[:1000]}",
                        status_code=response.status_code,
                    )
                event_name = "message"
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if line == "":
                        if data_lines:
                            raw_data = "\n".join(data_lines)
                            try:
                                data = json.loads(raw_data)
                            except json.JSONDecodeError:
                                data = {"text": raw_data}
                            yield {"event": event_name, "data": data}
                        event_name = "message"
                        data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
    except httpx.HTTPError as exc:
        raise CursorAgentError(f"Ошибка stream Cursor API: {exc}", status_code=502) from exc


def _request(method: str, path: str, *, json: dict | None = None, timeout: float) -> dict[str, Any]:
    if not settings.cursor_api_key.strip():
        raise CursorAgentError("CURSOR_API_KEY не настроен в backend/.env", status_code=500)
    url = f"{settings.cursor_api_base_url.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method,
                url,
                json=json,
                auth=(settings.cursor_api_key, ""),
                headers={"Content-Type": "application/json"},
            )
    except httpx.TimeoutException as exc:
        raise CursorAgentError("Превышено время ожидания Cursor API", status_code=504) from exc
    except httpx.HTTPError as exc:
        raise CursorAgentError(f"Ошибка сети Cursor API: {exc}", status_code=502) from exc
    if response.status_code == 409:
        raise CursorAgentError("Cursor Agent занят, дождитесь завершения текущего ответа", status_code=409)
    if response.status_code >= 400:
        body = response.text[:1000]
        raise CursorAgentError(f"Cursor API HTTP {response.status_code}: {body}", status_code=response.status_code)
    if not response.content:
        return {}
    return response.json()

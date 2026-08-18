from __future__ import annotations

import json
import logging
import os
import time
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _trace(message: str) -> None:
    os.write(sys.stdout.fileno(), (message + "\n").encode("utf-8", errors="replace"))
    logger.info(message)


def _preview(value: Any, limit: int = 4000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except TypeError:
        text = str(value)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


class CursorAgentError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


TERMINAL_RUN_STATUSES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED", "FAILED"}


def get_me() -> dict[str, Any]:
    _trace("Cursor -> GET /v1/me")
    return _request("GET", "/v1/me", timeout=30.0)


def list_models() -> list[dict[str, Any]]:
    _trace("Cursor -> GET /v1/models")
    data = _request("GET", "/v1/models", timeout=45.0)
    if isinstance(data, list):
        return data
    items = data.get("items") or data.get("models") or []
    return list(items)


def create_agent(
    *,
    prompt: str,
    model_id: str | None = None,
    name: str | None = None,
    mode: str = "agent",
    images: list[dict[str, str]] | None = None,
    model_params: list[dict[str, str]] | None = None,
    repo_url: str | None = None,
    starting_ref: str = "main",
    auto_create_pr: bool = False,
    skip_reviewer_request: bool = True,
) -> dict[str, Any]:
    prompt_body: dict[str, Any] = {"text": prompt}
    if images:
        prompt_body["images"] = images[:5]
    body: dict[str, Any] = {
        "prompt": prompt_body,
        "mode": mode,
        "skipReviewerRequest": skip_reviewer_request,
    }
    if name:
        body["name"] = name[:100]
    if model_id:
        model: dict[str, Any] = {"id": model_id}
        if model_params:
            model["params"] = model_params
        body["model"] = model
    if repo_url:
        body["repos"] = [{"url": repo_url, "startingRef": starting_ref or "main"}]
        body["autoCreatePR"] = auto_create_pr
    _trace(
        "Cursor -> POST /v1/agents "
        f"mode={mode} model={model_id or '-'} name={name or '-'} "
        f"prompt_len={len(prompt or '')} images={len(images or [])}"
    )
    _trace(f"Cursor request body /v1/agents:\n{_preview(body)}")
    return _request("POST", "/v1/agents", json=body, timeout=180.0)


def create_run(
    agent_id: str,
    *,
    prompt: str,
    mode: str | None = "agent",
    images: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    prompt_body: dict[str, Any] = {"text": prompt}
    if images:
        prompt_body["images"] = images[:5]
    body: dict[str, Any] = {"prompt": prompt_body}
    if mode:
        body["mode"] = mode
    _trace(
        "Cursor -> POST /v1/agents/{}/runs mode={} prompt_len={} images={}".format(
            agent_id,
            mode or "-",
            len(prompt or ""),
            len(images or []),
        )
    )
    _trace(f"Cursor request body /v1/agents/{agent_id}/runs:\n{_preview(body)}")
    data = _request("POST", f"/v1/agents/{agent_id}/runs", json=body, timeout=180.0)
    if isinstance(data, dict) and isinstance(data.get("run"), dict):
        return data["run"]
    return data


def get_run(agent_id: str, run_id: str) -> dict[str, Any]:
    _trace(f"Cursor -> GET /v1/agents/{agent_id}/runs/{run_id}")
    return _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}", timeout=45.0)


def wait_for_run(agent_id: str, run_id: str, *, timeout_seconds: float = 300.0) -> dict[str, Any]:
    _trace(f"Cursor wait start agent={agent_id[-8:]} run={run_id[-8:]}")
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


def cancel_run(agent_id: str, run_id: str) -> dict[str, Any]:
    _trace(f"Cursor -> POST /v1/agents/{agent_id}/runs/{run_id}/cancel")
    return _request("POST", f"/v1/agents/{agent_id}/runs/{run_id}/cancel", timeout=45.0)


def archive_agent(agent_id: str) -> dict[str, Any]:
    _trace(f"Cursor -> POST /v1/agents/{agent_id}/archive")
    return _request("POST", f"/v1/agents/{agent_id}/archive", timeout=45.0)


def list_artifacts(agent_id: str) -> list[dict[str, Any]]:
    _trace(f"Cursor -> GET /v1/agents/{agent_id}/artifacts")
    data = _request("GET", f"/v1/agents/{agent_id}/artifacts", timeout=60.0)
    if isinstance(data, list):
        return data
    return list(data.get("items") or [])


def artifact_download_url(agent_id: str, path: str) -> str:
    _trace(f"Cursor -> GET /v1/agents/{agent_id}/artifacts/download path={path}")
    data = _request(
        "GET",
        f"/v1/agents/{agent_id}/artifacts/download",
        params={"path": path},
        timeout=60.0,
    )
    return str(data.get("url") or "")


def download_artifact_to(agent_id: str, path: str, dest: str | Path) -> None:
    url = artifact_download_url(agent_id, path)
    if not url:
        raise CursorAgentError(f"Не удалось получить ссылку на артефакт: {path}")
    try:
        _trace(f"Cursor -> download artifact {path} -> {dest}")
        with httpx.Client(timeout=120.0, follow_redirects=True) as raw:
            with raw.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise CursorAgentError(
                        f"Скачивание артефакта HTTP {resp.status_code}: {body[:500]}",
                        status_code=resp.status_code,
                    )
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        _trace(f"Cursor <- download artifact ok {path}")
    except CursorAgentError:
        raise
    except httpx.HTTPError as exc:
        raise CursorAgentError(f"Ошибка скачивания артефакта: {exc}", status_code=502) from exc


def stream_run_events(
    agent_id: str,
    run_id: str,
    *,
    should_cancel: Callable[[], bool] | None = None,
    idle_timeout_seconds: float = 25.0,
) -> Iterator[dict[str, Any]]:
    """Stream Cursor run events.

    Cursor SSE иногда остаётся открытым после FINISHED и не шлёт terminal-event.
    При простое (read timeout) проверяем get_run и при необходимости отдаём result сами.
    """
    if not settings.cursor_api_key.strip():
        raise CursorAgentError("CURSOR_API_KEY не настроен в backend/.env", status_code=500)
    url = f"{settings.cursor_api_base_url.rstrip('/')}/v1/agents/{agent_id}/runs/{run_id}/stream"
    _trace(f"Cursor -> GET {url}")
    timeout = httpx.Timeout(None, connect=30.0, read=idle_timeout_seconds, write=30.0, pool=30.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            while True:
                try:
                    with client.stream(
                        "GET",
                        url,
                        auth=(settings.cursor_api_key, ""),
                        headers={"Accept": "text/event-stream"},
                    ) as response:
                        if response.status_code == 410:
                            raise CursorAgentError("stream_expired", status_code=410)
                        if response.status_code == 409:
                            raise CursorAgentError("stream_unavailable", status_code=409)
                        if response.status_code >= 400:
                            body = response.read().decode("utf-8", errors="replace")
                            raise CursorAgentError(
                                f"Cursor stream HTTP {response.status_code}: {body[:1000]}",
                                status_code=response.status_code,
                            )
                        _trace(f"Cursor <- GET stream {response.status_code} agent={agent_id[-8:]} run={run_id[-8:]}")
                        event_name = "message"
                        data_lines: list[str] = []
                        for line in response.iter_lines():
                            if should_cancel and should_cancel():
                                try:
                                    cancel_run(agent_id, run_id)
                                except CursorAgentError:
                                    pass
                                return
                            if line == "":
                                if data_lines:
                                    raw_data = "\n".join(data_lines)
                                    try:
                                        data = json.loads(raw_data)
                                    except json.JSONDecodeError:
                                        data = {"text": raw_data}
                                    if not isinstance(data, dict):
                                        data = {"value": data}
                                    _trace(
                                        "Cursor SSE event "
                                        f"{event_name} agent={agent_id[-8:]} run={run_id[-8:]}\n"
                                        f"{_preview(data, 2000)}"
                                    )
                                    yield {"event": event_name, "data": data}
                                    if event_name in {"done", "error", "result"}:
                                        return
                                event_name = "message"
                                data_lines = []
                                continue
                            if line.startswith(":"):
                                continue
                            if line.startswith("event:"):
                                event_name = line.split(":", 1)[1].strip() or "message"
                            elif line.startswith("data:"):
                                data_lines.append(line.split(":", 1)[1].strip())
                        if data_lines:
                            raw_data = "\n".join(data_lines)
                            try:
                                data = json.loads(raw_data)
                            except json.JSONDecodeError:
                                data = {"text": raw_data}
                            if isinstance(data, dict):
                                _trace(
                                    "Cursor SSE event "
                                    f"{event_name} agent={agent_id[-8:]} run={run_id[-8:]}\n"
                                    f"{_preview(data, 2000)}"
                                )
                                yield {"event": event_name, "data": data}
                        # Поток закрылся без terminal-event — заберём результат polling'ом.
                        yield from _terminal_result_events(agent_id, run_id)
                        return
                except httpx.ReadTimeout:
                    terminal = list(_terminal_result_events(agent_id, run_id))
                    if terminal:
                        yield from terminal
                        return
                    # Run ещё идёт — продолжаем ждать через новый stream.
                    continue
    except CursorAgentError:
        raise
    except httpx.HTTPError as exc:
        raise CursorAgentError(f"Ошибка stream Cursor API: {exc}", status_code=502) from exc


def _terminal_result_events(agent_id: str, run_id: str) -> Iterator[dict[str, Any]]:
    data = get_run(agent_id, run_id)
    status = str(data.get("status") or "")
    if status not in TERMINAL_RUN_STATUSES:
        return
    _trace(
        f"Cursor terminal poll agent={agent_id[-8:]} run={run_id[-8:]} "
        f"status={status}\n{_preview(data, 2000)}"
    )
    yield {
        "event": "result",
        "data": {
            "status": status,
            "text": str(data.get("result") or ""),
        },
    }


def _request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float,
) -> dict[str, Any]:
    if not settings.cursor_api_key.strip():
        raise CursorAgentError("CURSOR_API_KEY не настроен в backend/.env", status_code=500)
    url = f"{settings.cursor_api_base_url.rstrip('/')}{path}"
    _trace(f"Cursor -> {method} {url}")
    if json is not None:
        _trace(f"Cursor request json {method} {path}:\n{_preview(json)}")
    if params is not None:
        _trace(f"Cursor request params {method} {path}:\n{_preview(params)}")
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method,
                url,
                json=json,
                params=params,
                auth=(settings.cursor_api_key, ""),
                headers={"Content-Type": "application/json"},
            )
    except httpx.TimeoutException as exc:
        _trace(f"Cursor ✖ {method} {path} timeout")
        raise CursorAgentError("Превышено время ожидания Cursor API", status_code=504) from exc
    except httpx.HTTPError as exc:
        _trace(f"Cursor ✖ {method} {path} {exc}")
        raise CursorAgentError(f"Ошибка сети Cursor API: {exc}", status_code=502) from exc
    _trace(f"Cursor <- {method} {path} {response.status_code}")
    if response.content:
        try:
            response_body = response.json()
        except ValueError:
            response_body = response.text
        _trace(f"Cursor response body {method} {path}:\n{_preview(response_body)}")
    if response.status_code == 409:
        raise CursorAgentError(
            "Cursor Agent занят, дождитесь завершения текущего ответа", status_code=409
        )
    if response.status_code >= 400:
        body = response.text[:1000]
        raise CursorAgentError(
            f"Cursor API HTTP {response.status_code}: {body}",
            status_code=response.status_code,
        )
    if not response.content:
        return {}
    return response.json()

from __future__ import annotations

import codecs
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx

from app.config import settings


class CursorAgentError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


TERMINAL_RUN_STATUSES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED", "FAILED"}


def get_me() -> dict[str, Any]:
    return _request("GET", "/v1/me", timeout=30.0)


def list_models() -> list[dict[str, Any]]:
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
    data = _request("POST", f"/v1/agents/{agent_id}/runs", json=body, timeout=180.0)
    if isinstance(data, dict) and isinstance(data.get("run"), dict):
        return data["run"]
    return data


def wait_until_run_idle(
    agent_id: str,
    run_id: str,
    *,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Wait until a run reaches any terminal status (not only FINISHED)."""
    started = time.monotonic()
    last: dict[str, Any] = {}
    while True:
        last = get_run(agent_id, run_id)
        if str(last.get("status") or "") in TERMINAL_RUN_STATUSES:
            return last
        if time.monotonic() - started > timeout_seconds:
            raise CursorAgentError(
                "Cursor Agent занят, дождитесь завершения текущего ответа",
                status_code=409,
            )
        time.sleep(1.5)


def create_run_when_ready(
    agent_id: str,
    *,
    prompt: str,
    mode: str | None = "agent",
    images: list[dict[str, str]] | None = None,
    previous_run_id: str = "",
    retries: int = 6,
) -> dict[str, Any]:
    """Create a follow-up run after the previous one is no longer active.

    Cursor Cloud returns HTTP 409 if the same agent still has an open run.
    Streaming can finish (we already have constructor_tool text) a few seconds
    before the run status becomes FINISHED.
    """
    if previous_run_id:
        try:
            wait_until_run_idle(agent_id, previous_run_id, timeout_seconds=90.0)
        except CursorAgentError:
            pass
    delay = 1.0
    last_error: CursorAgentError | None = None
    for _ in range(max(1, retries)):
        try:
            return create_run(agent_id, prompt=prompt, mode=mode, images=images)
        except CursorAgentError as exc:
            last_error = exc
            if exc.status_code != 409:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 8.0)
    if last_error is not None:
        raise last_error
    raise CursorAgentError("Cursor Agent занят, дождитесь завершения текущего ответа", status_code=409)


def get_run(agent_id: str, run_id: str) -> dict[str, Any]:
    return _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}", timeout=45.0)


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


def cancel_run(agent_id: str, run_id: str) -> dict[str, Any]:
    return _request("POST", f"/v1/agents/{agent_id}/runs/{run_id}/cancel", timeout=45.0)


def archive_agent(agent_id: str) -> dict[str, Any]:
    return _request("POST", f"/v1/agents/{agent_id}/archive", json={}, timeout=45.0)


def list_artifacts(agent_id: str) -> list[dict[str, Any]]:
    data = _request("GET", f"/v1/agents/{agent_id}/artifacts", timeout=45.0)
    if isinstance(data, list):
        return data
    return list(data.get("items") or [])


def artifact_download_url(agent_id: str, path: str) -> str:
    data = _request(
        "GET",
        f"/v1/agents/{agent_id}/artifacts/download",
        params={"path": path},
        timeout=45.0,
    )
    return str(data.get("url") or "")


def download_artifact_to(agent_id: str, path: str, dest: str | Path) -> None:
    url = artifact_download_url(agent_id, path)
    if not url:
        raise CursorAgentError(f"Не удалось получить ссылку на артефакт: {path}")
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as raw:
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
                        for event_name, data in _iter_sse_events(response):
                            if should_cancel and should_cancel():
                                try:
                                    cancel_run(agent_id, run_id)
                                except CursorAgentError:
                                    pass
                                return
                            yield {"event": event_name, "data": data}
                            if event_name in {"done", "error", "result"}:
                                return
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


def _iter_sse_events(response: httpx.Response) -> Iterator[tuple[str, dict[str, Any]]]:
    """Читать SSE по маленьким чанкам — иначе think приходит одним куском в конце."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    event_name = "message"
    data_lines: list[str] = []
    carry = ""

    def feed(text: str) -> Iterator[tuple[str, dict[str, Any]]]:
        nonlocal event_name, data_lines, carry
        carry += text
        while "\n" in carry:
            line, carry = carry.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                if data_lines:
                    yield event_name, _parse_sse_data("\n".join(data_lines))
                event_name = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())

    for raw in response.iter_bytes(chunk_size=4096):
        if not raw:
            continue
        # final=False: неполная кириллица на границе чанка ждёт следующий байт,
        # а не превращается в U+FFFD.
        yield from feed(decoder.decode(raw, final=False))
    yield from feed(decoder.decode(b"", final=True))
    if data_lines:
        yield event_name, _parse_sse_data("\n".join(data_lines))


def _parse_sse_data(raw_data: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        data = {"text": raw_data}
    if not isinstance(data, dict):
        return {"value": data}
    return data


def _terminal_result_events(agent_id: str, run_id: str) -> Iterator[dict[str, Any]]:
    data = get_run(agent_id, run_id)
    status = str(data.get("status") or "")
    if status not in TERMINAL_RUN_STATUSES:
        return
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
        raise CursorAgentError("Превышено время ожидания Cursor API", status_code=504) from exc
    except httpx.HTTPError as exc:
        raise CursorAgentError(f"Ошибка сети Cursor API: {exc}", status_code=502) from exc
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

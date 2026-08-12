from __future__ import annotations

import json
from typing import Any, Callable, Iterator

import httpx

from app import config

API_BASE = "https://api.cursor.com/v1"


class RestApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def _auth() -> httpx.Auth:
    key = config.api_key()
    if not key:
        raise RestApiError("CURSOR_API_KEY не задан. Укажите ключ в desktop/.env")
    return httpx.BasicAuth(key, "")


def _client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(base_url=API_BASE, auth=_auth(), timeout=timeout)


def _raise_for_response(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        payload = resp.json()
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("detail")
            or resp.text
            or resp.reason_phrase
        )
    except Exception:  # noqa: BLE001
        message = resp.text or resp.reason_phrase or "API error"
    retryable = resp.status_code in {408, 425, 429, 500, 502, 503, 504}
    raise RestApiError(str(message), status_code=resp.status_code, retryable=retryable)


def get_me() -> dict[str, Any]:
    with _client() as client:
        resp = client.get("/me")
        _raise_for_response(resp)
        return resp.json()


def list_models() -> list[dict[str, Any]]:
    with _client() as client:
        resp = client.get("/models")
        _raise_for_response(resp)
        data = resp.json()
        if isinstance(data, list):
            return data
        items = data.get("items") or data.get("models") or []
        return list(items)


def create_agent(
    *,
    prompt: str,
    model_id: str | None = None,
    repo_url: str | None = None,
    starting_ref: str = "main",
    auto_create_pr: bool = False,
    skip_reviewer_request: bool = True,
    mode: str = "agent",
    name: str | None = None,
    images: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    prompt_body: dict[str, Any] = {"text": prompt}
    if images:
        # Cloud Agents API: up to 5 images, each {data, mimeType} or {url}.
        prompt_body["images"] = images[:5]
    body: dict[str, Any] = {
        "prompt": prompt_body,
        "mode": mode,
        "skipReviewerRequest": skip_reviewer_request,
    }
    if name:
        body["name"] = name[:100]
    if model_id:
        body["model"] = {"id": model_id}
    # GitHub optional and unused by the desktop product; omit repos by default.
    if repo_url:
        body["repos"] = [
            {
                "url": repo_url,
                "startingRef": starting_ref or "main",
            }
        ]
        body["autoCreatePR"] = auto_create_pr

    with _client(timeout=180.0) as client:
        resp = client.post("/agents", json=body)
        _raise_for_response(resp)
        return resp.json()


def create_run(
    agent_id: str,
    *,
    prompt: str,
    mode: str | None = None,
    images: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    prompt_body: dict[str, Any] = {"text": prompt}
    if images:
        prompt_body["images"] = images[:5]
    body: dict[str, Any] = {"prompt": prompt_body}
    if mode:
        body["mode"] = mode
    with _client(timeout=180.0) as client:
        resp = client.post(f"/agents/{agent_id}/runs", json=body)
        _raise_for_response(resp)
        data = resp.json()
        # Create-Run wraps the run object: {"run": {...}}. Unwrap for callers.
        if isinstance(data, dict) and isinstance(data.get("run"), dict):
            return data["run"]
        return data


def get_agent(agent_id: str) -> dict[str, Any]:
    with _client() as client:
        resp = client.get(f"/agents/{agent_id}")
        _raise_for_response(resp)
        return resp.json()


def list_artifacts(agent_id: str) -> list[dict[str, Any]]:
    with _client() as client:
        resp = client.get(f"/agents/{agent_id}/artifacts")
        _raise_for_response(resp)
        data = resp.json()
        if isinstance(data, list):
            return data
        return list(data.get("items") or [])


def artifact_download_url(agent_id: str, path: str) -> str:
    with _client() as client:
        resp = client.get(f"/agents/{agent_id}/artifacts/download", params={"path": path})
        _raise_for_response(resp)
        data = resp.json()
        return str(data.get("url") or "")


def download_artifact_to(agent_id: str, path: str, dest: Any) -> None:
    """Download one artifact (by relative path) to a local destination file."""
    url = artifact_download_url(agent_id, path)
    if not url:
        raise RestApiError(f"Не удалось получить ссылку на артефакт: {path}")
    with httpx.Client(timeout=120.0, follow_redirects=True) as raw:
        with raw.stream("GET", url) as resp:
            _raise_for_response(resp)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)


def list_agents(*, limit: int = 50, include_archived: bool = False) -> dict[str, Any]:
    params = {"limit": limit, "includeArchived": str(include_archived).lower()}
    with _client() as client:
        resp = client.get("/agents", params=params)
        _raise_for_response(resp)
        return resp.json()


def get_run(agent_id: str, run_id: str) -> dict[str, Any]:
    with _client() as client:
        resp = client.get(f"/agents/{agent_id}/runs/{run_id}")
        _raise_for_response(resp)
        return resp.json()


def cancel_run(agent_id: str, run_id: str) -> dict[str, Any]:
    with _client() as client:
        resp = client.post(f"/agents/{agent_id}/runs/{run_id}/cancel")
        _raise_for_response(resp)
        return resp.json()


def iter_run_sse(
    agent_id: str,
    run_id: str,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (event_name, payload) from the run SSE stream."""
    url = f"/agents/{agent_id}/runs/{run_id}/stream"
    headers = {"Accept": "text/event-stream"}
    with _client(timeout=None) as client:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 410:
                raise RestApiError("stream_expired", status_code=410, retryable=False)
            if not resp.is_success:
                # Streaming responses must be read before body access.
                resp.read()
                _raise_for_response(resp)

            event_name = "message"
            data_lines: list[str] = []

            for raw in resp.iter_lines():
                if should_cancel and should_cancel():
                    try:
                        cancel_run(agent_id, run_id)
                    except RestApiError:
                        pass
                    break

                if raw is None:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)

                if line.startswith(":"):
                    continue
                if not line:
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            payload = json.loads(data_str) if data_str else {}
                        except json.JSONDecodeError:
                            payload = {"raw": data_str}
                        if not isinstance(payload, dict):
                            payload = {"value": payload}
                        yield event_name, payload
                        if event_name in {"done", "error"}:
                            return
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                # ignore id: and other fields

            if data_lines:
                data_str = "\n".join(data_lines)
                try:
                    payload = json.loads(data_str) if data_str else {}
                except json.JSONDecodeError:
                    payload = {"raw": data_str}
                if isinstance(payload, dict):
                    yield event_name, payload

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from platform_contracts.tools import ToolInvokeRequest, ToolResult

logger = logging.getLogger(__name__)


class PlatformProxyError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _forward_headers(
    *,
    authorization: str | None,
    run_id: str | None,
    department: str,
    user_id: str,
) -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    if run_id:
        headers["X-Run-Id"] = run_id
    if department:
        headers["X-Department"] = department
    if user_id:
        headers["X-User-Id"] = user_id
    return headers


def _tool_invoke_timeout(tool_name: str) -> float:
    name = (tool_name or "").strip().lower()
    if name.startswith("imap."):
        return 180.0
    if name.startswith("onec."):
        return 120.0
    if name.startswith("com."):
        return 90.0
    if name.startswith("browser."):
        return 120.0
    return 120.0


async def invoke_tool(
    tool_name: str,
    request: ToolInvokeRequest,
    *,
    authorization: str | None = None,
) -> ToolResult:
    """Route tool execution through Agent Runtime (orchestrator), not directly to tools."""
    url = f"{settings.orchestrator_url.rstrip('/')}/api/v1/tools/{tool_name}/invoke"
    headers = _forward_headers(
        authorization=authorization,
        run_id=str(request.run_id) if request.run_id else None,
        department=request.department,
        user_id=request.user_id,
    )
    timeout = _tool_invoke_timeout(tool_name)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=request.model_dump(mode="json"), headers=headers)
    except httpx.ConnectError as exc:
        raise PlatformProxyError("Agent runtime unavailable") from exc
    except httpx.TimeoutException as exc:
        raise PlatformProxyError(f"Agent runtime timeout for tool: {tool_name}") from exc

    if response.status_code >= 400:
        detail = _extract_detail(response)
        raise PlatformProxyError(detail, status_code=response.status_code)

    return ToolResult.model_validate(response.json())


async def proxy_get(service_url: str, path: str, *, authorization: str | None = None) -> dict[str, Any]:
    url = f"{service_url.rstrip('/')}{path}"
    headers = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise PlatformProxyError(f"Service unavailable: {path}") from exc
    if response.status_code >= 400:
        raise PlatformProxyError(_extract_detail(response), status_code=response.status_code)
    return response.json()


async def proxy_post(
    service_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    authorization: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    url = f"{service_url.rstrip('/')}{path}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    if extra_headers:
        headers.update(extra_headers)
    # Sandbox run-all walks many tools and can exceed the default 60s window.
    if timeout is None:
        timeout = 180.0 if "sandbox" in path and "run" in path else 60.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise PlatformProxyError(f"Service unavailable: {path}") from exc
    if response.status_code >= 400:
        raise PlatformProxyError(_extract_detail(response), status_code=response.status_code)
    if not response.content:
        return {}
    return response.json()


async def check_service_health(service_url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{service_url.rstrip('/')}/health")
        if response.status_code >= 400:
            return {"status": "error", "reachable": False}
        data = response.json()
        data["reachable"] = True
        return data
    except httpx.HTTPError:
        return {"status": "unreachable", "reachable": False}


def _extract_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
    except Exception:
        pass
    return f"Upstream error ({response.status_code})"

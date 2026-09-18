"""Forward API calls to LAN constructor-gateway when local ERP/tools fail."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

_PROXY_TOOLS = frozenset(
    {
        "onec.",
        "turboproject.",
        "users.",
    }
)


def gateway_base() -> str:
    return (settings.auth_erp_gateway_url or "").strip().rstrip("/")


def gateway_proxy_enabled() -> bool:
    return bool(gateway_base())


def tool_should_proxy(tool_name: str) -> bool:
    name = (tool_name or "").strip().lower()
    return any(name.startswith(prefix) for prefix in _PROXY_TOOLS)


def proxy_http_json(
    *,
    method: str,
    path: str,
    bearer_token: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    base = gateway_base()
    if not base:
        raise HTTPException(status_code=503, detail="AUTH_ERP_GATEWAY_URL не задан")
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, json=json_body, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Gateway proxy unreachable %s %s: %s", method, url, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Gateway {base} недоступен с backend (порт 7812)",
        ) from exc
    if response.status_code >= 400:
        detail = response.text[:500]
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("detail"):
                detail = str(payload["detail"])
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def proxy_tool_invoke(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    bearer_token: str,
) -> dict[str, Any]:
    return proxy_http_json(
        method="POST",
        path="/api/v1/tools/invoke",
        bearer_token=bearer_token,
        json_body={"tool": tool_name, "arguments": arguments},
        timeout=300.0,
    )

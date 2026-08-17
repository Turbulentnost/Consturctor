"""Fetch readable text from an allowlisted URL via desktop host browser worker."""

from __future__ import annotations

import os
from typing import Any

import httpx

from agent.types import ToolResult

DEFAULT_HOST_URL = "http://127.0.0.1:7830"


def web_fetch(url: str, host_url: str | None = None, timeout_sec: float = 60.0) -> ToolResult:
    tool = "web_fetch"
    target = (url or "").strip()
    if not target:
        return ToolResult.failure(tool, "missing_url", "url is required")

    base = (host_url or os.environ.get("TOOL_DESKTOP_HOST_URL") or DEFAULT_HOST_URL).rstrip("/")
    body: dict[str, Any] = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "payload": {"url": target, "fetch_first": True, "use_session": False},
    }
    invoke_url = f"{base}/api/v1/tools/browser.extract_text/invoke"
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            response = client.post(invoke_url, json=body)
            data = response.json()
    except httpx.HTTPError as exc:
        return ToolResult.failure(tool, "fetch_failed", f"Host unreachable at {base}: {exc}")
    except ValueError:
        return ToolResult.failure(tool, "bad_response", "Invalid JSON from host")

    if not data.get("ok"):
        return ToolResult.failure(tool, "fetch_failed", str(data.get("error") or "fetch failed"))

    payload = data.get("data") or {}
    return ToolResult.success(
        tool,
        {
            "url": payload.get("url") or target,
            "title": payload.get("title") or "",
            "text": payload.get("text") or "",
            "source": payload.get("source") or "http",
        },
    )

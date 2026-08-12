"""Invoke platform tools on unified desktop host (:7830) without JWT."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx

from agent.types import ToolResult

DEFAULT_HOST_URL = "http://127.0.0.1:7830"

# Exposed when AGENT_PLATFORM_TOOLS=1
PLATFORM_TOOL_NAMES = frozenset(
    {
        "imap.search",
        "imap.fetch_message",
        "imap.list_unread",
        "com.list_apps",
        "com.outlook.launch",
        "com.outlook.calendar_list",
        "com.outlook.close",
        "fs.list",
        "fs.read",
        "shell.run",
        "desktop.capabilities",
    }
)


class PlatformToolClient:
    def __init__(self, base_url: str = DEFAULT_HOST_URL, timeout_sec: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def invoke(self, tool_name: str, run_id: str, payload: dict[str, Any] | None = None) -> ToolResult:
        if tool_name not in PLATFORM_TOOL_NAMES:
            return ToolResult.failure(tool_name, "unknown_tool", f"Platform tool not exposed: {tool_name}")

        body = {"run_id": run_id or str(uuid4()), "payload": payload or {}}
        url = f"{self.base_url}/api/v1/tools/{tool_name}/invoke"
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.post(url, json=body)
                data = response.json()
        except httpx.HTTPError as exc:
            return ToolResult.failure(
                tool_name,
                "PLATFORM_UNAVAILABLE",
                f"Desktop host unreachable at {self.base_url}: {exc}",
            )

        if not data.get("ok"):
            return ToolResult.failure(tool_name, "PLATFORM_ERROR", str(data.get("error") or "tool failed"))

        result_data = data.get("data") or {}
        if not isinstance(result_data, dict):
            result_data = {"value": result_data}
        return ToolResult.success(tool_name, result_data)


def default_host_url() -> str:
    return (
        os.environ.get("TOOL_DESKTOP_HOST_URL")
        or os.environ.get("AGENT_PLATFORM_HOST_URL")
        or DEFAULT_HOST_URL
    ).rstrip("/")

"""HTTP client for platform-tool-browser worker (:7824)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from agent.types import ToolResult

DEFAULT_BROWSER_URL = "http://127.0.0.1:7824"

BROWSER_TOOLS = frozenset(
    {
        "browser.open_session",
        "browser.close_session",
        "browser.navigate",
        "browser.snapshot",
        "browser.click",
        "browser.type",
        "browser.fill",
        "browser.wait",
        "browser.tabs",
        "browser.screenshot",
        "browser.extract_text",
    }
)

BROWSER_READ_ONLY = frozenset(
    {
        "browser.snapshot",
        "browser.extract_text",
        "browser.tabs",
    }
)


class BrowserToolClient:
    def __init__(self, base_url: str = DEFAULT_BROWSER_URL, timeout_sec: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def invoke(self, tool_name: str, run_id: str, payload: dict[str, Any] | None = None) -> ToolResult:
        if tool_name not in BROWSER_TOOLS:
            return ToolResult.failure(tool_name, "unknown_tool", f"Unknown browser tool: {tool_name}")

        body: dict[str, Any] = {"payload": payload or {}}
        try:
            body["run_id"] = str(UUID(run_id))
        except ValueError:
            body["payload"] = {**(payload or {}), "run_id": run_id}

        url = f"{self.base_url}/api/v1/tools/{tool_name}/invoke"
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.post(url, json=body)
        except httpx.HTTPError as exc:
            return ToolResult.failure(
                tool_name,
                "BROWSER_UNAVAILABLE",
                f"Browser worker unreachable at {self.base_url}: {exc}",
            )

        if response.status_code == 404:
            return ToolResult.failure(tool_name, "unknown_tool", f"Worker returned 404 for {tool_name}")

        try:
            data = response.json()
        except ValueError:
            return ToolResult.failure(tool_name, "bad_response", response.text[:500])

        if not data.get("ok", False):
            error = data.get("error") or "browser tool failed"
            code = "BROWSER_ERROR"
            if isinstance(error, str) and ":" in error:
                maybe_code, maybe_msg = error.split(":", 1)
                if maybe_code.isupper() or maybe_code.startswith("SESSION"):
                    code = maybe_code.strip()
                    error = maybe_msg.strip()
            return ToolResult.failure(tool_name, code, str(error))

        result_data = data.get("data") or {}
        if not isinstance(result_data, dict):
            result_data = {"value": result_data}
        return ToolResult.success(tool_name, result_data)

    def close_session(self, run_id: str) -> ToolResult:
        return self.invoke("browser.close_session", run_id, {})

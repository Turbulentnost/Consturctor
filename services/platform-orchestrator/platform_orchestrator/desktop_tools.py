from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import httpx

DESKTOP_HOST_PORT = 7830

LEGACY_DESKTOP_PORTS = {"7826", "7827", "7828"}
DESKTOP_TOOL_HINTS: dict[str, str] = {
    str(DESKTOP_HOST_PORT): "Desktop host (com.*, fs.*, imap.*, browser.*, shell native, desktop.*)",
    "7826": "COM (legacy)",
    "7827": "Filesystem (legacy)",
    "7828": "Native shell (legacy)",
}


def is_host_tool(tool_name: str, *, shell_runtime: str = "") -> bool:
    name = (tool_name or "").strip()
    if name.startswith(("com.", "fs.", "desktop.", "imap.", "browser.")):
        return True
    if name.startswith("shell."):
        return (shell_runtime or "").strip().lower() == "native"
    return False


def desktop_tool_port(base_url: str) -> str | None:
    parsed = urlparse(base_url.strip())
    if parsed.port is not None:
        port = str(parsed.port)
        if port in DESKTOP_TOOL_HINTS:
            return port
    return None


def is_desktop_tool_url(base_url: str) -> bool:
    return desktop_tool_port(base_url) is not None


def is_desktop_tool_name(tool_name: str) -> bool:
    return is_host_tool(tool_name, shell_runtime="native") or tool_name.startswith("shell.")


def ensure_desktop_tool_via_launcher(
    *,
    tool_name: str,
    base_url: str,
    launcher_url: str,
    shell_runtime: str = "",
    timeout: float = 45.0,
) -> str | None:
    """Start unified desktop host (:7830) when agent invokes a host tool."""
    url = (launcher_url or "").strip().rstrip("/")
    if not url:
        return None
    if not is_host_tool(tool_name, shell_runtime=shell_runtime):
        if not is_desktop_tool_url(base_url):
            return None
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{url}/api/v1/ensure",
                json={"port": DESKTOP_HOST_PORT, "tool_name": tool_name},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return (
            f"Desktop host launcher unavailable ({url}): {exc}. "
            "Запустите turbobot desktop app или scripts\\start_desktop_host.cmd "
            f"(единый порт {DESKTOP_HOST_PORT})."
        )
    return None


def format_tool_unreachable_error(*, tool_name: str, base_url: str, exc: Exception) -> str:
    port = desktop_tool_port(base_url)
    err = str(exc).strip()
    connection_refused = "111" in err or "Connection refused" in err or "ConnectError" in type(exc).__name__

    if port in DESKTOP_TOOL_HINTS and connection_refused:
        return (
            f"Desktop host offline ({base_url}, {tool_name}): порт {port} не слушает. "
            f"Запустите scripts\\ensure_desktop_tools.cmd "
            f"(поднимает launcher :7829 и COM/FS/shell :7826/:7827/:7828) "
            f"или desktop app / scripts\\start_desktop_host.cmd. "
            f"Логи: logs\\desktop-*.log"
        )

    if port in DESKTOP_TOOL_HINTS:
        return f"Desktop host error ({base_url}, {tool_name}): {err}."

    if connection_refused and (
        tool_name.startswith(("com.", "fs."))
        or (tool_name.startswith("shell.") and "7828" in base_url)
    ):
        return (
            f"Tool service unavailable ({base_url}, {tool_name}): {err}. "
            f"Запустите scripts\\ensure_desktop_tools.cmd на Windows host."
        )

    return f"Tool service unavailable ({base_url}, {tool_name}): {err}"


def parse_host_port(base_url: str) -> tuple[str, int] | None:
    parsed = urlparse(base_url.strip())
    if not parsed.hostname or parsed.port is None:
        match = re.search(r":(\d{4,5})$", parsed.netloc or "")
        if match and parsed.hostname:
            return parsed.hostname, int(match.group(1))
        return None
    return parsed.hostname, parsed.port

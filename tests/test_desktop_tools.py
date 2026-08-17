from __future__ import annotations

import httpx

from platform_orchestrator.desktop_tools import (
    ensure_desktop_tool_via_launcher,
    format_tool_unreachable_error,
    is_desktop_tool_url,
)


def test_is_desktop_tool_url() -> None:
    assert is_desktop_tool_url("http://host.docker.internal:7830")
    assert is_desktop_tool_url("http://127.0.0.1:7827")
    assert not is_desktop_tool_url("http://platform-tool-imap:7821")


def test_format_connection_refused_com() -> None:
    msg = format_tool_unreachable_error(
        tool_name="com.list_apps",
        base_url="http://host.docker.internal:7830",
        exc=httpx.ConnectError("[Errno 111] Connection refused"),
    )
    assert "Desktop host offline" in msg
    assert "7830" in msg


def test_format_generic_tool_error() -> None:
    msg = format_tool_unreachable_error(
        tool_name="imap.search",
        base_url="http://platform-tool-imap:7821",
        exc=httpx.ConnectError("connection failed"),
    )
    assert "Tool service unavailable" in msg


def test_ensure_skips_non_desktop_url() -> None:
    assert (
        ensure_desktop_tool_via_launcher(
            tool_name="imap.search",
            base_url="http://platform-tool-imap:7821",
            launcher_url="http://127.0.0.1:7829",
        )
        is None
    )

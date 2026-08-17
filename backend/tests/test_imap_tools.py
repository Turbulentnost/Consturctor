"""IMAP tool stub/real path smoke tests."""

from __future__ import annotations

from app.services.imap_tools import ImapToolError, imap_configured, invoke_imap


def test_imap_stub_list_unread() -> None:
    if imap_configured():
        # Skip hard assertions about stub when real creds are present.
        result = invoke_imap("imap.list_unread", {"limit": 5})
        assert "uids" in result
        assert result.get("mode") in {"real", "stub"}
        return
    result = invoke_imap("imap.list_unread", {"limit": 2, "user": "omto"})
    assert result["mode"] == "stub"
    assert result["count"] >= 1
    assert 8801 in result["uids"]


def test_imap_stub_fetch_message() -> None:
    if imap_configured():
        return
    result = invoke_imap("imap.fetch_message", {"uid": 8801, "user": "omto"})
    assert result["mode"] == "stub"
    assert "спецификац" in result["subject"].casefold() or "omto" in result["subject"].casefold()
    assert result["body_text"]


def test_imap_unknown_tool() -> None:
    try:
        invoke_imap("imap.unknown", {})
        raise AssertionError("expected ImapToolError")
    except ImapToolError:
        pass

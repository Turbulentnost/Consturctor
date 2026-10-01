"""IMAP tool stub/real path smoke tests."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.imap_tools import ImapToolError, imap_configured, imap_date_token, invoke_imap


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


def test_imap_personal_requires_user_mailbox(monkeypatch) -> None:
    from app.services import imap_tools

    monkeypatch.setattr(imap_tools.settings, "imap_host", "mail.example.local")
    monkeypatch.setattr(imap_tools.settings, "imap_username", "service")
    monkeypatch.setattr(imap_tools.settings, "imap_password", "service-secret")
    try:
        invoke_imap("imap.list_unread", {"limit": 1}, personal=True)
        raise AssertionError("expected ImapToolError")
    except ImapToolError as exc:
        assert "Общий ящик" in str(exc)

    seen: list[tuple[str, str] | None] = []

    def fake_list_unread(args):
        seen.append(imap_tools._mailbox_login.get())
        return {"login": imap_tools._imap_meta()["login"]}

    monkeypatch.setitem(imap_tools.REAL_HANDLERS, "imap.list_unread", fake_list_unread)
    result = invoke_imap(
        "imap.list_unread",
        {"limit": 1},
        user_login="ivanov",
        user_password="pw",
        personal=True,
    )
    assert seen == [("ivanov", "pw")]
    assert result["login"] == "ivanov"
    assert imap_tools._mailbox_login.get() is None


def test_imap_date_token_english_month() -> None:
    assert imap_date_token("2026-09-16") == "16-Sep-2026"
    assert imap_date_token("01.02.2026") == "1-Feb-2026"
    assert imap_date_token("") is None


def test_imap_stub_search_today_headers() -> None:
    if imap_configured():
        return
    today = date.today().isoformat()
    result = invoke_imap("imap.search", {"limit": 2, "user": "omto", "date": today})
    assert result["mode"] == "stub"
    assert result["messages"]
    first = result["messages"][0]
    assert first["from"]
    assert first["subject"]
    assert first["date"]
    assert first["message_id"]
    assert first["uid"]


def test_imap_stub_search_future_since_empty() -> None:
    if imap_configured():
        return
    future = (date.today() + timedelta(days=10)).isoformat()
    result = invoke_imap("imap.search", {"since": future, "user": "omto"})
    assert result["mode"] == "stub"
    assert result["messages"] == []
    assert result["uids"] == []

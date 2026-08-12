from __future__ import annotations

import time

import pytest

from platform_tool_browser.session_manager import BrowserSessionError, BrowserSessionManager


def test_open_reuse_close_stub_session() -> None:
    mgr = BrowserSessionManager(force_stub=True, max_contexts=3, ttl_sec=900)
    run_id = "11111111-1111-1111-1111-111111111111"
    s1 = mgr.open_session(run_id, prefer_stub=True)
    s2 = mgr.open_session(run_id, prefer_stub=True)
    assert s1 is s2
    page = s1.active_page()
    page.goto("https://example.com")
    assert "example.com" in page.url
    assert mgr.close_session(run_id) is True
    with pytest.raises(BrowserSessionError) as exc:
        mgr.get_session(run_id)
    assert exc.value.code == "SESSION_NOT_FOUND"


def test_ttl_evicts_session() -> None:
    mgr = BrowserSessionManager(force_stub=True, max_contexts=3, ttl_sec=0.05)
    run_id = "22222222-2222-2222-2222-222222222222"
    mgr.open_session(run_id, prefer_stub=True)
    time.sleep(0.08)
    with pytest.raises(BrowserSessionError):
        mgr.get_session(run_id)


def test_max_contexts_evicts_oldest() -> None:
    mgr = BrowserSessionManager(force_stub=True, max_contexts=2, ttl_sec=900)
    mgr.open_session("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", prefer_stub=True)
    time.sleep(0.02)
    mgr.open_session("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", prefer_stub=True)
    time.sleep(0.02)
    mgr.open_session("cccccccc-cccc-cccc-cccc-cccccccccccc", prefer_stub=True)
    with pytest.raises(BrowserSessionError):
        mgr.get_session("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert mgr.get_session("cccccccc-cccc-cccc-cccc-cccccccccccc") is not None


def test_resolve_selector_from_ref() -> None:
    mgr = BrowserSessionManager(force_stub=True)
    run_id = "33333333-3333-3333-3333-333333333333"
    session = mgr.open_session(run_id, prefer_stub=True)
    session.refs = {"e2": "#q"}
    assert mgr.resolve_selector(session, ref="e2") == "#q"
    with pytest.raises(BrowserSessionError) as exc:
        mgr.resolve_selector(session, ref="missing")
    assert exc.value.code == "SELECTOR_NOT_FOUND"

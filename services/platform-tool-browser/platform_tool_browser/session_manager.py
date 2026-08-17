"""Ephemeral Playwright browser sessions keyed by run_id."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


class BrowserSessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class StubPage:
    """In-memory page used when Playwright is unavailable or USE_STUBS forces stub sessions."""

    url: str = "about:blank"
    _title: str = "Stub Page"
    _html: str = "<html><body><h1>Stub Page</h1><a href='/'>Home</a><button>OK</button></body></html>"
    elements: list[dict[str, Any]] = field(default_factory=list)

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return self._html

    def goto(self, url: str, **_kwargs: Any) -> None:
        self.url = url
        self._title = urlparse_host(url) or "Stub Page"
        self._html = (
            f"<html><body><h1>{self._title}</h1>"
            f"<a id='link1' href='{url}'>Link</a>"
            f"<input id='q' name='q' type='text' />"
            f"<button id='go'>Go</button>"
            f"<p>Stub content for {url}</p>"
            f"</body></html>"
        )
        self.elements = [
            {"ref": "e1", "role": "link", "name": "Link", "selector": "#link1", "visible": True},
            {"ref": "e2", "role": "textbox", "name": "q", "selector": "#q", "visible": True},
            {"ref": "e3", "role": "button", "name": "Go", "selector": "#go", "visible": True},
        ]

    def click(self, selector: str, **_kwargs: Any) -> None:
        self._title = f"Clicked {selector}"

    def fill(self, selector: str, text: str, **_kwargs: Any) -> None:
        self._html = self._html.replace("Stub content", f"Filled {selector}={text}")

    def type(self, selector: str, text: str, **_kwargs: Any) -> None:
        self.fill(selector, text)

    def wait_for_selector(self, selector: str, **_kwargs: Any) -> None:
        return None

    def wait_for_url(self, url: str, **_kwargs: Any) -> None:
        return None

    def screenshot(self, **_kwargs: Any) -> bytes:
        # Minimal valid 1x1 PNG
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    def locator(self, selector: str) -> "_StubLocator":
        return _StubLocator(self, selector)

    def close(self) -> None:
        return None

    def keyboard(self) -> "_StubKeyboard":
        return _StubKeyboard(self)


class _StubLocator:
    def __init__(self, page: StubPage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def inner_text(self, **_kwargs: Any) -> str:
        return f"Stub text ({self.selector}) from {self.page.url}"

    def click(self, **_kwargs: Any) -> None:
        self.page.click(self.selector)

    def fill(self, text: str, **_kwargs: Any) -> None:
        self.page.fill(self.selector, text)

    def press(self, key: str, **_kwargs: Any) -> None:
        if key.lower() in {"enter", "return"}:
            self.page._title = f"Submitted {self.selector}"


class _StubKeyboard:
    def __init__(self, page: StubPage) -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page._title = f"Key {key}"


class StubContext:
    def __init__(self) -> None:
        self._pages: list[StubPage] = []

    def new_page(self) -> StubPage:
        page = StubPage()
        self._pages.append(page)
        return page

    def close(self) -> None:
        self._pages.clear()


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


@dataclass
class BrowserSession:
    run_id: str
    context: Any
    pages: dict[str, Any] = field(default_factory=dict)
    active_page_id: str = ""
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    refs: dict[str, str] = field(default_factory=dict)
    stub: bool = False

    def touch(self) -> None:
        self.last_used_at = time.time()

    def active_page(self) -> Any:
        if not self.active_page_id or self.active_page_id not in self.pages:
            raise BrowserSessionError("SESSION_NOT_FOUND", "No active page in session")
        return self.pages[self.active_page_id]


BrowserFactory = Callable[[], Any]


class BrowserSessionManager:
    def __init__(
        self,
        *,
        max_contexts: int = 3,
        max_pages_per_session: int = 5,
        ttl_sec: float = 900.0,
        force_stub: bool = False,
        browser_factory: BrowserFactory | None = None,
    ) -> None:
        self.max_contexts = max_contexts
        self.max_pages_per_session = max_pages_per_session
        self.ttl_sec = ttl_sec
        self.force_stub = force_stub
        self._browser_factory = browser_factory
        self._lock = threading.RLock()
        self._sessions: dict[str, BrowserSession] = {}
        self._playwright: Any = None
        self._browser: Any = None
        self._playwright_error: str | None = None

    def _ensure_browser(self) -> Any:
        if self.force_stub:
            raise BrowserSessionError("PLAYWRIGHT_UNAVAILABLE", "Stub-only session manager")
        if self._browser is not None:
            return self._browser
        if self._browser_factory is not None:
            self._browser = self._browser_factory()
            return self._browser
        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            return self._browser
        except Exception as exc:  # pragma: no cover - depends on local playwright
            self._playwright_error = str(exc)
            raise BrowserSessionError(
                "PLAYWRIGHT_UNAVAILABLE",
                f"Playwright unavailable: {exc}",
            ) from exc

    def _evict_expired_unlocked(self, now: float | None = None) -> None:
        now = now or time.time()
        expired = [
            rid
            for rid, session in self._sessions.items()
            if now - session.last_used_at > self.ttl_sec
        ]
        for rid in expired:
            self._close_unlocked(rid)

    def _evict_overflow_unlocked(self) -> None:
        while len(self._sessions) >= self.max_contexts:
            oldest = min(self._sessions.values(), key=lambda s: s.last_used_at)
            self._close_unlocked(oldest.run_id)

    def _close_unlocked(self, run_id: str) -> bool:
        session = self._sessions.pop(run_id, None)
        if session is None:
            return False
        for page in list(session.pages.values()):
            try:
                page.close()
            except Exception:
                pass
        try:
            session.context.close()
        except Exception:
            pass
        return True

    def open_session(self, run_id: str, *, prefer_stub: bool = False) -> BrowserSession:
        with self._lock:
            self._evict_expired_unlocked()
            existing = self._sessions.get(run_id)
            if existing is not None:
                existing.touch()
                return existing

            self._evict_overflow_unlocked()
            stub = prefer_stub or self.force_stub
            if not stub:
                try:
                    browser = self._ensure_browser()
                    context = browser.new_context()
                    page = context.new_page()
                    page_id = "p1"
                    session = BrowserSession(
                        run_id=run_id,
                        context=context,
                        pages={page_id: page},
                        active_page_id=page_id,
                        stub=False,
                    )
                    self._sessions[run_id] = session
                    return session
                except BrowserSessionError:
                    if not prefer_stub and not self.force_stub:
                        # Fall through to stub only when explicitly allowed by caller
                        raise

            context = StubContext()
            page = context.new_page()
            page_id = "p1"
            session = BrowserSession(
                run_id=run_id,
                context=context,
                pages={page_id: page},
                active_page_id=page_id,
                stub=True,
            )
            self._sessions[run_id] = session
            return session

    def get_session(self, run_id: str) -> BrowserSession:
        with self._lock:
            self._evict_expired_unlocked()
            session = self._sessions.get(run_id)
            if session is None:
                raise BrowserSessionError("SESSION_NOT_FOUND", f"No session for run_id={run_id}")
            session.touch()
            return session

    def require_session(self, run_id: str | None, *, auto_open: bool = False, prefer_stub: bool = False) -> BrowserSession:
        if not run_id:
            raise BrowserSessionError("SESSION_NOT_FOUND", "run_id is required for browser session")
        if auto_open:
            return self.open_session(run_id, prefer_stub=prefer_stub)
        return self.get_session(run_id)

    def new_tab(self, run_id: str, *, url: str | None = None) -> dict[str, Any]:
        with self._lock:
            session = self.get_session(run_id)
            if len(session.pages) >= self.max_pages_per_session:
                raise BrowserSessionError(
                    "PAGE_LIMIT",
                    f"Max pages per session is {self.max_pages_per_session}",
                )
            page = session.context.new_page()
            page_id = f"p{len(session.pages) + 1}_{uuid.uuid4().hex[:6]}"
            session.pages[page_id] = page
            session.active_page_id = page_id
            if url:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            session.touch()
            return {"page_id": page_id, "url": getattr(page, "url", "")}

    def switch_tab(self, run_id: str, page_id: str) -> dict[str, Any]:
        with self._lock:
            session = self.get_session(run_id)
            if page_id not in session.pages:
                raise BrowserSessionError("PAGE_NOT_FOUND", f"Unknown page_id={page_id}")
            session.active_page_id = page_id
            page = session.pages[page_id]
            session.touch()
            return {"page_id": page_id, "url": getattr(page, "url", ""), "title": _safe_title(page)}

    def list_tabs(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            session = self.get_session(run_id)
            items = []
            for page_id, page in session.pages.items():
                items.append(
                    {
                        "page_id": page_id,
                        "url": getattr(page, "url", ""),
                        "title": _safe_title(page),
                        "active": page_id == session.active_page_id,
                    }
                )
            return items

    def close_session(self, run_id: str) -> bool:
        with self._lock:
            return self._close_unlocked(run_id)

    def resolve_selector(self, session: BrowserSession, *, selector: str = "", ref: str = "") -> str:
        selector = (selector or "").strip()
        ref = (ref or "").strip()
        if ref:
            mapped = session.refs.get(ref)
            if not mapped:
                raise BrowserSessionError("SELECTOR_NOT_FOUND", f"Unknown ref={ref}; call browser.snapshot first")
            return mapped
        if selector:
            return selector
        raise BrowserSessionError("SELECTOR_NOT_FOUND", "selector or ref is required")

    def shutdown(self) -> None:
        with self._lock:
            for rid in list(self._sessions):
                self._close_unlocked(rid)
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
            self._browser = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
            self._playwright = None


def _safe_title(page: Any) -> str:
    try:
        return page.title()
    except Exception:
        return ""

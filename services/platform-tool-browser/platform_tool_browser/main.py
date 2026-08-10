from __future__ import annotations

import base64
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

_playwright = None
_browser = None
_lock = threading.Lock()
_contexts: list[Any] = []


class BrowserSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-browser"
    api_port: int = 7824
    browser_max_contexts: int = 3
    url_whitelist: str = "localhost,127.0.0.1,turbo-don.ru"
    workspace_root: str = ""


settings = BrowserSettings()


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    allowed = [x.strip().lower() for x in settings.url_whitelist.split(",") if x.strip()]
    return any(host == item or host.endswith(f".{item}") for item in allowed)


def _screenshot_dir(run_id: str | None) -> Path:
    root = settings.workspace_root or os.environ.get("CONSTRUCTOR_WORKSPACE") or "data/workspace"
    path = Path(root) / (str(run_id) if run_id else "default") / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stub_navigate(req: ToolInvokeRequest) -> dict[str, Any]:
    url = str(req.payload.get("url", "https://example.com"))
    return {"summary": f"stub navigate {url}", "url": url, "title": "Stub Page"}


def _stub_screenshot(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub screenshot", "path": "stub.png", "bytes": 0}


def _stub_click(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub click", "selector": req.payload.get("selector", "")}


def _stub_extract_text(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub text", "text": "Stub page text"}


def _ensure_browser():
    global _playwright, _browser
    with _lock:
        if _browser is not None:
            return _browser
        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        return _browser


def _new_page():
    browser = _ensure_browser()
    with _lock:
        if len(_contexts) >= settings.browser_max_contexts:
            ctx = _contexts.pop(0)
            ctx.close()
        context = browser.new_context()
        _contexts.append(context)
        return context.new_page()


def _navigate(req: ToolInvokeRequest) -> dict[str, Any]:
    url = str(req.payload.get("url", "")).strip()
    if not url or not _allowed_url(url):
        raise ValueError("url not allowed")
    page = _new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"summary": page.title(), "url": page.url, "title": page.title()}
    finally:
        page.close()


def _screenshot(req: ToolInvokeRequest) -> dict[str, Any]:
    url = str(req.payload.get("url", "")).strip()
    if not url or not _allowed_url(url):
        raise ValueError("url not allowed")
    page = _new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        png = page.screenshot(full_page=False)
        out = _screenshot_dir(str(req.run_id) if req.run_id else None) / "shot.png"
        out.write_bytes(png)
        return {
            "summary": "screenshot saved",
            "path": str(out),
            "bytes": len(png),
            "base64": base64.b64encode(png).decode("ascii")[:200] + "...",
        }
    finally:
        page.close()


def _click(req: ToolInvokeRequest) -> dict[str, Any]:
    url = str(req.payload.get("url", "")).strip()
    selector = str(req.payload.get("selector", "")).strip()
    if not url or not selector:
        raise ValueError("url and selector required")
    if not _allowed_url(url):
        raise ValueError("url not allowed")
    page = _new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.click(selector, timeout=10000)
        return {"summary": f"clicked {selector}", "url": page.url}
    finally:
        page.close()


def _extract_text(req: ToolInvokeRequest) -> dict[str, Any]:
    url = str(req.payload.get("url", "")).strip()
    selector = str(req.payload.get("selector", "body")).strip() or "body"
    if not url or not _allowed_url(url):
        raise ValueError("url not allowed")
    page = _new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        text = page.locator(selector).inner_text(timeout=10000)
        return {"summary": f"text len={len(text)}", "text": text[:12000]}
    finally:
        page.close()


REAL_HANDLERS = {
    "browser.navigate": _navigate,
    "browser.screenshot": _screenshot,
    "browser.click": _click,
    "browser.extract_text": _extract_text,
}

STUB_HANDLERS = {
    "browser.navigate": _stub_navigate,
    "browser.screenshot": _stub_screenshot,
    "browser.click": _stub_click,
    "browser.extract_text": _stub_extract_text,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()

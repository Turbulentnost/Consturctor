"""Universal site browser powered by Playwright (any URL, JS-rendered pages)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urlparse

from .extract import (
    extract_cards,
    extract_links,
    readable_text,
    summarize_dom,
)

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    PlaywrightTimeout = Exception  # type: ignore[misc, assignment]
    sync_playwright = None  # type: ignore[assignment]


class SiteBrowserError(RuntimeError):
    pass


def _require_playwright() -> None:
    if sync_playwright is None:
        raise SiteBrowserError(
            "Playwright не установлен. Выполните:\n"
            "  pip install -r tools/site_browser_tool/requirements.txt\n"
            "  python -m playwright install chromium"
        )


def _normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise SiteBrowserError("url обязателен")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.netloc:
        raise SiteBrowserError(f"Некорректный url: {url}")
    return value


def open_page(
    url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 45_000,
    wait_until: str = "domcontentloaded",
    wait_selector: str | None = None,
    wait_ms: int = 0,
) -> dict[str, Any]:
    """Open URL in Chromium and return title/text/links/cards."""
    return browse(
        action="open",
        url=url,
        headless=headless,
        timeout_ms=timeout_ms,
        wait_until=wait_until,
        wait_selector=wait_selector,
        wait_ms=wait_ms,
    )


def browse(
    *,
    action: str = "open",
    url: str,
    query: str = "",
    headless: bool = True,
    timeout_ms: int = 45_000,
    wait_until: str = "domcontentloaded",
    wait_selector: str | None = None,
    wait_ms: int = 0,
    input_selector: str | None = None,
    submit_selector: str | None = None,
    item_selector: str | None = None,
    title_selector: str | None = None,
    link_selector: str | None = None,
    text_selector: str | None = None,
    max_items: int = 30,
    max_text_chars: int = 12_000,
) -> dict[str, Any]:
    """
    Actions:
      - open: load URL, return text + links + heuristic cards
      - extract: same as open but emphasize cards (optional selectors)
      - search: type query into page search box (or append ?q=) and extract
    """
    _require_playwright()
    action = (action or "open").strip().lower()
    if action not in {"open", "extract", "search"}:
        raise SiteBrowserError(f"Неизвестное action: {action}")
    target = _normalize_url(url)
    timeout_ms = max(5_000, min(180_000, int(timeout_ms or 45_000)))
    max_items = max(1, min(100, int(max_items or 30)))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1100},
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(target, wait_until=wait_until, timeout=timeout_ms)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            if wait_ms:
                page.wait_for_timeout(int(wait_ms))

            if action == "search":
                _do_search(
                    page,
                    query=query,
                    input_selector=input_selector,
                    submit_selector=submit_selector,
                    timeout_ms=timeout_ms,
                )
                # SPA pages often need a beat after submit.
                page.wait_for_timeout(800)
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=timeout_ms)
                    except PlaywrightTimeout:
                        pass

            final_url = page.url
            title = ""
            try:
                title = (page.title() or "").strip()
            except Exception:
                title = ""

            text = readable_text(page, max_chars=max_text_chars)
            links = extract_links(page, base_url=final_url, limit=40)
            cards = extract_cards(
                page,
                base_url=final_url,
                item_selector=item_selector,
                title_selector=title_selector,
                link_selector=link_selector,
                text_selector=text_selector,
                max_items=max_items,
            )
            dom = summarize_dom(page)
            result = {
                "ok": True,
                "action": action,
                "url": final_url,
                "requested_url": target,
                "title": title,
                "text": text,
                "text_len": len(text),
                "links": links,
                "cards": cards,
                "cards_count": len(cards),
                "dom": dom,
                "query": query or "",
                "engine": "playwright-chromium",
            }
            return result
        except PlaywrightTimeout as exc:
            raise SiteBrowserError(f"Таймаут загрузки {target}: {exc}") from exc
        except SiteBrowserError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SiteBrowserError(f"Ошибка браузера: {exc}") from exc
        finally:
            context.close()
            browser.close()


def _do_search(
    page,
    *,
    query: str,
    input_selector: str | None,
    submit_selector: str | None,
    timeout_ms: int,
) -> None:
    q = (query or "").strip()
    if not q:
        raise SiteBrowserError("для action=search нужен query")

    selectors = []
    if input_selector:
        selectors.append(input_selector)
    selectors.extend(
        [
            "input[type='search']",
            "input[name='search']",
            "input[name='q']",
            "input[name='query']",
            "input[name='text']",
            "input[placeholder*='оиск' i]",
            "input[placeholder*='earch' i]",
            "input[type='text']",
        ]
    )

    box = None
    used_sel = ""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            if not loc.is_visible():
                continue
            box = loc
            used_sel = sel
            break
        except Exception:
            continue

    if box is None:
        # Fallback: rewrite URL with common query params.
        current = page.url
        joiner = "&" if "?" in current else "?"
        page.goto(f"{current}{joiner}q={quote_plus(q)}", wait_until="domcontentloaded", timeout=timeout_ms)
        return

    box.click(timeout=timeout_ms)
    box.fill("")
    box.fill(q)
    if submit_selector:
        try:
            page.locator(submit_selector).first.click(timeout=timeout_ms)
            return
        except Exception:
            pass
    try:
        box.press("Enter")
    except Exception as exc:
        raise SiteBrowserError(
            f"Не удалось отправить поиск (input={used_sel}): {exc}"
        ) from exc

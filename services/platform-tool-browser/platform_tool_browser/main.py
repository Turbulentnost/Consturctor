from __future__ import annotations

import base64
import concurrent.futures
import os
import re
import threading
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

_playwright = None
_browser = None
_lock = threading.Lock()
_contexts: list[Any] = []
_fetch_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="browser-fetch")

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_DDG_LINK = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIPPET = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)>',
    re.IGNORECASE | re.DOTALL,
)


class BrowserSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-browser"
    api_port: int = 7824
    browser_max_contexts: int = 3
    url_whitelist: str = (
        "localhost,127.0.0.1,turbo-don.ru,161.ru,ria.ru,don24.ru,donnews.ru,"
        "yandex.ru,vseinstrumenti.ru,www.vseinstrumenti.ru"
    )
    workspace_root: str = ""
    browser_http_timeout_sec: float = 30.0


settings = BrowserSettings()


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    allowed = [x.strip().lower() for x in settings.url_whitelist.split(",") if x.strip()]
    return any(host == item or host.endswith(f".{item}") for item in allowed)



def _normalize_input_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url.lstrip('/')}"
    host = (urlparse(url).hostname or "").lower()
    if host in _URL_ALIASES:
        return _URL_ALIASES[host]
    return url


def _unwrap_ddg_href(href: str) -> str:
    href = unescape(href.strip())
    if href.startswith("//"):
        href = f"https:{href}"
    if "uddg=" in href:
        parsed = urlparse(href)
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return href


def _web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    max_results = max(1, min(10, max_results))
    with httpx.Client(timeout=settings.browser_http_timeout_sec, follow_redirects=True) as client:
        response = client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": "", "kl": "ru-ru"},
            headers={**_HTTP_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        html = response.text

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _DDG_LINK.finditer(html):
        href = _unwrap_ddg_href(match.group(1))
        title = _strip_tags(match.group(2))
        if not href.startswith(("http://", "https://")):
            continue
        if not title or any(noise in title.lower() for noise in _NOISE_FRAGMENTS):
            continue
        if href in seen:
            continue
        seen.add(href)
        snippet = ""
        tail = html[match.end() : match.end() + 1200]
        snippet_match = _DDG_SNIPPET.search(tail)
        if snippet_match:
            snippet = _strip_tags(snippet_match.group(1))
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _format_search_results(query: str, results: list[dict[str, str]]) -> str:
    lines = [f"Поиск: {query}", f"Найдено: {len(results)}", ""]
    for idx, row in enumerate(results, 1):
        lines.append(f"{idx}. {row['title']}")
        lines.append(f"   {row['url']}")
        if row.get("snippet"):
            lines.append(f"   {row['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()


def _search_and_extract(query: str, max_results: int, fetch_first: bool) -> dict[str, Any]:
    results = _web_search(query, max_results)
    if not results:
        return {
            "summary": "ничего не найдено",
            "query": query,
            "results": [],
            "text": f"По запросу «{query}» результатов не найдено.",
            "source": "search",
        }

    first_url = results[0]["url"]
    first_title = results[0]["title"]
    page_text = ""
    if fetch_first:
        page = _fetch_page_text_sync(first_url, relax_whitelist=True)
        if page.get("source") != "blocked":
            page_text = str(page.get("text") or "").strip()
            first_url = str(page.get("url") or first_url)
            first_title = str(page.get("title") or first_title)

    listing = _format_search_results(query, results)
    text = page_text or listing
    summary = f"search: {len(results)} results"
    if page_text:
        summary += f", fetched first ({len(page_text)} chars)"
    return {
        "summary": summary,
        "query": query,
        "url": first_url,
        "title": first_title,
        "results": results,
        "text": text,
        "source": "search",
    }


_NOISE_FRAGMENTS = (
    "all regions",
    "duckduckgo",
    "smartcaptcha",
    "не робот",
    "подтвердите, что запросы",
    "feedback",
    "подписаться",
    "подписка на цифровую",
)


_URL_ALIASES: dict[str, str] = {
    "всеинструменты.ру": "https://www.vseinstrumenti.ru/",
    "www.всеинструменты.ру": "https://www.vseinstrumenti.ru/",
    "vseinstrumenti.ru": "https://www.vseinstrumenti.ru/",
    "www.vseinstrumenti.ru": "https://www.vseinstrumenti.ru/",
}


def _resolve_browser_url(req: ToolInvokeRequest) -> str:
    return _normalize_input_url(str(req.payload.get("url", "")).strip())


def _strip_tags(fragment: str) -> str:
    text = _HTML_TAG_RE.sub(" ", fragment)
    return unescape(_WS_RE.sub(" ", text).strip())


def _html_to_text(html: str) -> str:
    cleaned = _TAG_RE.sub(" ", html)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned[:12000]


def _extract_readable_text(html: str, url: str) -> str:
    lowered = html.lower()
    if "smartcaptcha" in lowered or "не робот" in lowered or "подтвердите, что запросы" in lowered:
        return (
            "Сайт вернул captcha (автоматический доступ заблокирован). "
            "Для новостей Ростова используйте https://donnews.ru/ или https://161.ru/text/. "
            "Yandex и агрегаторы поиска в sandbox не поддерживаются."
        )

    chunks: list[str] = []
    for pattern in (
        r"<h1[^>]*>(.*?)</h1>",
        r"<h2[^>]*>(.*?)</h2>",
        r"<h3[^>]*>(.*?)</h3>",
        r"<article[^>]*>(.*?)</article>",
        r"<a[^>]+href=[^>]+>(.*?)</a>",
    ):
        for match in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
            text = _strip_tags(match.group(1))
            if len(text) < 12:
                continue
            if any(noise in text.lower() for noise in _NOISE_FRAGMENTS):
                continue
            if text not in chunks:
                chunks.append(text)

    if chunks:
        return "\n".join(f"- {line}" for line in chunks[:25])

    fallback = _html_to_text(html)
    parts = re.split(r"(?<=[.!?])\s+", fallback)
    cleaned: list[str] = []
    for part in parts:
        piece = part.strip()
        if len(piece) < 20:
            continue
        low = piece.lower()
        if any(noise in low for noise in _NOISE_FRAGMENTS):
            continue
        if piece.count(" ") > 25 and len(piece) > 180:
            continue
        cleaned.append(piece)
        if len(cleaned) >= 20:
            break
    if cleaned:
        return "\n".join(f"- {line}" for line in cleaned)
    return fallback[:4000] or f"Не удалось извлечь текст с {url}"


def _site_hint(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "vseinstrumenti" in host or "всеинструменты" in host:
        return (
            "ВсеИнструменты.ру блокирует автоматический доступ (anti-bot). "
            "Для каталога откройте сайт в обычном браузере."
        )
    if "yandex" in host:
        return (
            "Yandex не отдаёт содержимое без браузера/авторизации (captcha или redirect на Dzen/SSO). "
            "В sandbox используйте прямые источники: donnews.ru, 161.ru."
        )
    return "Сайт ограничивает автоматический доступ. Укажите прямой URL новостного источника."


def _blocked_result(url: str, reason: str) -> dict[str, Any]:
    text = f"{reason}\n{_site_hint(url)}"
    host = urlparse(url).hostname or url
    return {
        "summary": "blocked by site",
        "url": url,
        "title": host,
        "text": text,
        "source": "blocked",
    }


def _detect_blocked_html(html: str, url: str, status_code: int) -> str | None:
    lowered = html.lower()
    if status_code in {403, 429, 503}:
        return f"HTTP {status_code}: сайт отклонил запрос."
    if any(token in lowered for token in ("servicepipe", "spinner-loader", "cf-challenge", "ddos-guard")):
        return "Страница защиты от ботов (anti-bot challenge)."
    if len(html) < 8000 and any(
        token in lowered
        for token in ("sso.passport.yandex", "sso.dzen.ru", "yredirect=true", "smartcaptcha", "не робот")
    ):
        return "Страница captcha или redirect (контент недоступен автоматически)."
    visible = _html_to_text(html)
    if len(visible) < 80 and "<body></body>" in lowered.replace(" ", ""):
        return "Пустая страница с JS-redirect — текст недоступен."
    return None


def _fetch_text_http(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=settings.browser_http_timeout_sec, follow_redirects=True) as client:
        response = client.get(url, headers=_HTTP_HEADERS)
        blocked = _detect_blocked_html(response.text, url, response.status_code)
        if blocked:
            return _blocked_result(url, blocked)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
        title = unescape(_WS_RE.sub(" ", title_match.group(1)).strip()) if title_match else url
        text = _extract_readable_text(response.text, url)
    return {
        "summary": f"http fetch ok ({len(text)} chars)",
        "url": url,
        "title": title,
        "text": text,
        "content_type": content_type,
        "source": "http",
    }


def _fetch_in_background(fn, *args):
    future = _fetch_pool.submit(fn, *args)
    return future.result(timeout=settings.browser_http_timeout_sec + 15)


def _screenshot_dir(run_id: str | None) -> Path:
    root = settings.workspace_root or os.environ.get("CONSTRUCTOR_WORKSPACE") or "data/workspace"
    path = Path(root) / (str(run_id) if run_id else "default") / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _fetch_page_text_sync(url: str, selector: str = "body", *, relax_whitelist: bool = False) -> dict[str, Any]:
    if not relax_whitelist and not _allowed_url(url):
        raise ValueError(f"url not allowed: {url}")
    try:
        data = _fetch_text_http(url)
        if data.get("source") == "blocked":
            return data
        return data
    except Exception as http_exc:
        err = str(http_exc)
        if "Executable doesn't exist" in err or "playwright install" in err.lower():
            return _blocked_result(url, f"HTTP не удался ({http_exc}). Playwright в контейнере не установлен.")
        page = None
        try:
            page = _new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            blocked = _detect_blocked_html(html, page.url, 200)
            if blocked:
                return _blocked_result(page.url, blocked)
            text = _extract_readable_text(html, page.url)
            if selector and selector != "body":
                try:
                    text = page.locator(selector).inner_text(timeout=10000)[:12000]
                except Exception:
                    pass
            return {
                "summary": f"playwright text len={len(text)}",
                "url": page.url,
                "title": page.title(),
                "text": text[:12000],
                "source": "playwright",
                "http_error": str(http_exc),
            }
        except Exception as pw_exc:
            return _blocked_result(url, f"Не удалось загрузить страницу: {pw_exc}")
        finally:
            if page is not None:
                page.close()


def _fetch_page_text(url: str, selector: str = "body") -> dict[str, Any]:
    return _fetch_in_background(_fetch_page_text_sync, url, selector)


def _navigate(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _resolve_browser_url(req)
    if not url:
        raise ValueError("url or query required")
    data = _fetch_page_text(url)
    return {
        "summary": data.get("title") or data.get("summary", ""),
        "url": data.get("url", url),
        "title": data.get("title", ""),
        "source": data.get("source", "http"),
    }


def _screenshot(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _resolve_browser_url(req)
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
    url = _resolve_browser_url(req)
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
    url = _normalize_input_url(str(req.payload.get("url", "")).strip())
    query = str(req.payload.get("query") or req.payload.get("topic") or "").strip()
    selector = str(req.payload.get("selector", "body")).strip() or "body"
    max_results = max(1, min(10, int(req.payload.get("max_results", 5))))
    fetch_first = bool(req.payload.get("fetch_first", True))

    if query and not url:
        return _fetch_in_background(_search_and_extract, query, max_results, fetch_first)

    if not url:
        raise ValueError("url or query required")
    if not _allowed_url(url):
        raise ValueError(f"url not allowed: {url}")

    data = _fetch_page_text(url, selector)
    return {
        "summary": data.get("summary") or f"text len={len(data.get('text', ''))}",
        "url": data.get("url", url),
        "title": data.get("title", ""),
        "text": data.get("text", ""),
        "source": data.get("source", "http"),
    }


def _stub_navigate(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _resolve_browser_url(req)
    if url and _allowed_url(url):
        return _navigate(req)
    return {"summary": f"stub navigate {url or 'empty'}", "url": url, "title": "Stub Page"}


def _stub_screenshot(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _resolve_browser_url(req)
    if url and _allowed_url(url):
        return _screenshot(req)
    return {"summary": "stub screenshot", "path": "stub.png", "bytes": 0}


def _stub_click(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub click", "selector": req.payload.get("selector", "")}


def _stub_extract_text(req: ToolInvokeRequest) -> dict[str, Any]:
    return _extract_text(req)


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

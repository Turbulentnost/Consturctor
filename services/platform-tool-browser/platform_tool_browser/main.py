from __future__ import annotations

import base64
import concurrent.futures
import os
import re
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID, uuid4

import httpx
from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app
from platform_tool_browser.session_manager import BrowserSessionError, BrowserSessionManager, StubPage

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

_SNAPSHOT_JS = """
() => {
  const picks = [];
  const nodes = Array.from(document.querySelectorAll(
    'a, button, input, textarea, select, [role="button"], [role="link"], [role="textbox"], [onclick]'
  ));
  let idx = 0;
  for (const el of nodes) {
    if (idx >= 40) break;
    const style = window.getComputedStyle(el);
    const visible = style && style.visibility !== 'hidden' && style.display !== 'none'
      && el.offsetParent !== null;
    const role = el.getAttribute('role')
      || (el.tagName === 'A' ? 'link'
        : el.tagName === 'BUTTON' ? 'button'
        : el.tagName === 'SELECT' ? 'combobox'
        : (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') ? 'textbox'
        : el.tagName.toLowerCase());
    const name = (el.getAttribute('aria-label')
      || el.getAttribute('name')
      || el.getAttribute('placeholder')
      || el.innerText
      || el.value
      || '').trim().slice(0, 80);
    let selector = '';
    if (el.id) selector = '#' + CSS.escape(el.id);
    else if (el.getAttribute('name')) selector = el.tagName.toLowerCase() + '[name="' + el.getAttribute('name') + '"]';
    else if (el.getAttribute('href')) selector = 'a[href="' + el.getAttribute('href') + '"]';
    else selector = el.tagName.toLowerCase() + ':nth-of-type(' + (Array.from(el.parentElement?.children || []).filter(c => c.tagName === el.tagName).indexOf(el) + 1) + ')';
    const ref = 'e' + (++idx);
    picks.push({ ref, role, name, selector, visible: !!visible });
  }
  return picks;
}
"""


class BrowserSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-browser"
    api_port: int = 7824
    browser_max_contexts: int = 3
    browser_max_pages: int = 5
    browser_session_ttl_sec: float = 900.0
    url_whitelist: str = (
        "localhost,127.0.0.1,turbo-don.ru,161.ru,ria.ru,don24.ru,donnews.ru,"
        "yandex.ru,vseinstrumenti.ru,www.vseinstrumenti.ru"
    )
    workspace_root: str = ""
    browser_http_timeout_sec: float = 30.0


settings = BrowserSettings()

_session_manager = BrowserSessionManager(
    max_contexts=settings.browser_max_contexts,
    max_pages_per_session=settings.browser_max_pages,
    ttl_sec=settings.browser_session_ttl_sec,
    force_stub=bool(settings.use_stubs),
)


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
        try:
            # Search hits may be outside whitelist; allow first-hit preview.
            page = _fetch_text_http(first_url)
            if page.get("source") != "blocked":
                page_text = str(page.get("text") or "").strip()
                first_url = str(page.get("url") or first_url)
                first_title = str(page.get("title") or first_title)
        except Exception:
            page_text = ""

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


def _resolve_browser_url(req: ToolInvokeRequest) -> str:
    return _normalize_input_url(str(req.payload.get("url", "")).strip())


def _run_id(req: ToolInvokeRequest) -> str:
    if req.run_id:
        return str(req.run_id)
    raw = str(req.payload.get("run_id") or req.payload.get("session_id") or "").strip()
    if raw:
        return raw
    raise BrowserSessionError("SESSION_NOT_FOUND", "run_id is required")


def _ensure_run_id(req: ToolInvokeRequest) -> str:
    try:
        return _run_id(req)
    except BrowserSessionError:
        return str(uuid4())


def _page_meta(page: Any) -> dict[str, str]:
    try:
        title = page.title()
    except Exception:
        title = ""
    return {"url": getattr(page, "url", "") or "", "title": title}


def _timeout_ms(req: ToolInvokeRequest, default: int = 10000) -> int:
    try:
        return max(100, min(120_000, int(req.payload.get("timeout_ms", default))))
    except (TypeError, ValueError):
        return default


def _open_session(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _ensure_run_id(req)
    prefer_stub = bool(settings.use_stubs)
    try:
        session = _session_manager.open_session(run_id, prefer_stub=prefer_stub)
    except BrowserSessionError:
        session = _session_manager.open_session(run_id, prefer_stub=True)
    page = session.active_page()
    meta = _page_meta(page)
    return {
        "summary": f"session open ({'stub' if session.stub else 'playwright'})",
        "run_id": run_id,
        "session_id": run_id,
        "stub": session.stub,
        **meta,
    }


def _close_session(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _run_id(req)
    closed = _session_manager.close_session(run_id)
    return {
        "summary": "session closed" if closed else "session already closed",
        "run_id": run_id,
        "closed": closed,
    }


def _navigate(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _ensure_run_id(req)
    url = _resolve_browser_url(req)
    if not url:
        raise ValueError("url required")
    if not _allowed_url(url) and not settings.use_stubs:
        raise BrowserSessionError("URL_NOT_ALLOWED", f"url not allowed: {url}")

    prefer_stub = bool(settings.use_stubs) or not _allowed_url(url)
    session = _session_manager.require_session(run_id, auto_open=True, prefer_stub=prefer_stub)
    page = session.active_page()
    timeout = _timeout_ms(req, 30000)

    if session.stub or isinstance(page, StubPage):
        if not _allowed_url(url):
            page.goto(url)
            return {
                "summary": f"stub navigate {url}",
                "run_id": run_id,
                "url": url,
                "title": "Stub Page",
                "source": "stub",
            }
        # Whitelisted URL in stub mode: HTTP fastpath + update stub page state
        try:
            data = _fetch_text_http(url)
            page.goto(url)
            if hasattr(page, "_title"):
                page._title = str(data.get("title") or page._title)
            return {
                "summary": data.get("title") or data.get("summary", ""),
                "run_id": run_id,
                "url": data.get("url", url),
                "title": data.get("title", ""),
                "source": data.get("source", "http"),
            }
        except Exception:
            page.goto(url)
            return {"summary": f"stub navigate {url}", "run_id": run_id, "url": url, "title": page.title(), "source": "stub"}

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception as exc:
        # Fallback to HTTP metadata when Playwright navigation fails
        try:
            data = _fetch_text_http(url)
            return {
                "summary": data.get("title") or data.get("summary", ""),
                "run_id": run_id,
                "url": data.get("url", url),
                "title": data.get("title", ""),
                "source": "http",
                "playwright_error": str(exc),
            }
        except Exception as http_exc:
            raise BrowserSessionError("TIMEOUT", f"navigate failed: {exc}; http: {http_exc}") from exc

    meta = _page_meta(page)
    return {
        "summary": meta["title"] or meta["url"],
        "run_id": run_id,
        "url": meta["url"],
        "title": meta["title"],
        "source": "playwright",
    }


def _snapshot(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _run_id(req)
    session = _session_manager.get_session(run_id)
    page = session.active_page()
    meta = _page_meta(page)

    if session.stub or isinstance(page, StubPage):
        elements = list(getattr(page, "elements", []) or [])
        if not elements:
            elements = [
                {"ref": "e1", "role": "heading", "name": page.title(), "selector": "h1", "visible": True},
            ]
        session.refs = {str(item["ref"]): str(item["selector"]) for item in elements if item.get("ref") and item.get("selector")}
        return {
            "summary": f"snapshot {len(elements)} elements",
            "run_id": run_id,
            **meta,
            "elements": elements,
            "source": "stub",
        }

    try:
        elements = page.evaluate(_SNAPSHOT_JS)
    except Exception as exc:
        raise BrowserSessionError("SNAPSHOT_FAILED", str(exc)) from exc

    session.refs = {
        str(item.get("ref")): str(item.get("selector"))
        for item in elements
        if item.get("ref") and item.get("selector")
    }
    return {
        "summary": f"snapshot {len(elements)} elements",
        "run_id": run_id,
        **meta,
        "elements": elements[:40],
        "source": "playwright",
    }


def _click(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _run_id(req)
    session = _session_manager.get_session(run_id)
    page = session.active_page()
    selector = _session_manager.resolve_selector(
        session,
        selector=str(req.payload.get("selector", "")),
        ref=str(req.payload.get("ref", "")),
    )
    timeout = _timeout_ms(req, 10000)
    # Optional url: only navigate if provided AND page is blank
    url = _resolve_browser_url(req)
    if url and (not getattr(page, "url", None) or getattr(page, "url", "") in {"", "about:blank"}):
        if not _allowed_url(url) and not session.stub:
            raise BrowserSessionError("URL_NOT_ALLOWED", f"url not allowed: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 30000))

    try:
        if hasattr(page, "locator") and not isinstance(page, StubPage):
            page.locator(selector).click(timeout=timeout)
        else:
            page.click(selector, timeout=timeout)
    except BrowserSessionError:
        raise
    except Exception as exc:
        raise BrowserSessionError("SELECTOR_NOT_FOUND", f"click failed for {selector}: {exc}") from exc

    meta = _page_meta(page)
    return {"summary": f"clicked {selector}", "run_id": run_id, "selector": selector, **meta}


def _type(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _run_id(req)
    session = _session_manager.get_session(run_id)
    page = session.active_page()
    selector = _session_manager.resolve_selector(
        session,
        selector=str(req.payload.get("selector", "")),
        ref=str(req.payload.get("ref", "")),
    )
    text = str(req.payload.get("text", ""))
    clear = bool(req.payload.get("clear", True))
    submit = bool(req.payload.get("submit", False))
    timeout = _timeout_ms(req, 10000)
    is_password = "password" in selector.lower() or bool(req.payload.get("password"))

    try:
        if clear:
            if isinstance(page, StubPage):
                page.fill(selector, text)
            else:
                page.fill(selector, text, timeout=timeout)
        else:
            if isinstance(page, StubPage):
                page.type(selector, text)
            else:
                page.type(selector, text, timeout=timeout)
        if submit:
            if isinstance(page, StubPage):
                page.locator(selector).press("Enter")
            else:
                page.locator(selector).press("Enter")
    except BrowserSessionError:
        raise
    except Exception as exc:
        raise BrowserSessionError("SELECTOR_NOT_FOUND", f"type failed for {selector}: {exc}") from exc

    meta = _page_meta(page)
    return {
        "summary": f"typed into {selector}",
        "run_id": run_id,
        "selector": selector,
        "submitted": submit,
        "text_redacted": is_password,
        **meta,
    }


def _fill(req: ToolInvokeRequest) -> dict[str, Any]:
    payload = dict(req.payload)
    payload["clear"] = True
    return _type(req.model_copy(update={"payload": payload}))


def _wait(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _run_id(req)
    session = _session_manager.get_session(run_id)
    page = session.active_page()
    timeout = _timeout_ms(req, 10000)
    selector = str(req.payload.get("selector", "")).strip()
    ref = str(req.payload.get("ref", "")).strip()
    url_glob = str(req.payload.get("url", "")).strip()
    sleep_ms = req.payload.get("sleep_ms")

    try:
        if selector or ref:
            resolved = _session_manager.resolve_selector(session, selector=selector, ref=ref)
            if isinstance(page, StubPage):
                page.wait_for_selector(resolved)
            else:
                page.wait_for_selector(resolved, timeout=timeout)
            waited = f"selector:{resolved}"
        elif url_glob:
            if isinstance(page, StubPage):
                page.wait_for_url(url_glob)
            else:
                page.wait_for_url(url_glob, timeout=timeout)
            waited = f"url:{url_glob}"
        elif sleep_ms is not None:
            time.sleep(max(0, min(30.0, float(sleep_ms) / 1000.0)))
            waited = f"sleep:{sleep_ms}ms"
        else:
            time.sleep(min(timeout / 1000.0, 1.0))
            waited = "timeout"
    except BrowserSessionError:
        raise
    except Exception as exc:
        raise BrowserSessionError("TIMEOUT", str(exc)) from exc

    meta = _page_meta(page)
    return {"summary": f"waited {waited}", "run_id": run_id, "waited": waited, **meta}


def _tabs(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _run_id(req)
    action = str(req.payload.get("action", "list")).strip().lower()
    if action == "new":
        url = _resolve_browser_url(req) or None
        if url and not _allowed_url(url) and not settings.use_stubs:
            raise BrowserSessionError("URL_NOT_ALLOWED", f"url not allowed: {url}")
        info = _session_manager.new_tab(run_id, url=url)
        return {"summary": "tab created", "run_id": run_id, "action": "new", **info}
    if action == "switch":
        page_id = str(req.payload.get("page_id", "")).strip()
        if not page_id:
            raise ValueError("page_id required for switch")
        info = _session_manager.switch_tab(run_id, page_id)
        return {"summary": f"switched to {page_id}", "run_id": run_id, "action": "switch", **info}
    tabs = _session_manager.list_tabs(run_id)
    return {"summary": f"{len(tabs)} tabs", "run_id": run_id, "action": "list", "tabs": tabs}


def _screenshot(req: ToolInvokeRequest) -> dict[str, Any]:
    run_id = _ensure_run_id(req)
    session = _session_manager.require_session(run_id, auto_open=True, prefer_stub=bool(settings.use_stubs))
    page = session.active_page()
    url = _resolve_browser_url(req)
    if url:
        if not _allowed_url(url) and not session.stub:
            raise BrowserSessionError("URL_NOT_ALLOWED", f"url not allowed: {url}")
        current = getattr(page, "url", "") or ""
        if current in {"", "about:blank"} or current != url:
            page.goto(url, wait_until="domcontentloaded", timeout=_timeout_ms(req, 30000))

    png = page.screenshot(full_page=bool(req.payload.get("full_page", False)))
    out = _screenshot_dir(run_id) / "shot.png"
    out.write_bytes(png)
    b64 = base64.b64encode(png).decode("ascii")
    return {
        "summary": "screenshot saved",
        "run_id": run_id,
        "path": str(out),
        "bytes": len(png),
        "base64": b64[:200] + ("..." if len(b64) > 200 else ""),
        **_page_meta(page),
    }


def _extract_from_active_page(session_run_id: str, selector: str) -> dict[str, Any]:
    session = _session_manager.get_session(session_run_id)
    page = session.active_page()
    meta = _page_meta(page)
    if session.stub or isinstance(page, StubPage):
        if selector and selector != "body":
            text = page.locator(selector).inner_text()
        else:
            text = _extract_readable_text(page.content(), meta["url"] or "stub")
        return {
            "summary": f"stub text len={len(text)}",
            "run_id": session_run_id,
            **meta,
            "text": text[:12000],
            "source": "stub",
        }

    if selector and selector != "body":
        try:
            text = page.locator(selector).inner_text(timeout=10000)[:12000]
        except Exception as exc:
            raise BrowserSessionError("SELECTOR_NOT_FOUND", str(exc)) from exc
    else:
        html = page.content()
        blocked = _detect_blocked_html(html, meta["url"], 200)
        if blocked:
            return {**_blocked_result(meta["url"], blocked), "run_id": session_run_id}
        text = _extract_readable_text(html, meta["url"])[:12000]
    return {
        "summary": f"playwright text len={len(text)}",
        "run_id": session_run_id,
        **meta,
        "text": text,
        "source": "playwright",
    }


def _extract_text(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _normalize_input_url(str(req.payload.get("url", "")).strip())
    query = str(req.payload.get("query") or req.payload.get("topic") or "").strip()
    selector = str(req.payload.get("selector", "body")).strip() or "body"
    max_results = max(1, min(10, int(req.payload.get("max_results", 5))))
    fetch_first = bool(req.payload.get("fetch_first", True))
    use_session = bool(req.payload.get("use_session", True))

    if query and not url:
        return _fetch_in_background(_search_and_extract, query, max_results, fetch_first)

    # Prefer active session page when run_id present and no explicit url override needed
    if use_session and req.run_id:
        run_id = str(req.run_id)
        try:
            session = _session_manager.get_session(run_id)
            page_url = getattr(session.active_page(), "url", "") or ""
            if page_url and page_url not in {"about:blank"} and (not url or url == page_url):
                return _extract_from_active_page(run_id, selector)
        except BrowserSessionError:
            pass

    if not url:
        # Try session without url
        if req.run_id:
            return _extract_from_active_page(str(req.run_id), selector)
        raise ValueError("url or query required")

    if not _allowed_url(url):
        raise BrowserSessionError("URL_NOT_ALLOWED", f"url not allowed: {url}")

    # Session navigate then extract when possible
    if use_session:
        run_id = _ensure_run_id(req)
        nav_req = req.model_copy(update={"run_id": UUID(run_id) if _is_uuid(run_id) else req.run_id, "payload": {**req.payload, "url": url}})
        # Ensure session exists via navigate helper
        try:
            _navigate(nav_req if nav_req.run_id else req.model_copy(update={"payload": {**req.payload, "url": url, "run_id": run_id}}))
            return _extract_from_active_page(run_id, selector)
        except Exception:
            pass

    data = _fetch_in_background(_fetch_text_http, url)
    if selector != "body" and data.get("source") == "http":
        # HTTP path cannot honor arbitrary selectors beyond readable extract
        pass
    return {
        "summary": data.get("summary") or f"text len={len(data.get('text', ''))}",
        "url": data.get("url", url),
        "title": data.get("title", ""),
        "text": data.get("text", ""),
        "source": data.get("source", "http"),
    }


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _wrap(handler):
    def _inner(req: ToolInvokeRequest) -> dict[str, Any]:
        try:
            return handler(req)
        except BrowserSessionError as exc:
            raise ValueError(f"{exc.code}: {exc.message}") from exc

    return _inner


# --- stubs (session-aware, no Chromium required) ---

def _stub_open_session(req: ToolInvokeRequest) -> dict[str, Any]:
    return _open_session(req)


def _stub_close_session(req: ToolInvokeRequest) -> dict[str, Any]:
    try:
        return _close_session(req)
    except BrowserSessionError as exc:
        return {"summary": exc.message, "closed": False, "run_id": str(req.run_id or "")}


def _stub_navigate(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _resolve_browser_url(req)
    if url and _allowed_url(url):
        return _navigate(req)
    run_id = _ensure_run_id(req)
    _session_manager.open_session(run_id, prefer_stub=True)
    session = _session_manager.get_session(run_id)
    page = session.active_page()
    if url:
        page.goto(url)
    return {"summary": f"stub navigate {url or 'empty'}", "run_id": run_id, "url": url, "title": "Stub Page", "source": "stub"}


def _stub_screenshot(req: ToolInvokeRequest) -> dict[str, Any]:
    url = _resolve_browser_url(req)
    if url and _allowed_url(url):
        try:
            return _screenshot(req)
        except Exception:
            pass
    run_id = _ensure_run_id(req)
    _session_manager.open_session(run_id, prefer_stub=True)
    return {"summary": "stub screenshot", "run_id": run_id, "path": "stub.png", "bytes": 0}


def _stub_click(req: ToolInvokeRequest) -> dict[str, Any]:
    # Require an existing session (same as real handler) so close_session stays meaningful.
    return _click(req)


def _stub_extract_text(req: ToolInvokeRequest) -> dict[str, Any]:
    return _extract_text(req)


def _stub_snapshot(req: ToolInvokeRequest) -> dict[str, Any]:
    return _snapshot(req)


def _stub_type(req: ToolInvokeRequest) -> dict[str, Any]:
    return _type(req)


def _stub_fill(req: ToolInvokeRequest) -> dict[str, Any]:
    return _fill(req)


def _stub_wait(req: ToolInvokeRequest) -> dict[str, Any]:
    return _wait(req)


def _stub_tabs(req: ToolInvokeRequest) -> dict[str, Any]:
    return _tabs(req)


REAL_HANDLERS = {
    "browser.open_session": _wrap(_open_session),
    "browser.close_session": _wrap(_close_session),
    "browser.navigate": _wrap(_navigate),
    "browser.snapshot": _wrap(_snapshot),
    "browser.click": _wrap(_click),
    "browser.type": _wrap(_type),
    "browser.fill": _wrap(_fill),
    "browser.wait": _wrap(_wait),
    "browser.tabs": _wrap(_tabs),
    "browser.screenshot": _wrap(_screenshot),
    "browser.extract_text": _wrap(_extract_text),
}

STUB_HANDLERS = {
    "browser.open_session": _wrap(_stub_open_session),
    "browser.close_session": _wrap(_stub_close_session),
    "browser.navigate": _wrap(_stub_navigate),
    "browser.snapshot": _wrap(_stub_snapshot),
    "browser.click": _wrap(_stub_click),
    "browser.type": _wrap(_stub_type),
    "browser.fill": _wrap(_stub_fill),
    "browser.wait": _wrap(_stub_wait),
    "browser.tabs": _wrap(_stub_tabs),
    "browser.screenshot": _wrap(_stub_screenshot),
    "browser.extract_text": _wrap(_stub_extract_text),
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()

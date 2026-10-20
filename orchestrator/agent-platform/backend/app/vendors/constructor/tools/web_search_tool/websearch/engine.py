"""Движок веб-поиска и извлечения текста (порт из platform-tool-browser, jalko).

Зависимости: httpx + стандартная библиотека. Без Playwright и без платформенного
фреймворка. Логика:
- `search()` — DuckDuckGo (HTML) с фолбэком на Wikipedia API;
- `fetch_page()` — загрузка страницы и извлечение читаемого текста;
- определение captcha/anti-bot страниц.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

DEFAULT_TIMEOUT_S = 30.0

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

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

_CAPTCHA_MARKERS = (
    "smartcaptcha",
    "не робот",
    "подтвердите, что запросы",
    "sso.passport.yandex",
    "sso.dzen.ru",
    "yredirect=true",
)
_ANTIBOT_MARKERS = ("servicepipe", "spinner-loader", "cf-challenge", "ddos-guard")


@dataclass
class SearchResult:
    """Одна позиция поисковой выдачи."""

    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass
class PageText:
    """Результат загрузки/извлечения текста страницы."""

    url: str
    title: str = ""
    text: str = ""
    source: str = "http"  # http | blocked
    summary: str = ""
    blocked: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "source": self.source,
            "summary": self.summary,
            "blocked": self.blocked,
        }


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url.lstrip('/')}"
    return url


def _unwrap_ddg_href(href: str) -> str:
    """DuckDuckGo оборачивает ссылки в редирект /l/?uddg=<url> — разворачиваем."""
    href = unescape((href or "").strip())
    if href.startswith("//"):
        href = f"https:{href}"
    if "uddg=" in href:
        parsed = urlparse(href)
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return href


def _strip_tags(fragment: str) -> str:
    text = _HTML_TAG_RE.sub(" ", fragment or "")
    return unescape(_WS_RE.sub(" ", text).strip())


def _html_to_text(html: str, *, limit: int = 12000) -> str:
    cleaned = _TAG_RE.sub(" ", html or "")
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned[:limit]


def _is_noise(text: str) -> bool:
    low = text.lower()
    return any(noise in low for noise in _NOISE_FRAGMENTS)


def extract_readable_text(html: str, url: str = "") -> str:
    """Извлечь осмысленный текст: заголовки/статьи/ссылки, иначе — предложения."""
    chunks: list[str] = []
    for pattern in (
        r"<h1[^>]*>(.*?)</h1>",
        r"<h2[^>]*>(.*?)</h2>",
        r"<h3[^>]*>(.*?)</h3>",
        r"<article[^>]*>(.*?)</article>",
        r"<p[^>]*>(.*?)</p>",
    ):
        for match in re.finditer(pattern, html or "", re.IGNORECASE | re.DOTALL):
            text = _strip_tags(match.group(1))
            if len(text) < 12 or _is_noise(text) or text in chunks:
                continue
            chunks.append(text)
    if chunks:
        return "\n".join(f"- {line}" for line in chunks[:25])

    fallback = _html_to_text(html)
    parts = re.split(r"(?<=[.!?])\s+", fallback)
    cleaned: list[str] = []
    for part in parts:
        piece = part.strip()
        if len(piece) < 20 or _is_noise(piece):
            continue
        cleaned.append(piece)
        if len(cleaned) >= 20:
            break
    if cleaned:
        return "\n".join(f"- {line}" for line in cleaned)
    return fallback[:4000] or f"Не удалось извлечь текст с {url}"


def detect_blocked(html: str, status_code: int) -> str | None:
    """Вернуть причину блокировки (captcha/anti-bot), иначе None."""
    lowered = (html or "").lower()
    if status_code in {403, 429, 503}:
        return f"HTTP {status_code}: сайт отклонил запрос."
    if any(token in lowered for token in _ANTIBOT_MARKERS):
        return "Страница защиты от ботов (anti-bot challenge)."
    if any(token in lowered for token in _CAPTCHA_MARKERS):
        return "Страница captcha или redirect (контент недоступен автоматически)."
    return None


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True)


# «Вежливый» User-Agent для сайтов, которые блокируют generic-браузерный UA
# (например, Wikipedia требует описательный UA с контактом).
_POLITE_HEADERS = {
    **_HTTP_HEADERS,
    "User-Agent": "WebSearchTool/1.0 (+https://localhost; contact: admin@localhost)",
}


def fetch_page(url: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> PageText:
    """Загрузить страницу и извлечь читаемый текст."""
    url = _normalize_url(url)
    if not url:
        raise ValueError("url обязателен")
    with _client(timeout) as client:
        response = client.get(url, headers=_HTTP_HEADERS)
        # Часть сайтов (Wikipedia и т.п.) блокируют generic-браузерный UA —
        # повторяем один раз с описательным User-Agent.
        if response.status_code in {403, 429, 503}:
            retry = client.get(url, headers=_POLITE_HEADERS)
            if retry.status_code < 400:
                response = retry
        blocked = detect_blocked(response.text, response.status_code)
        if blocked:
            return PageText(url=url, title=urlparse(url).hostname or url,
                            text=blocked, source="blocked", summary="blocked by site", blocked=True)
        response.raise_for_status()
        title_match = _TITLE_RE.search(response.text)
        title = unescape(_WS_RE.sub(" ", title_match.group(1)).strip()) if title_match else url
        text = extract_readable_text(response.text, url)
    return PageText(
        url=str(response.url),
        title=title,
        text=text,
        source="http",
        summary=f"http fetch ok ({len(text)} chars)",
    )


def parse_ddg_html(html: str, max_results: int = 5) -> list[SearchResult]:
    """Разобрать HTML-выдачу html.duckduckgo.com (чистая функция, без сети)."""
    max_results = max(1, min(20, max_results))
    if "anomaly-modal" in (html or "") or "result__a" not in (html or ""):
        return []
    results: list[SearchResult] = []
    seen: set[str] = set()
    for match in _DDG_LINK.finditer(html):
        href = _unwrap_ddg_href(match.group(1))
        title = _strip_tags(match.group(2))
        if not href.startswith(("http://", "https://")):
            continue
        if not title or _is_noise(title) or href in seen:
            continue
        seen.add(href)
        snippet = ""
        tail = html[match.end(): match.end() + 1200]
        snippet_match = _DDG_SNIPPET.search(tail)
        if snippet_match:
            snippet = _strip_tags(snippet_match.group(1))
        results.append(SearchResult(title=title, url=href, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


def _search_ddg(query: str, max_results: int, timeout: float) -> list[SearchResult]:
    with _client(timeout) as client:
        response = client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": "", "kl": "ru-ru"},
            headers={
                **_HTTP_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://duckduckgo.com/",
            },
        )
        response.raise_for_status()
        html = response.text
    return parse_ddg_html(html, max_results)


def parse_wikipedia_json(data: dict, max_results: int = 5) -> list[SearchResult]:
    """Разобрать ответ MediaWiki search API (чистая функция, без сети)."""
    hits = (data.get("query") or {}).get("search") or []
    results: list[SearchResult] = []
    for hit in hits:
        title = str(hit.get("title") or "").strip()
        if not title:
            continue
        pageid = hit.get("pageid")
        if pageid is not None:
            page_url = f"https://ru.wikipedia.org/?curid={int(pageid)}"
        else:
            page_url = "https://ru.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()%:_")
        results.append(
            SearchResult(title=title, url=page_url, snippet=_strip_tags(str(hit.get("snippet") or "")))
        )
        if len(results) >= max_results:
            break
    return results


def _search_wikipedia(query: str, max_results: int, timeout: float) -> list[SearchResult]:
    api = (
        "https://ru.wikipedia.org/w/api.php"
        f"?action=query&list=search&srsearch={quote(query)}"
        f"&srlimit={max_results}&format=json&utf8=1"
    )
    headers = {
        **_HTTP_HEADERS,
        "User-Agent": "WebSearchTool/1.0 (+https://localhost)",
        "Accept": "application/json",
    }
    try:
        with _client(timeout) as client:
            response = client.get(api, headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    return parse_wikipedia_json(data, max_results)


def search(
    query: str,
    *,
    max_results: int = 5,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> tuple[list[SearchResult], str]:
    """Поиск: DuckDuckGo → Wikipedia (фолбэк). Возвращает (результаты, движок)."""
    query = (query or "").strip()
    if not query:
        raise ValueError("пустой поисковый запрос")
    max_results = max(1, min(20, max_results))
    try:
        ddg = _search_ddg(query, max_results, timeout)
    except httpx.HTTPError:
        ddg = []
    if ddg:
        return ddg, "duckduckgo"
    wiki = _search_wikipedia(query, max_results, timeout)
    if wiki:
        return wiki, "wikipedia"
    return [], "none"


def format_results(query: str, results: list[SearchResult], engine: str = "") -> str:
    """Человекочитаемая выдача."""
    head = f"Поиск: {query}"
    if engine:
        head += f"  (движок: {engine})"
    lines = [head, f"Найдено: {len(results)}", ""]
    for idx, row in enumerate(results, 1):
        lines.append(f"{idx}. {row.title}")
        lines.append(f"   {row.url}")
        if row.snippet:
            lines.append(f"   {row.snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def search_and_extract(
    query: str,
    *,
    max_results: int = 5,
    fetch_first: bool = True,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, object]:
    """Найти и (опционально) загрузить текст первой доступной страницы выдачи."""
    results, engine = search(query, max_results=max_results, timeout=timeout)
    if not results:
        return {
            "summary": "ничего не найдено",
            "query": query,
            "engine": engine,
            "results": [],
            "text": (
                f"По запросу «{query}» результатов не найдено. "
                "DuckDuckGo мог вернуть anti-bot страницу; проверьте запрос "
                "или откройте конкретный URL напрямую."
            ),
        }

    page_text = ""
    first_url = results[0].url
    first_title = results[0].title
    if fetch_first:
        for candidate in results:
            try:
                page = fetch_page(candidate.url, timeout=timeout)
            except httpx.HTTPError:
                continue
            if page.blocked or not page.text.strip():
                continue
            page_text = page.text
            first_url = page.url
            first_title = page.title
            break

    listing = format_results(query, results, engine)
    summary = f"search: {len(results)} результатов через {engine}"
    if page_text:
        summary += f", загружена страница ({len(page_text)} символов)"
    else:
        summary += ", только список (страницы заблокированы/captcha)"
    return {
        "summary": summary,
        "query": query,
        "engine": engine,
        "url": first_url,
        "title": first_title,
        "results": [r.to_dict() for r in results],
        "text": page_text or listing,
    }

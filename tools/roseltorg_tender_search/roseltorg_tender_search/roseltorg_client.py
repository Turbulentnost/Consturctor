"""Поиск закупок на Росэлторг через Playwright (headless Chromium).

Запускается ЛОКАЛЬНО на машине с доступом к www.roseltorg.ru.
Из облачного окружения сайт недоступен (ERR_CONNECTION_RESET).

Клиент максимально устойчив к смене вёрстки: селекторы берутся из config.py,
а извлечение суммы/даты дополнительно подстраховано разбором текста карточки.
"""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from . import config
from .models import Tender

try:  # Playwright импортируется лениво, чтобы тесты без сети не требовали его.
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - окружение без playwright
    sync_playwright = None  # type: ignore[assignment]


_AMOUNT_RE = re.compile(r"\d[\d\s\u00a0.,]*\s*(?:руб|₽|р\.)", re.IGNORECASE)
_DATE_RE = re.compile(r"\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}(?:\s+\d{1,2}:\d{2})?")
_ID_RE = re.compile(r"(?:procedure|procedures)[/=](\d+)")


def build_search_url(query: str) -> str:
    """Собрать URL поиска Росэлторг для одного ключевого слова."""
    parsed = urlparse(config.SEARCH_URL)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    params.append((config.QUERY_PARAM, query))
    new_query = urlencode(params)
    return urlunparse(parsed._replace(query=new_query))


def _first_text(node, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            el = node.query_selector(sel)
        except Exception:
            el = None
        if el:
            txt = (el.inner_text() or "").strip()
            if txt:
                return txt
    return ""


def _extract_amount(node, card_text: str) -> str:
    txt = _first_text(node, config.AMOUNT_SELECTORS)
    if txt:
        return " ".join(txt.split())
    m = _AMOUNT_RE.search(card_text)
    return " ".join(m.group(0).split()) if m else ""


def _extract_deadline(node, card_text: str) -> str:
    """Дата ОКОНЧАНИЯ ПОДАЧИ ЗАЯВОК.

    Приоритет — текст рядом с меткой «Окончание приёма заявок». Если метка не
    найдена, пробуем селекторы дедлайна, затем — первую дату в карточке.
    """
    low = card_text.lower()
    for label in config.DEADLINE_LABELS:
        idx = low.find(label)
        if idx != -1:
            tail = card_text[idx + len(label): idx + len(label) + 40]
            m = _DATE_RE.search(tail)
            if m:
                return m.group(0).strip()
    txt = _first_text(node, config.DEADLINE_SELECTORS)
    if txt:
        m = _DATE_RE.search(txt)
        return m.group(0).strip() if m else " ".join(txt.split())
    m = _DATE_RE.search(card_text)
    return m.group(0).strip() if m else ""


def _extract_cards(page, query: str) -> list[Tender]:
    cards = []
    for sel in config.CARD_SELECTORS:
        try:
            found = page.query_selector_all(sel)
        except Exception:
            found = []
        if found:
            cards = found
            break

    tenders: list[Tender] = []
    for node in cards:
        try:
            card_text = (node.inner_text() or "").strip()
        except Exception:
            card_text = ""
        title = ""
        url = ""
        for sel in config.TITLE_SELECTORS:
            el = node.query_selector(sel)
            if el:
                title = (el.inner_text() or "").strip()
                url = el.get_attribute("href") or ""
                if title:
                    break
        if not title and card_text:
            title = card_text.splitlines()[0].strip()
        if not title:
            continue
        # Site search is fuzzy; keep only cards that actually contain the keyword.
        blob = f"{title}\n{card_text}".casefold()
        q = (query or "").strip().casefold()
        if q and q not in blob:
            continue
        if url and url.startswith("/"):
            url = "https://www.roseltorg.ru" + url
        pid = ""
        m = _ID_RE.search(url)
        if m:
            pid = m.group(1)
        tenders.append(
            Tender(
                title=" ".join(title.split()),
                amount=_extract_amount(node, card_text),
                deadline=_extract_deadline(node, card_text),
                url=url,
                procedure_id=pid,
                matched_queries=[query],
            )
        )
    return tenders


def _goto_next_page(page) -> bool:
    for sel in config.NEXT_PAGE_SELECTORS:
        el = page.query_selector(sel)
        if el:
            try:
                el.click()
                page.wait_for_timeout(config.RESULTS_WAIT_MS)
                return True
            except Exception:
                continue
    return False


def search(queries: list[str], *, headless: bool = True, on_progress=None) -> list[Tender]:
    """Выполнить поиск по списку ключевых слов и вернуть список закупок без дублей.

    on_progress(i, total, query, found_on_query) — необязательный колбэк прогресса.
    """
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright не установлен. Выполните:\n"
            "  pip install -r requirements.txt\n"
            "  python -m playwright install chromium"
        )

    dedup: dict[str, Tender] = {}
    total = len(queries)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=getattr(config, "USER_AGENT", None)
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page.set_default_timeout(config.PAGE_TIMEOUT_MS)
        for i, query in enumerate(queries, start=1):
            found_here = 0
            try:
                page.goto(build_search_url(query), wait_until="domcontentloaded")
                page.wait_for_timeout(config.RESULTS_WAIT_MS)
                body_low = ""
                try:
                    body_low = (page.inner_text("body") or "").casefold()
                except Exception:
                    body_low = ""
                if "web page blocked" in body_low or "has been blocked" in body_low:
                    raise RuntimeError(
                        "Росэлторг заблокировал запрос (WAF). "
                        "Повторите позже или проверьте сеть/прокси."
                    )
                for _ in range(config.MAX_PAGES):
                    for t in _extract_cards(page, query):
                        key = t.dedup_key()
                        if key in dedup:
                            if query not in dedup[key].matched_queries:
                                dedup[key].matched_queries.append(query)
                        else:
                            dedup[key] = t
                            found_here += 1
                    if not _goto_next_page(page):
                        break
            except Exception as exc:  # noqa: BLE001
                if on_progress:
                    on_progress(i, total, f"{query}  [ошибка: {exc}]", found_here)
                continue
            if on_progress:
                on_progress(i, total, query, found_here)
            time.sleep(config.BETWEEN_QUERIES_S)
        context.close()
        browser.close()

    return list(dedup.values())

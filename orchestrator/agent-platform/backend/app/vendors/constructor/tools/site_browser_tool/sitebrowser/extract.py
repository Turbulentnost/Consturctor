from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin

_WS_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(
    r"^(cookie|подписаться|войти|регистрация|меню|навигация|все права)",
    re.IGNORECASE,
)

# Generic repeated-item selectors for list/search pages.
# Prefer specific result/card selectors before broad `li`.
DEFAULT_ITEM_SELECTORS = [
    "[class*='search-result']",
    "[class*='result-item']",
    "[class*='procedure-item']",
    "[class*='procedure']",
    "[class*='tender']",
    "[class*='purchase']",
    "[class*='lot']",
    "[class*='card']",
    "article",
    "[role='listitem']",
    ".item",
    "li",
    ".row",
]


def clean_text(value: str | None) -> str:
    text = _WS_RE.sub(" ", (value or "").replace("\xa0", " ")).strip()
    return text


def is_useful_text(text: str, *, min_len: int = 12) -> bool:
    if len(text) < min_len:
        return False
    if _NOISE_RE.search(text):
        return False
    return True


def pick_best_item_selector(page, candidates: list[str] | None = None) -> str | None:
    """Choose a CSS selector that yields the most plausible repeated cards."""
    best_sel: str | None = None
    best_score = -10_000.0
    for sel in candidates or DEFAULT_ITEM_SELECTORS:
        try:
            nodes = page.query_selector_all(sel)
        except Exception:
            continue
        total = len(nodes)
        if total < 3:
            continue
        lengths: list[int] = []
        useful = 0
        with_proc_link = 0
        for node in nodes[:60]:
            try:
                txt = clean_text(node.inner_text())
            except Exception:
                continue
            if not is_useful_text(txt, min_len=40):
                continue
            useful += 1
            lengths.append(len(txt))
            try:
                html = node.inner_html() or ""
            except Exception:
                html = ""
            if "/procedure" in html or "/tender" in html or "/purchase" in html:
                with_proc_link += 1
        if useful < 3:
            continue
        avg = sum(lengths) / max(1, len(lengths))
        if avg < 60 or avg > 4500:
            continue
        # Prefer medium cards with procedure-like links; penalize huge menus.
        score = useful * 12
        score -= abs(avg - 420) / 15
        score -= max(0, total - 50) * 1.5
        score += with_proc_link * 30
        if with_proc_link == 0 and total > 80:
            score -= 80
        if score > best_score:
            best_score = score
            best_sel = sel
    return best_sel


def extract_cards_from_procedure_links(
    page,
    *,
    base_url: str,
    max_items: int = 30,
) -> list[dict[str, Any]]:
    """Fallback: build cards from anchors that look like tender/procedure links."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        anchors = page.query_selector_all("a[href*='/procedure/'], a[href*='/procedures/']")
    except Exception:
        return []
    for a in anchors:
        try:
            href = urljoin(base_url, (a.get_attribute("href") or "").strip())
            title = clean_text(a.inner_text())
        except Exception:
            continue
        if not href or href in seen:
            continue
        low = href.casefold()
        if "/procedure/" not in low and "/procedures/" not in low:
            continue
        if any(x in low for x in ("tenderplan", "/help", "/login", "/register")):
            continue
        if not is_useful_text(title, min_len=12):
            continue
        # Climb to a reasonably sized parent card.
        body = title
        try:
            parent = a.evaluate_handle(
                """el => {
                  let p = el.parentElement;
                  for (let i = 0; i < 6 && p; i++) {
                    const t = (p.innerText || '').trim();
                    if (t.length >= 80 && t.length <= 2500) return p;
                    p = p.parentElement;
                  }
                  return el.parentElement;
                }"""
            )
            if parent:
                body = clean_text(parent.inner_text()) or title
        except Exception:
            body = title
        seen.add(href)
        cards.append(
            {
                "title": title[:240],
                "url": href,
                "text": body[:2000],
                "selector": "a[href*=procedure]",
            }
        )
        if len(cards) >= max_items:
            break
    return cards


def extract_links(page, *, base_url: str, limit: int = 40) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        anchors = page.query_selector_all("a[href]")
    except Exception:
        return links
    for a in anchors:
        try:
            href = (a.get_attribute("href") or "").strip()
            title = clean_text(a.inner_text())
        except Exception:
            continue
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        if not title:
            title = url
        if not is_useful_text(title, min_len=4) and "http" not in title:
            continue
        links.append({"title": title[:240], "url": url})
        if len(links) >= limit:
            break
    return links


def extract_cards(
    page,
    *,
    base_url: str,
    item_selector: str | None = None,
    title_selector: str | None = None,
    link_selector: str | None = None,
    text_selector: str | None = None,
    max_items: int = 30,
) -> list[dict[str, Any]]:
    sel = item_selector or pick_best_item_selector(page)
    if not sel:
        return extract_cards_from_procedure_links(page, base_url=base_url, max_items=max_items)
    try:
        nodes = page.query_selector_all(sel)
    except Exception:
        return []

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        try:
            full = clean_text(node.inner_text())
        except Exception:
            continue
        if not is_useful_text(full, min_len=20):
            continue

        title = ""
        if title_selector:
            try:
                el = node.query_selector(title_selector)
                if el:
                    title = clean_text(el.inner_text())
            except Exception:
                title = ""
        if not title:
            title = full.split(". ")[0][:180]

        href = ""
        link_sel = link_selector or "a[href]"
        try:
            anchors = node.query_selector_all(link_sel)
        except Exception:
            anchors = []
        best_a = None
        for a in anchors:
            try:
                cand = (a.get_attribute("href") or "").strip()
            except Exception:
                continue
            if not cand:
                continue
            low = cand.casefold()
            if any(x in low for x in ("/procedure", "/tender", "/purchase", "/lot")):
                best_a = a
                break
            if best_a is None:
                best_a = a
        if best_a is not None:
            try:
                href = urljoin(base_url, (best_a.get_attribute("href") or "").strip())
                t2 = clean_text(best_a.inner_text())
                if t2 and (not title or len(t2) > 20):
                    title = t2[:180]
            except Exception:
                href = href or ""

        body = full
        if text_selector:
            try:
                el = node.query_selector(text_selector)
                if el:
                    body = clean_text(el.inner_text()) or full
            except Exception:
                body = full

        key = (href or title[:120]).casefold()
        if not key or key in seen:
            continue
        seen.add(key)

        cards.append(
            {
                "title": title[:240],
                "url": href,
                "text": body[:2000],
                "selector": sel,
            }
        )
        if len(cards) >= max_items:
            break
    # Prefer procedure-link cards when heuristic output is noisy/fragmented.
    fallback = extract_cards_from_procedure_links(page, base_url=base_url, max_items=max_items)
    proc_urls = {
        c["url"]
        for c in cards
        if "/procedure/" in (c.get("url") or "").casefold()
    }
    if fallback and (len(proc_urls) < max(2, len(fallback) // 2) or len(fallback) >= len(cards)):
        return fallback
    return cards


def readable_text(page, *, max_chars: int = 12_000) -> str:
    try:
        raw = page.inner_text("body")
    except Exception:
        try:
            raw = page.content()
        except Exception:
            return ""
    text = clean_text(raw)
    # Keep line structure lightly for lists.
    lines = []
    for line in (raw or "").splitlines():
        cleaned = clean_text(line)
        if is_useful_text(cleaned, min_len=2):
            lines.append(cleaned)
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        return joined[:max_chars] + "\n…[truncated]"
    return joined


def summarize_dom(page) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for sel in DEFAULT_ITEM_SELECTORS:
        try:
            n = len(page.query_selector_all(sel))
        except Exception:
            n = 0
        if n:
            counts[sel] = n
    return {"candidate_counts": dict(counts.most_common(12))}

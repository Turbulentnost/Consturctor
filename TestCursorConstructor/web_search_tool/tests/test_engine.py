"""Оффлайн-тесты движка веб-поиска (без сети)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from websearch.engine import (  # noqa: E402
    SearchResult,
    _html_to_text,
    _strip_tags,
    _unwrap_ddg_href,
    detect_blocked,
    extract_readable_text,
    format_results,
    parse_ddg_html,
    parse_wikipedia_json,
)


def test_strip_tags_removes_markup_and_unescapes():
    assert _strip_tags("<b>Привет</b> &amp; мир") == "Привет & мир"


def test_html_to_text_drops_scripts_and_truncates():
    html = "<script>var x=1;</script><p>Текст</p>"
    out = _html_to_text(html, limit=100)
    assert "var x" not in out
    assert "Текст" in out


def test_unwrap_ddg_href_extracts_uddg():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert _unwrap_ddg_href(href) == "https://example.com/page"


def test_unwrap_ddg_href_passthrough_plain_url():
    assert _unwrap_ddg_href("https://example.com/x") == "https://example.com/x"


def test_parse_ddg_html_extracts_results_and_snippets():
    html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.ru%2F1">Первый</a>
    <td class="result__snippet">Описание первого</td>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fb.ru%2F2">Второй</a>
    <td class="result__snippet">Описание второго</td>
    """
    results = parse_ddg_html(html, max_results=5)
    assert [r.url for r in results] == ["https://a.ru/1", "https://b.ru/2"]
    assert results[0].title == "Первый"
    assert results[0].snippet == "Описание первого"


def test_parse_ddg_html_respects_max_results():
    html = "".join(
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.ru%2F{i}">T{i}</a>'
        for i in range(10)
    )
    assert len(parse_ddg_html(html, max_results=3)) == 3


def test_parse_ddg_html_anomaly_returns_empty():
    assert parse_ddg_html('<div class="anomaly-modal">bot</div>') == []


def test_parse_wikipedia_json_builds_urls():
    data = {"query": {"search": [
        {"title": "Python", "pageid": 42, "snippet": "<span>язык</span>"},
        {"title": "Кот Шрёдингера", "snippet": ""},
    ]}}
    results = parse_wikipedia_json(data, max_results=5)
    assert results[0].url == "https://ru.wikipedia.org/?curid=42"
    assert results[0].snippet == "язык"
    assert "%D0%9A%D0%BE%D1%82" in results[1].url


def test_detect_blocked_captcha():
    assert detect_blocked("<div>SmartCaptcha загрузка</div>", 200) is not None


def test_detect_blocked_http_status():
    assert detect_blocked("<html></html>", 403) is not None


def test_detect_blocked_clean_page():
    assert detect_blocked("<html><body>обычный текст страницы</body></html>", 200) is None


def test_extract_readable_text_prefers_headings():
    html = "<h1>Главный заголовок статьи</h1><p>Небольшой абзац текста здесь.</p>"
    out = extract_readable_text(html)
    assert "Главный заголовок статьи" in out


def test_format_results_renders_lines():
    out = format_results("тест", [SearchResult("Заголовок", "https://x.ru", "сниппет")], "duckduckgo")
    assert "Найдено: 1" in out
    assert "https://x.ru" in out
    assert "duckduckgo" in out

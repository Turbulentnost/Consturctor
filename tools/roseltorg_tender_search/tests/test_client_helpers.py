from urllib.parse import parse_qs, urlparse

from roseltorg_tender_search import config
from roseltorg_tender_search.roseltorg_client import (
    _extract_amount,
    _extract_deadline,
    build_search_url,
)


class _FakeNode:
    """Узел без совпадающих селекторов — заставляет использовать разбор текста."""

    def query_selector(self, _sel):
        return None


def test_build_search_url_keeps_223fz_and_adds_query():
    url = build_search_url("ууг")
    q = parse_qs(urlparse(url).query)
    assert q.get("place") == ["223fz"]
    assert q.get(config.QUERY_PARAM) == ["ууг"]
    assert q.get("source[]") == ["28", "2"]


def test_extract_amount_from_text():
    text = "Реконструкция ГРП\nНачальная цена: 1 200 000,00 руб.\n"
    assert "1 200 000,00" in _extract_amount(_FakeNode(), text)


def test_extract_deadline_prefers_submission_label():
    text = (
        "Дата публикации: 01.08.2026\n"
        "Окончание приема заявок: 15.09.2026 10:00\n"
    )
    got = _extract_deadline(_FakeNode(), text)
    assert got.startswith("15.09.2026")


def test_extract_deadline_falls_back_to_first_date():
    text = "Закупка без метки\n20.09.2026\n"
    assert _extract_deadline(_FakeNode(), text) == "20.09.2026"

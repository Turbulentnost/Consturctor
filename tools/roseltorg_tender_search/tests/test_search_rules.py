from roseltorg_tender_search.keywords import EXCLUDED_LINES, KEYWORD_LINES
from roseltorg_tender_search.search_rules import build_queries, expand_line


def test_comma_splits_into_separate_queries():
    assert expand_line("ууг, пуг, пург, шуург, куург") == [
        "ууг", "пуг", "пург", "шуург", "куург",
    ]


def test_slash_with_shared_prefix():
    assert expand_line("модернизация грп/грс") == [
        "модернизация грп", "модернизация грс",
    ]


def test_slash_standalone_words():
    assert expand_line(
        "модернизация / реконструкция / перевооружение / обновление"
    ) == ["модернизация", "реконструкция", "перевооружение", "обновление"]


def test_plain_line_stays_single():
    assert expand_line("газорегуляторный пункт") == ["газорегуляторный пункт"]


def test_typo_line_excluded_by_default():
    queries = build_queries()
    for bad in EXCLUDED_LINES:
        assert bad not in queries
    # корректная форма присутствует
    assert "система измерения количества и качества газа" in queries


def test_queries_are_unique_and_nonempty():
    queries = build_queries()
    assert queries
    assert len(queries) == len({q.lower() for q in queries})
    assert all(q.strip() for q in queries)


def test_all_lines_covered_except_excluded():
    # Каждая неисключённая строка даёт хотя бы один запрос.
    for line in KEYWORD_LINES:
        if line in EXCLUDED_LINES:
            continue
        assert expand_line(line)

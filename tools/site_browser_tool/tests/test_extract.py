from sitebrowser.extract import clean_text, is_useful_text


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("  a\xa0b\n c  ") == "a b c"


def test_is_useful_text_filters_noise() -> None:
    assert is_useful_text("Поставка бумаги офисной А4")
    assert not is_useful_text("ok")
    assert not is_useful_text("Войти")

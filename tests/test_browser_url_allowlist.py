from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def browser_module(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_browser.main")
    return importlib.reload(module)


def test_allowed_url_includes_ya_ru(browser_module) -> None:
    assert browser_module._allowed_url("https://ya.ru/") is True
    assert browser_module._allowed_url("https://www.ya.ru/search") is True


def test_allowed_url_includes_yandex_and_google(browser_module) -> None:
    assert browser_module._allowed_url("https://yandex.ru/") is True
    assert browser_module._allowed_url("https://www.google.com/search?q=test") is True


def test_allowed_url_rejects_unknown_host(browser_module) -> None:
    assert browser_module._allowed_url("https://example.com/") is False


def test_normalize_ya_ru_alias(browser_module) -> None:
    assert browser_module._normalize_input_url("https://ya.ru/") == "https://yandex.ru/"

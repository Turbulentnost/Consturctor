"""Инструмент веб-поиска и извлечения текста страниц.

Портирован из ветки `jalko` проекта Constructor (сервис `platform-tool-browser`),
переписан как самостоятельный модуль без зависимостей от платформенного
фреймворка. Использует только `httpx` + стандартную библиотеку.

Возможности:
- веб-поиск: DuckDuckGo (HTML) → Wikipedia API (фолбэк);
- загрузка страницы и извлечение читаемого текста;
- определение captcha/anti-bot блокировок.
"""

from .engine import (
    SearchResult,
    fetch_page,
    format_results,
    search,
    search_and_extract,
)

__version__ = "1.0.0"

__all__ = [
    "SearchResult",
    "search",
    "search_and_extract",
    "fetch_page",
    "format_results",
]

"""Конфигурация поиска: URL площадки и CSS-селекторы карточек результатов.

ВАЖНО: Росэлторг — динамический сайт, его вёрстка периодически меняется.
Селекторы вынесены сюда, чтобы их можно было поправить без изменения логики.
Если поиск перестал находить карточки — обнови значения ниже (F12 в браузере).
"""

from __future__ import annotations

# База поиска по 223-ФЗ (source[]=28&source[]=2&place=223fz).
SEARCH_URL = (
    "https://www.roseltorg.ru/procedures/search"
    "?source%5B%5D=28&source%5B%5D=2&place=223fz"
)

# Имя GET-параметра, в который подставляется ключевое слово.
QUERY_PARAM = "search"

# Селекторы карточек результатов. Первый сработавший — используется.
CARD_SELECTORS = [
    "div.search-results__item",
    "div.procedure-card",
    "[data-qa='procedure-card']",
    "div.card",
]

# Внутри карточки: название/ссылка, сумма, дата окончания подачи заявок.
TITLE_SELECTORS = ["a.card__title", "a.procedure-card__title", "a[href*='/procedure']", "a"]
AMOUNT_SELECTORS = [
    "[class*='price']",
    "[class*='sum']",
    "[class*='amount']",
]
# Дата ОКОНЧАНИЯ ПОДАЧИ ЗАЯВОК (не дата публикации!).
DEADLINE_LABELS = [
    "окончание приема заявок",
    "окончание подачи заявок",
    "дата окончания подачи",
    "приём заявок до",
    "прием заявок до",
]
DEADLINE_SELECTORS = [
    "[class*='deadline']",
    "[class*='date-end']",
    "[class*='end-date']",
]

# Пагинация.
NEXT_PAGE_SELECTORS = [
    "a[rel='next']",
    "button[aria-label*=' след']",
    "li.pagination__next a",
    "a.pagination__next",
]
MAX_PAGES = 10

# Таймауты (мс) и задержки.
PAGE_TIMEOUT_MS = 30000
RESULTS_WAIT_MS = 8000
BETWEEN_QUERIES_S = 1.0

# Приёмочная подвыборка (--acceptance): не менее 5 разнотипных запросов.
ACCEPTANCE_QUERIES = [
    "ууг",
    "газорегуляторный пункт",
    "система измерения количества и качества газа",
    "модернизация грс",
    "реконструкция узла учета",
]

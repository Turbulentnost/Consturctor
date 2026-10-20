# web_search_tool

Инструмент веб-поиска и извлечения текста страниц.

Портирован из ветки `jalko` проекта `Constructor` (сервис `platform-tool-browser`)
и переписан как самостоятельный модуль **без** платформенного фреймворка
(`platform_service_common`, `platform_contracts`) и **без** Playwright.
Зависимости: только `httpx` + стандартная библиотека.

## Что умеет

- **Поиск в интернете**: DuckDuckGo (HTML endpoint) с автоматическим фолбэком
  на Wikipedia API, если DuckDuckGo вернул anti-bot/captcha.
- **Загрузка страницы** и извлечение читаемого текста (заголовки, абзацы, статьи).
- **Определение блокировок** (captcha, anti-bot, HTTP 403/429/503).
- `search_and_extract` — поиск + подгрузка текста первой доступной страницы выдачи.

> Что НЕ перенесено: интерактивная Playwright-сессия (`browser.navigate/click/type/
> snapshot/screenshot`) из исходного сервиса. Она требует Playwright и платформенной
> обвязки. Если нужен интерактивный браузер — скажите, добавлю отдельным слоем.

## Установка

```bat
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## CLI

```bat
:: поиск
python -m websearch search "закупки росэлторг" -n 5

:: поиск + текст первой страницы
python -m websearch search "новости ростов" --extract

:: загрузить конкретную страницу
python -m websearch fetch https://ru.wikipedia.org/wiki/Python

:: JSON-вывод
python -m websearch --json search "python asyncio" -n 3
```

Или через лаунчер (сам создаёт venv и ставит зависимости):

```bat
run.bat search "закупки росэлторг" -n 5
```

## Python API

```python
from websearch import search, search_and_extract, fetch_page, format_results

results, engine = search("python asyncio", max_results=5)
print(format_results("python asyncio", results, engine))

data = search_and_extract("новости ростов", max_results=5)
print(data["summary"])
print(data["text"])

page = fetch_page("https://ru.wikipedia.org/wiki/Python")
print(page.title, page.source)
```

## Тесты (офлайн, без сети)

```bat
.venv\Scripts\python.exe -m pytest tests -q
```

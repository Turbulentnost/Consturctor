# site_browser_tool

Универсальный парсер **любого сайта** через Playwright Chromium.

В отличие от `web_search_tool` (httpx, без JS) умеет:
- открывать SPA / JS-страницы;
- ждать отрисовки;
- искать по полю на сайте;
- эвристически вытаскивать карточки/списки без точных селекторов;
- принимать явные CSS-селекторы, если они известны.

## Установка

```powershell
cd tools\site_browser_tool
pip install -r requirements.txt
python -m playwright install chromium
```

Или через `run.bat` (сам создаст venv).

## CLI

```powershell
# открыть URL
python -m sitebrowser open https://example.com

# карточки со страницы списка
python -m sitebrowser extract https://www.roseltorg.ru/procedures/search --wait-ms 1500

# поиск на сайте
python -m sitebrowser search https://www.roseltorg.ru/procedures/search "бумага" --wait-ms 2000

# JSON
python -m sitebrowser --json open https://example.com
```

## Python API

```python
from sitebrowser import browse

data = browse(action="open", url="https://example.com")
print(data["title"], data["cards_count"])

data = browse(
    action="search",
    url="https://www.roseltorg.ru/procedures/search",
    query="бумага",
    wait_ms=2000,
    max_items=20,
)
for card in data["cards"]:
    print(card["title"], card["url"])
```

## Backend / MCP

Инструмент доступен агенту как `site_browser` через `local_mcp`
(`backend/app/services/local_mcp.py`).

## Важно

- Запускать нужно **локально** (на машине с доступом к сайту).
- Cloud VM Cursor часто не достучится до ЭТП — это нормально.
- Для сложных сайтов лучше передать `item_selector` / `input_selector`.

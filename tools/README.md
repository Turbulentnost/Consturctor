# Tools

Локальные CLI-инструменты. **Исполнение при запуске агента — на desktop**
(через SSE `tool_request` → `desktop/app/tools`). Backend только оркестрирует;
исключение — **IMAP** (сервер).

## roseltorg_tender_search

Поиск тендеров на roseltorg.ru (Playwright + Excel). Вызывается desktop-tool
`plan_export`.

```powershell
cd tools\roseltorg_tender_search
pip install -r requirements.txt
python -m playwright install chromium
.\run.bat
```

## web_search_tool

Веб-поиск (DuckDuckGo / Wikipedia). Desktop-tool `web_search`.

```powershell
cd tools\web_search_tool
pip install -r requirements.txt
python -m websearch "запрос"
```

## site_browser_tool

Парсер сайтов (Playwright). Desktop-tool `site_browser`.

```powershell
cd tools\site_browser_tool
pip install -r requirements.txt
python -m playwright install chromium
python -m sitebrowser open https://example.com
```

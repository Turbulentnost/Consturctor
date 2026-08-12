# Tools

Локальные CLI-инструменты для workflow constructor.

## roseltorg_tender_search

Поиск тендеров на roseltorg.ru (Playwright + Excel).

```powershell
cd tools\roseltorg_tender_search
pip install -r requirements.txt
python -m playwright install chromium
.\run.bat
```

В desktop: «Мои workflow» → «Привязать roseltorg» → «Запустить локально».

## web_search_tool

Веб-поиск (DuckDuckGo / Wikipedia). Также доступен через backend:

`POST /api/v1/tools/web-search`

```powershell
cd tools\web_search_tool
pip install -r requirements.txt
python -m websearch "запрос"
```

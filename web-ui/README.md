# Constructor Web UI

Веб-версия desktop-конструктора для быстрых правок UI без PySide6.

**URL:** http://127.0.0.1:8780/

## Запуск

```cmd
rem 1. Backend с 1С на http://192.168.1.157:7812
cd Consturctor\backend
py -3.12 -m app.main

rem 2. Web UI
cd Consturctor\web-ui
start.cmd
```

## Структура (редактируйте напрямую)

| Файл | Содержание |
|------|------------|
| `index.html` | Разметка: login, sidebar, страницы |
| `style.css` | Emerald-тема как в desktop |
| `api.js` | HTTP-клиент к backend через прокси |
| `app.js` | Роутинг и логика страниц |
| `server.py` | Статика + прокси `/api/gateway/*` → backend |

Прокси избавляет от CORS — frontend всегда ходит на тот же origin (`8780`).

## Страницы MVP

- **Вход / регистрация** — как в desktop
- **Создать** — загрузка регламента (PDF/DOCX)
- **Обзор** — результат парсинга
- **Роль** — approve/reject функций
- **Мои агенты** — черновики и опубликованные workflow
- **KPI** — сводка и карточки метрик
- **Настройки** — профиль и отдел

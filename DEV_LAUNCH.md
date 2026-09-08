# Запуск Constructor (dev) — ветка orchestrator

Текущая рабочая версия: **Electron-клиент** + **Python backend**.  
Корень репозитория для запуска:

```
c:\Users\mdj\Desktop\конструктор\orchestrator
```

> **Не запускайте** копию из `orchestrator\orchestrator\` — там другой порт Vite (5176) и устаревшие настройки.

---

## Что куда ходит

| Компонент | Где запускается | Адрес |
|-----------|-----------------|--------|
| Backend API | ваш ПК | `http://127.0.0.1:7812` |
| Electron UI (Vite) | ваш ПК | `http://127.0.0.1:5173` |
| Postgres (пользователи, сессии) | сервер **ii1** | `192.168.1.157:5435` |
| ERP SQL (логин 1С) | сервер **ii1** | `192.168.1.157` / `erp_pm` |

Backend слушает локально, но **базы данных** — на 157. Это нормально.

---

## Требования

- **Python 3.12** (`py -3.12`)
- **Node.js** + npm (для `desktop-electron`)
- Доступ к сети **192.168.1.157** (VPN/офис)
- Учётная запись 1С в `erp_pm` (ФИО + пароль)

---

## Первичная настройка (один раз)

### 1. Backend

```bat
cd c:\Users\mdj\Desktop\конструктор\orchestrator\backend
copy .env.example .env
```

В `backend\.env` должны быть (минимум):

```env
ERP_SQL_SERVER=192.168.1.157
ERP_SQL_DATABASE=erp_pm
ERP_SQL_USER=TURBO-DON\ваш_логин
ERP_SQL_PASSWORD=...

DATABASE_URL=postgresql+psycopg://constructor:constructor@192.168.1.157:5435/constructor
```

Установка зависимостей Python — по `backend/README.md` (pip/poetry проекта).

### 2. Electron

```bat
cd c:\Users\mdj\Desktop\конструктор\orchestrator\desktop-electron
npm install
```

### 3. Sidecar / desktop tools

Файл `desktop\.env` — для локального агента (Outlook, COM, CURSOR_API_KEY):

```env
BACKEND_URL=http://127.0.0.1:7812
```

При первом входе Electron может скопировать `.env` в профиль пользователя.  
Если в логе видите `Constructor backend: http://192.168.1.157:7812` — исправьте:

- `%APPDATA%\constructor-desktop-electron\.env`
- `%APPDATA%\Orchestrator\.env`

и перезапустите Electron.

---

## Ежедневный запуск (2 окна cmd)

### Окно 1 — Backend

```bat
cd c:\Users\mdj\Desktop\конструктор\orchestrator\backend
run_dev.bat
```

Ожидаемый вывод:

```
Starting orchestrator backend on 0.0.0.0:7812 ...
Application startup complete.
```

Проверка:

```bat
curl http://127.0.0.1:7812/health
```

Ответ: `{"status":"ok","erp_reachable":true,...}`

### Окно 2 — Electron (Constructor)

```bat
cd c:\Users\mdj\Desktop\конструктор\orchestrator\desktop-electron
run_dev.bat
```

Ожидаемый вывод:

```
Backend: http://127.0.0.1:7812
Vite:    5173
...
Constructor backend: http://127.0.0.1:7812
```

Откроется окно **Constructor** → вход через ФИО и пароль 1С.

---

## Порядок важен

1. Сначала **backend** (`run_dev.bat` в `backend\`)
2. Потом **Electron** (`run_dev.bat` в `desktop-electron\`)

После правок в `desktop-electron\src\` достаточно перезапустить Electron (или Ctrl+R в окне).  
После правок в `backend\app\` — перезапустить backend.

---

## Типичные проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| «Не удалось подключиться к backend (192.168.1.157:7812)» | Старый `BACKEND_URL` в профиле Electron | Поставить `http://127.0.0.1:7812` в `run_dev.bat`, `desktop\.env`, `%APPDATA%\constructor-desktop-electron\.env` |
| Зелёный экран без кнопок | Падение React (часто после merge) | `npm run typecheck` в `desktop-electron`, смотреть DevTools (Ctrl+Shift+I) |
| Backend не стартует, `ImportError` | Сломанный merge в Python | Смотреть traceback, чинить импорты в `backend\app\` |
| `Port 5173 is already in use` | Старый Vite/Electron | Закрыть процесс на 5173 или убить Electron |
| `Port 5176` в логе | Запуск из **неправильной** папки | Только `orchestrator\desktop-electron\`, не `orchestrator\orchestrator\` |
| ERP недоступен | Нет VPN / нет доступа к 157 | Проверить сеть, `curl http://127.0.0.1:7812/health` → `erp_reachable` |

---

## Release (exe / установщик)

Сборка **не нужна** для ежедневной разработки.  
Exe и установщик — только по явному запросу:

- `desktop-electron\scripts\build_installer.py`
- не копировать exe на Desktop автоматически после каждой правки UI

---

## Полезные команды

```bat
REM TypeScript-проверка UI
cd desktop-electron
npm run typecheck

REM Проверка, кто слушает порты
netstat -ano | findstr ":7812 :5173"
```

---

## Структура (кратко)

```
orchestrator/
├── backend/              ← API :7812, run_dev.bat
├── desktop-electron/     ← Electron UI, run_dev.bat (порт 5173)
├── desktop/              ← Python tools, sidecar, COM/Outlook
│   └── .env              ← BACKEND_URL для sidecar
└── DEV_LAUNCH.md         ← этот файл
```

# Руководство для агента-разработчика (Constructor Platform)

**Начните отсюда**, если вы — внешний ИИ-агент или разработчик, который создаёт других агентов и должен понять, **где что лежит**, **откуда берётся каждая часть системы** и **как правильно работать с 1С ERP**.

---

## 1. Карта документации

| Документ | Для кого | Содержание |
|----------|----------|------------|
| **[AGENT_BUILDER.md](AGENT_BUILDER.md)** *(этот файл)* | Агент-разработчик | Карта репо, tools, API, 1С ERP (OData vs COM), запуск |
| **[ACT_REGISTRY.md](ACT_REGISTRY.md)** | ACT-реестр | Регламент агента: OData, tools, Excel построчно, скрипты, TODO |
| [AGENT_INTERACTION.md](AGENT_INTERACTION.md) | Рабочий агент | Граница: задачи агента ≠ tools ≠ KPI |
| [PLATFORM.md](PLATFORM.md) | DevOps | Docker, порты, скрипты, тесты |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Архитектор | Gateway → Runtime → RabbitMQ → workers |
| [README.md](README.md) | Обзор | MVP desktop + backend |

**Demo UI (sandbox):** [`platform-demo-ui/`](platform-demo-ui/) → http://127.0.0.1:8790/

---

## 2. Карта репозитория

```
Consturctor/
├── backend/                              # Gateway :7812
│   ├── app/api/v1/tools.py               # GET /tools, POST /tools/{name}/invoke
│   ├── app/api/v1/cron_jobs.py           # CRUD cron-задач (прокси в orchestrator)
│   └── data/tool_manifest.json           # ACL tools по отделу
│
├── services/
│   ├── platform-orchestrator/            # Agent Runtime :7825
│   │   ├── service.py                    # Маршрутизация tool → URL
│   │   ├── cron_jobs.py                # Шаблоны daily_tasks, daily_mail
│   │   └── desktop_tools.py            # Подсказки по host-портам
│   │
│   ├── platform-tool-imap/               # :7821  imap.*
│   ├── platform-tool-onec/               # :7822  onec.odata_* / onec.sql_*
│   ├── platform-tool-onec-com/           # :7831  onec.com.*  (32-bit Python, Windows)
│   ├── platform-tool-shell/              # :7823 sandbox, :7828 native
│   ├── platform-tool-browser/            # :7824  browser.*
│   ├── platform-tool-com/                # :7826  com.* (Outlook, legacy onec bridge)
│   ├── platform-tool-filesystem/         # :7827  fs.*
│   ├── platform-desktop-launcher/        # :7829  spawn desktop host tools
│   └── platform-kpi/                     # :7820  KPI
│
├── platform-contracts/                   # ToolInvokeRequest, cron schemas
├── platform-service-common/              # create_tool_app()
├── platform-db/                          # SQLAlchemy, scheduled_jobs
│
├── infra/
│   ├── docker-compose.yml                # TOOL_*_URL, USE_STUBS
│   ├── .env.example                      # IMAP, OData, ONEC_COM_*, desktop URLs
│   └── postgres/init/
│       ├── 01-schemas.sql                # tool_registry seed
│       ├── 02-agent-cards.sql
│       └── 03-cron-jobs.sql              # platform_core.scheduled_jobs
│
├── scripts/
│   ├── docker_up.cmd
│   ├── ensure_com_python.cmd             # Python 3.12 32-bit + pywin32 для 1C COM
│   ├── start_onec_com_service.cmd        # platform-tool-onec-com :7831
│   ├── start_host_network_tools.cmd      # unified desktop host :7830
│   └── smoke_onec_com.py                 # smoke onec.com.*
│
└── tests/                                # pytest контрактов и stub tools
```

---

## 3. Источники правды (три слоя)

| Слой | Источник | Кто решает |
|------|----------|------------|
| **Задачи агента** | `agent_cards.tasks_json` | Разработчик агента |
| **Tools** | `tool_registry` + `tool_manifest.json` | Платформа |
| **KPI** | `agent_cards.kpi_metrics_json` | Платформа считает, агент отчитывается |

Платформа **не** связывает бизнес-задачу агента с конкретным tool. Агент сам выбирает `imap.search`, `onec.com.query_tasks` и т.д.

### Цепочка вызова tool

```
POST /api/v1/tools/{name}/invoke  + JWT
  → Gateway (ACL)
  → Orchestrator :7825 (_tool_url)
  → Worker (real или stub handler)
  → ToolResult { ok, data, error, audit_id }
```

---

## 4. 1С ERP: OData и COM — не путать

| Способ | Tools | Где | Для чего |
|--------|-------|-----|----------|
| **OData REST** | `onec.odata_get/post/patch`, `onec.attach_file` | Docker :7822 | Документы, справочники, массовые выборки по HTTP |
| **COM (ERP-сессия)** | `onec.com.*` | Windows :7831, **32-bit Python** | Задачи пользователя, запросы 1С, контекст сеанса ERP |

### Критично для COM

1. **Тонкий клиент 1С (`1cv8c.exe`) — 32-bit.** COM работает только из **Python 3.12 32-bit** + **pywin32**.
2. **Строка подключения — ragent, не OData URL.**
   - ✅ `ONEC_COM_SERVER=192.168.2.229` (без `:81`)
   - ❌ `192.168.2.229:81` — это HTTP OData, COM Connect упадёт
3. **ProgID:** `V83.COMConnector` → `Connect(conn)` → объект сеанса ERP.
4. **Запросы:** использовать `query.Execute().Unload()` или `.Select()`, **не** `.Choose().Select()` (вернёт 0 строк).
5. **OData `Task_ЗадачаИсполнителя`** и **COM `Задача.ЗадачаИсполнителя`** — разные транспорты; для «моих задач» предпочтителен COM.

### Переменные `infra/.env`

```env
# OData (документооборот, HTTP :81)
ODATA_BASE_URL=http://192.168.2.229:81/erp_pm/odata/standard.odata
ODATA_USERNAME=odata.user
ODATA_PASSWORD=...

# COM ERP (ragent, отдельная сессия)
ONEC_COM_SERVER=192.168.2.229
ONEC_COM_REF=erp_pm
ONEC_COM_PROGID=V83.COMConnector
ERP_LOGIN="ФИО пользователя 1С"
ERP_PASSWORD=...
TOOL_ONEC_COM_URL=http://host.docker.internal:7831
```

### Установка COM на Windows

```cmd
scripts\ensure_com_python.cmd      :: Python 3.12-32 + pywin32 + пакеты
regsvr32 /s "C:\Program Files (x86)\1cv8\...\bin\comcntr.dll"   :: от администратора
scripts\start_onec_com_service.cmd
py scripts\smoke_onec_com.py
```

---

## 5. Каталог tools

### 5.1. Сводная таблица

| Tool | Назначение | Где | Порт |
|------|------------|-----|------|
| `imap.*` | Почта IMAP | Docker / host :7830 | 7821 / 7830 |
| `onec.odata_*`, `onec.sql_query` | OData / SQL | Docker | 7822 |
| **`onec.com.status`** | Статус COM-сервиса | **Windows 32-bit** | **7831** |
| **`onec.com.connect`** | Подключение к ERP через COMConnector | **Windows 32-bit** | **7831** |
| **`onec.com.query_tasks`** | **Мои задачи** (запрос 1С, не OData) | **Windows 32-bit** | **7831** |
| **`onec.com.invoke`** | Вызов метода COM-сессии | **Windows 32-bit** | **7831** |
| **`onec.com.release`** | Закрыть COM-сессию | **Windows 32-bit** | **7831** |
| `browser.*` | Браузер (Playwright) | Docker / :7830 | 7824 / 7830 |
| `shell.run` | Команды (sandbox / native) | Docker / host | 7823 / 7828 |
| `fs.*` | Файловая система (allowlist) | Windows host | 7827 / 7830 |
| `com.*` | Outlook COM, legacy bridge | Windows host | 7826 / 7830 |
| `com.outlook.*` | Календарь Outlook | Windows host | 7826 / 7830 |

Код COM ERP: [platform-tool-onec-com/](services/platform-tool-onec-com/platform_tool_onec_com/)

### 5.2. Мои задачи в 1С ERP (`onec.com.query_tasks`)

Tool выполняет **COM-запрос в сеансе ERP** под пользователем `ERP_LOGIN`. Это не OData и не «главная форма GUI», а **серверный запрос** к `Задача.ЗадачаИсполнителя` с фильтром по исполнителю из каталога `Справочник.Пользователи`.

**Workflow для агента:**

```http
POST /api/v1/tools/onec.com.query_tasks/invoke
Authorization: Bearer ...
Content-Type: application/json

{
  "payload": {
    "mine_only": true,
    "limit": 30
  }
}
```

**Ответ (поля):**

| Поле | Описание |
|------|----------|
| `source` | `onec-com` (не `stub`, не OData) |
| `transport` | `com-connector` |
| `current_user` | ФИО из `ПользователиИнформационнойБазы.ТекущийПользователь()` |
| `count` | Число задач |
| `tasks[]` | `{ number, description, date, due_date, executor }` |

Опционально: сначала `onec.com.connect` → передать `session_id` в `query_tasks` для переиспользования сеанса.

**Cron «Задачи на сегодня»** (`daily_tasks`) вызывает именно `onec.com.query_tasks`, не `onec.odata_get`. См. [cron_jobs.py](services/platform-orchestrator/platform_orchestrator/cron_jobs.py).

### 5.3. Payload (ключевые примеры)

**Общий контракт** — [platform-contracts/tools.py](platform-contracts/platform_contracts/tools.py):

```json
{ "run_id": "uuid", "department": "...", "payload": { } }
```

| Tool | payload |
|------|---------|
| `imap.search` | `{ "query": "UNSEEN", "limit": 20 }` |
| `onec.odata_get` | `{ "entity": "Document_...", "path": "/...?$top=5", "top": 5 }` |
| `onec.com.connect` | `{}` или `{ "progid": "V83.COMConnector" }` |
| `onec.com.query_tasks` | `{ "mine_only": true, "limit": 30, "prefer_crm": false }` — ERP `Задача.ЗадачаИсполнителя`; CRM только при `"prefer_crm": true` |
| `onec.com.invoke` | `{ "session_id": "...", "method": "NewObject", "args": ["Query", "..."] }` |
| `browser.open_session` | `{}` |
| `com.outlook.launch` | `{ "visible": true }` |
| `com.outlook.calendar_list` | `{ "session_id": "...", "days": 7, "limit": 50 }` |

### 5.4. Stub vs real

| Переменная | Эффект |
|------------|--------|
| `USE_STUBS=true` | Stub handlers, фикстуры (CI/offline) |
| `USE_STUBS=false` + credentials | Боевой IMAP, OData, COM |
| `onec.com` на 64-bit Python | Сервис не поднимет real COM — нужен `py -3.12-32` |

В ответе смотрите `source` (`onec-com` / `stub`) и `transport` (`com-connector`).

---

## 6. API Gateway

**Base URL:** `http://127.0.0.1:7812`

| Метод | Путь | Назначение |
|-------|------|------------|
| POST | `/api/v1/auth/login` | `{ "fio", "password" }` → JWT |
| GET | `/api/v1/tools` | ACL: разрешённые tools |
| POST | `/api/v1/tools/{name}/invoke` | Выполнить tool |
| GET/POST/PATCH/DELETE | `/api/v1/cron/jobs` | Cron-задачи (Beat → agent run) |
| POST | `/api/v1/runs` | Async run (Celery) |
| GET | `/api/v1/kpi/summary` | KPI |

---

## 7. Маршрутизация orchestrator

Настройка: [infra/docker-compose.yml](infra/docker-compose.yml), [service.py `_tool_url()`](services/platform-orchestrator/platform_orchestrator/service.py).

| Префикс | URL (из Docker) | Примечание |
|---------|-----------------|------------|
| `imap.*`, `browser.*` | `TOOL_DESKTOP_HOST_URL` → `:7830` | Unified desktop host |
| **`onec.com.*`** | **`TOOL_ONEC_COM_URL` → `:7831`** | **32-bit COM, приоритет над `onec.*`** |
| `onec.*` (OData) | `http://platform-tool-onec:7822` | HTTP OData |
| `com.*`, `fs.*` | `TOOL_DESKTOP_HOST_URL` или legacy `:7826/:7827` | Windows |
| `shell.*` native | `:7828` | Windows |

**Desktop launcher :7829** поднимает host-сервисы по запросу ([spawn.py](services/platform-desktop-launcher/platform_desktop_launcher/spawn.py)).

---

## 8. Запуск и проверка

### Полный стек

```cmd
cd Consturctor
scripts\install_platform.cmd
scripts\docker_up.cmd
scripts\ensure_com_python.cmd
scripts\start_onec_com_service.cmd
scripts\start_host_network_tools.cmd
```

### Health

| Сервис | URL |
|--------|-----|
| Gateway | http://127.0.0.1:7812/health |
| Orchestrator | http://127.0.0.1:7825/health |
| 1C OData | http://127.0.0.1:7822/health |
| **1C COM** | **http://127.0.0.1:7831/health** |
| Desktop host | http://127.0.0.1:7830/health |
| IMAP / Browser | :7821 / :7824 |

### Smoke 1C COM

```cmd
py scripts\smoke_onec_com.py
py -3.12-32 scripts\verify_com_erp_live.py
```

### Тесты

```cmd
py -3.12 -m pytest tests\test_onec_com_service.py tests\test_cron_jobs.py -q
py -3.12 -m pytest tests\ -q
```

---

## 9. Чеклист для агента

1. JWT через Gateway (`AUTH_STUB=true` в dev).
2. `GET /api/v1/tools` — актуальный ACL.
3. **Задачи 1С ERP** → `onec.com.query_tasks`, не OData (если нужен контекст пользователя ERP).
4. **Документы OData** → `onec.odata_get` / `post`.
5. Desktop/COM: на Windows запущены `:7831` (onec-com) и `:7830` (host).
6. Проверять `source=onec-com`, `transport=com-connector` в ответе.
7. Cron: `POST /api/v1/cron/jobs` с шаблоном `daily_tasks` для утренней проверки задач.
8. Не хардкодить tool list — всегда запрашивать у Gateway.

---

## 10. Связанные артефакты

| Артефакт | Путь |
|----------|------|
| Demo UI | http://127.0.0.1:8790/ |
| Env template | [infra/.env.example](infra/.env.example) |
| Tool seed SQL | [infra/postgres/init/01-schemas.sql](infra/postgres/init/01-schemas.sql) |

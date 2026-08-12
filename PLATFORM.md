# Constructor Platform — Tools & KPI

> **Главный документ для агента-разработчика:** [AGENT_BUILDER.md](AGENT_BUILDER.md)

Модульная платформа инструментов для ИИ-агентов и KPI.

## Структура

- `backend/` — API Gateway (auth, proxy `/runs`, `/tools` → Agent Runtime, `/kpi`)
- `platform-contracts/` — общие Pydantic-схемы
- `platform-db/` — SQLAlchemy модели PostgreSQL
- `platform-service-common/` — FastAPI factory для tool-сервисов
- `services/` — микросервисы
- `infra/docker-compose.yml` — **весь стек** (не нужны отдельные cmd-окна)

## Быстрый старт (Docker — рекомендуется)

```cmd
cd Consturctor
scripts\install_platform.cmd

scripts\docker_up.cmd
```

Или вручную:

```cmd
cd Consturctor\infra
copy .env.example .env
docker compose up -d --build
```

### URL после запуска

| Сервис | URL |
|--------|-----|
| Gateway | http://127.0.0.1:7812/health |
| Demo UI | http://127.0.0.1:8790/ |
| KPI | http://127.0.0.1:7820/health |
| Orchestrator | http://127.0.0.1:7825/health |
| RabbitMQ UI | http://127.0.0.1:15673/ (guest/guest) |

Остановка:

```cmd
scripts\docker_down.cmd
```

### Что поднимает docker-compose

- `postgres`, `rabbitmq`
- `platform-kpi`, `platform-tool-imap`, `platform-tool-onec`, `platform-tool-shell`, `platform-tool-browser`
- **Desktop (Windows host):** `platform-tool-com` (:7826), `platform-tool-filesystem` (:7827), `platform-tool-shell` native (:7828)
- `platform-orchestrator-api`, `platform-orchestrator-worker`, `platform-orchestrator-beat`
- `platform-tool-imap-worker`, `platform-tool-onec-worker`
- `constructor-gateway` (backend)
- `platform-demo-ui`

RabbitMQ на хосте: **5673** (AMQP), **15673** (UI) — если 5672 занят.

### Auth в Docker

По умолчанию `AUTH_STUB=true` в `infra/.env` — вход для теста платформы без ERP SQL из контейнера.

Для реального 1С SQL настройте `ERP_SQL_*` в `infra/.env` (см. `infra/.env.example`).

## Локальный запуск (без Docker)

Только для разработки отдельных сервисов на Windows (shell/browser native). Полный стек — через Docker выше.

### Desktop host (Windows, один порт для агента)

**Единый шлюз :7830** — Microsoft COM (1С, Outlook, Excel, Word, PowerPoint), файлы (`fs.*`), native shell, буфер обмена, открытие файлов (`desktop.*`).

| Сценарий | Что запускать |
|----------|----------------|
| **Пользователь через turbobot desktop app** | Приложение само поднимает `:7830` + launcher `:7829` (фон, без окон) |
| **Docker без desktop app** | `scripts\start_desktop_launcher.cmd` — host `:7830` стартует **по первому вызову агента** |
| **Полный стек** | `scripts\start_platform_all.cmd` (Docker + launcher) |

```cmd
scripts\start_desktop_host.cmd     rem только unified host :7830
scripts\check_desktop_tools.cmd    rem статус launcher + host
```

Orchestrator: `TOOL_DESKTOP_HOST_URL=http://host.docker.internal:7830` → все `com.*`, `fs.*`, native `shell.*`, `desktop.*`.

| Порт | Роль |
|------|------|
| **7830** | **platform-desktop-host** — все desktop tools (единый API) |
| **7829** | launcher — lazy-start `:7830` для Docker |
| 7826–7828 | legacy (если `TOOL_DESKTOP_HOST_URL` не задан) |

Логи: `logs/desktop-host.out.log`.

Orchestrator в Docker обращается через `host.docker.internal`. Настройки в `infra/.env`:

- `FS_ROOT_ALLOWLIST` — локальные папки для fs.*
- `SHELL_CWD_ROOTS` — рабочие каталоги native shell
- `COM_APPS` — JSON `{ "onec": "V83.Application", ... }`

`shell.run` payload: `{ "command": "...", "cwd": "...", "runtime": "native"|"sandbox" }`.

## API Gateway

| Метод | Путь |
|-------|------|
| POST | `/api/v1/tools/{name}/invoke` |
| GET | `/api/v1/tools` |
| POST | `/api/v1/runs` |
| GET | `/api/v1/runs/{id}` |
| GET | `/api/v1/kpi/summary` |
| POST | `/api/v1/kpi/review` |
| GET | `/api/v1/agent/mocks` |
| POST | `/api/v1/agent/mocks/{id}/simulate` |
| POST | `/api/v1/agent/mocks/{id}/run` |
| GET | `/health` |

**FigJam v2:** https://www.figma.com/board/d3SqK8NI5SejQtfy8yzpxF

**Архитектура:** см. `ARCHITECTURE.md`, взаимодействие с внешним агентом — `AGENT_INTERACTION.md`.

## Mock agent scenarios

```cmd
scripts\run_agent_mocks.cmd --list
scripts\run_agent_mocks.cmd --all
```

| ID | Инструменты |
|----|-------------|
| `mail_inbound` | imap.list_unread → fetch_message → fetch_attachments |
| `onec_register` | onec.odata_get → odata_post → attach_file |
| `shell_probe` | shell.run |
| `browser_research` | browser.open_session → navigate → snapshot → screenshot → extract_text → close_session |
| `full_correspondence` | imap + onec + shell + browser |

## Тесты

```cmd
py -3.12 -m pytest tests\ -q
```

Основные модули: `test_platform_contracts.py`, `test_platform_tools_stub.py`, `test_desktop_tools_stub.py`, `test_imap_sandbox.py`, `test_agent_mocks.py`, `test_platform_kpi.py`.

## Каталог tools (кратко)

| Префикс | Tools |
|---------|-------|
| `imap.*` | list_unread, fetch_message, fetch_attachments, search |
| `onec.*` | odata_get, odata_post, odata_patch, attach_file, sql_query |
| `browser.*` | open_session, close_session, navigate, snapshot, click, type, fill, wait, tabs, screenshot, extract_text |
| `shell.*` | run (sandbox :7823 или native :7828) |
| `fs.*` | list, read, write, stat, move, copy |
| `com.*` | list_apps, connect, invoke, release |

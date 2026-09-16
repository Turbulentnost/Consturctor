# Источники данных для UI сетки 9×9

По умолчанию v1: **mock** там, где нет API; пометка в UI через `data-origin="mock"` (dev) — TBD.

| Элемент | Статус v1 | Источник |
|---------|-----------|----------|
| Метрики «Процессы» | live | `useSpecV04Sources`, `buildProcessTiles` |
| Таблица процессов | live | agents + 1C + Turbo + Outlook mail + Outlook meetings |
| Задачи 1С | live | **`onec.docflow_tasks`** — HTTP SOAP `/doc/ws/dm.1cws` (DOK_HTTP_*). Без `erp_tasks_current` / OData. |
| Проекты | live | `turboproject.get_user_portfolio` (source id `turboproject`) |
| Письма (вкладка «Почта» / процессы) | live | **Проба сегодня:** Outlook COM Inbox vs backend IMAP (`POST /api/v1/tools/invoke` → `imap.search` / `imap.list_unread`, desktop **не** открывает IMAP-сокеты). Сверка по `message-id` или нормализованным `(from, subject, date)`. Если IMAP даёт письма за сегодня, которых нет в Outlook — **IMAP primary** (маппер `imapMessageToMailRow`). Иначе COM week (`outlook.search_mail`, `folder=All`, пн…вс). Stub/пустой IMAP — не переключать, показать `GET /api/v1/tools/imap/status`. COM остаётся fallback и для ответ/открыть/прочитано. Ошибки COM и IMAP независимы. |
| Письма («Сегодня») | live | Та же проба primary. Виджет дня: IMAP (`imap.search` `date=Период`) или COM Inbox. Stub/пусто IMAP — COM + строка статуса IMAP. |
| Совещания | live/partial | `ensureOutlookMeetings` |
| База знаний | partial | `api.listWorkflows()` (регламенты Constructor) |
| KPI «Сегодня» (5 плиток) | live/partial | `useTodayKpiData` → `useSpecV04Sources` (см. ниже) |
| Сегодня → «Результаты дня» | live | `useTodayAgentResults` → `GET /api/v1/workflows/files` (`listPlatformFiles`), фильтр: `source=agent`, день = «Период», скачивание `api.download` |
| Сегодня → «Подготовленные решения» | live | `useTodayPreparedDecisions` (день = «Период», scope = пользователь): доска `useWorkplaceData` + `useRuns` (live HITL / `WAITING_HUMAN`) + `extractToolDecisions` по прогонам за день (`listAgentRuns` / `getAgentRunDetail`) + файлы агентов без вердикта (`listPlatformFiles`, как «Результаты дня»); подзаголовок — `intent`/`result` инструмента, `summary`/`agentTitle` файла или итог прогона (`run.summary` / `cleanRunResult`); пустой список без demo; mock `TODAY_PREPARED_DECISIONS` не используется |
| Сегодня → «Проектные задачи» | live | `useTodayProjectTasks`: портфель + до 5× `get_project_tasks` (open); **pin** `VITE_TURBO_PIN_FILE_IDS=363`; для pin — все open-задачи, не только «на день» |
| Сегодня → «Задачи из 1С» | live | `loadOrchestratorErpTasks` → `onec.docflow_tasks` (`today_and_overdue`: срок сегодня + просроченные) |
| Сегодня → «Предстоящие события» | live | `useSpecV04Sources` → `ensureOutlookMeetings`, фильтр по «Период» |
| Сегодня / план дня | live | `useTodayPlanTimeline`: Outlook + доска агентов (без demo-fallback блоков) |
| Глобальный поиск (row 1) | noop | локальный фильтр — TBD endpoint |
| Помощь (?) | link | `https://wiki.turbo-don.ru` (заменить URL по решению) |
| Уведомления | live | `api.listNotifications`, `unread` |
| KPI tiles row 2 (другие вкладки) | mock | до подключения агрегатов KpiPage |

### KPI вкладки «Сегодня» (`buildTodayKpiTiles`)

| Плитка | Источник | Примечание |
|--------|----------|------------|
| Выполнение дня | erp_tasks + агенты доски | % в кольце; value = «N из M»; без Turbo-задач |
| Задачи 1С | `onec.docflow_tasks` | HTTP SOAP `/doc/ws/dm.1cws`. Общий кэш полной выгрузки (`DOK_HTTP_CACHE_TTL_SEC`), нарезка по ФИО на backend. |
| Регламентные работы | `useWorkplaceData` agents (!standalone) | count + выполненные по статусу процесса |
| Проекты | `turboproject.get_user_portfolio` | count портфеля |
| События дня | `ensureOutlookMeetings` + `meetingCountToday` | только встречи на текущий день |
| History journal count | mock | audit API — TBD |
| Decisions comparison table | mock | payload агента — TBD |
| Project calendar (bottom) | mock | TurboProject events tool — TBD |

### Обновление данных (`GridDataRefreshProvider` + `gridDataCache`)

TTL кэша: **10 мин** (`GRID_DATA_TTL_MS = 600_000`). Смена вкладки **не** поднимает `generation` — повторный fetch только если кэш протух или изменились локальные deps (день, портфель, runs).

| Область | Где живёт | Смена user | Focus после blur / visibility | Interval 10 мин | События |
|---------|-----------|------------|-------------------------------|-----------------|---------|
| `SpecV04SourcesProvider` → `fetchOrchestratorTaskSources` (`orchestratorTaskSources.ts`) | App | да | да | да | — |
| `useWorkplaceData` (доска) | hook + module cache | да | да | да | `onBoardUpdated` (всегда reload) |
| `useTodayOutlookMail` | hook + cache | — (`periodDay` в deps) | да | да | проба IMAP vs COM за сегодня, primary кэшируется 2 мин |
| `useTodayAgentResults` | hook + cache | — | да | да | `files_updated`, poll 60 с |
| `useTodayPreparedDecisions` | hook + cache | — | да | да | `files_updated`, `useRuns`, poll 60 с |
| `useTodayProjectTasks` | hook + cache | — | да | да | — |
| `useTodayPlanTimeline` | hook + cache | — | да | да | — |

Повторный вход в приложение поднимает `generation` и перезапрашивает live-источники без пересборки exe.

Это **не** обновление приложения. `forceRefresh()` / TTL 10 мин только перезапрашивают данные сеток.

### Обновление приложения (Electron)

Источник инсталлятора: GitHub `releases/latest` репозитория **Turbulentnost/Consturctor** (`UPDATE_GITHUB_OWNER` / `REPO`, опционально token). MaxJalo — только разработка, не канал установщика.

Алгоритм (`src/main/updater.ts`): `app.getVersion()` ↔ `tag_name`; ассеты `constructor-setup.exe` / `orchestrator-setup.exe`; скачивание в `%TEMP%\constructor-updates`; установка `/S`. Автоопрос каждые 30 мин (первый через 4 с) — только в упакованном exe.

| Действие | Где | IPC |
|----------|-----|-----|
| Проверить обновление | сайдбар, Настройки → Общие | `updater:check` |
| Статус (версия / ошибка / нет релиза / сеть) | сайдбар и настройки | `updater:status`, `updater:getStatus` |
| Установить exe | только packaged + есть релиз | `updater:install` |

`npm run dev`: проверка недоступна, установку exe не предлагаем. Не путать с кнопкой обновления данных на вкладках.

### Запуск для вкладки «Сегодня» (Outlook COM + 1С COM)

1. Backend: `constructor-gateway` на `:7812` (infra `docker compose up -d constructor-gateway`).
2. Orchestrator Electron: `orchestrator/orchestrator/desktop-electron/run_dev.bat` (не Turbobot `Consturctor/desktop/run_dev.bat` — там нет `window.agent`).
3. После правок **preload/main/pybridge** — полностью закрыть окно Electron и снова `run_dev.bat` (hot-reload renderer не подхватывает preload).
4. Outlook/1С COM: локально установлены Outlook и клиент 1С; sidecar вызывает `orchestrator/desktop` AC workers.
5. **Учётка 1С:** после входа в Orchestrator пароль хранится только в памяти renderer (`setComCredentials`) и уходит в gateway (`fio` + `password` в теле `invoke`) и в COM sidecar (`agent:ready` + каждый `onec.*` invoke). JWT — только идентификация пользователя, не пароль 1С.
6. **Dev backend:** для **задач 1С** — `BACKEND_URL=http://127.0.0.1:7812`, в `backend/.env` задайте `DOK_HTTP_*` (SOAP `/doc/ws/dm.1cws`). Виджет вызывает только `onec.docflow_tasks`. Пустой `get_user_portfolio` не блокирует pin `VITE_TURBO_PIN_FILE_IDS=363`.
7. `DOCFLOW_ODATA_*` / `ERP_*` на gateway — **fallback**, если сеанс восстановлен по token без повторного ввода пароля или invoke без `password`.

### Быстрые действия вкладки «Процессы» (`specGridQuickActions.ts`)

| Кнопка | Действие |
|--------|----------|
| Быстрый запуск / Запустить процесс / Карта процессов | вкладка «Решения» (`openWorkplaceTab('decisions')`) |
| Создать задачу в 1С (быстрые действия процессов) | `invokeLocalAcTool('onec.search_tasks', { mine_only: true, limit: 1 })` — COM-сессия |
| + Создать задачу (шапка Задач) | канал 1С / Turbo / черновик → панель «write-API не готов», без фейкового успеха |
| Открыть календарь Outlook | `workspace.powershell_run`: Outlook COM `ShowFolder` (календарь) или `Start-Process outlook` |
| Перейти в 1С | `invokeLocalAcTool('onec.search_tasks', { mine_only: true, limit: 1 })` |

### Кнопки, которые пока noop

Чекбоксы задач, «Отметить выполненной», «⋯» процессов, админ KB/календарь «Запланировать». Плитки KPI в этой итерации не кликабельны (фильтры плиток — отдельная задача).

## Вопросы к владельцу продукта

1. Endpoint глобального поиска или только фильтр текущей таблицы?
2. ~~Письма: ждём Outlook COM или достаточно IMAP?~~ Проба за сегодня: если IMAP (real) содержит письма, которых нет в Outlook Inbox — IMAP становится primary для «Почта» и виджета «Сегодня». COM остаётся fallback + действия. Stub/пусто — не переключать, показать `GET /api/v1/tools/imap/status`.
3. KB: отдельный сервис или только Constructor workflows?
4. KPI/History: приоритет pixel-perfect графиков vs табличные данные?

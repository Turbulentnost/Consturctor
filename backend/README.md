# turbobot Backend

FastAPI-сервис между desktop и внешними системами (1С `erp_pm`, LLM/VLM).

Общая схема: [корневой README](../README.md).

## Как работает

### Аутентификация 1С

Типичный dev на ПК без VPN до `erp_pm`: desktop с `BACKEND_URL=http://127.0.0.1:7812`, в `backend/.env` — `AUTH_ERP_GATEWAY_URL=http://192.168.1.157:7812`, `AUTH_SKIP_ERP_SQL=0`. Локальный backend сначала пробует SQL (`ERP_SQL_*`); если ODBC недоступен — проксирует вход на constructor-gateway. На экране входа — ФИО и **пароль пользователя 1C**.

Полностью локальный SQL (VPN до `ii1`): можно оставить `AUTH_ERP_GATEWAY_URL` пустым — вход только через `dbo.v8users`.

1. `POST /api/v1/auth/login` с `{ fio, password }`.
2. Поиск пользователя в `dbo.v8users` (точное совпадение `Name` или `Descr`).
3. Проверка пароля по полю `Data` — модуль [`tools/onec/password.py`](tools/onec/password.py).
4. Отдел: join сотрудника `_Reference366` и подразделений `_Reference513` (несколько полей FK, берётся первое непустое).
5. Должность: актуальная запись регистра `_InfoRg43757` по физлицу `_Reference596` → справочник `_Reference164`.
5. Выдаётся JWT; отдельная БД приложения на MVP не используется.

Список ФИО для автодополнения: `GET /api/v1/auth/users?search=`.

Профиль: `GET /api/v1/auth/me` (Bearer) — повторное чтение из ERP.

### Health

`GET /health` — статус API, доступность ERP (`erp_reachable`), имя сервера, текущий LLM-провайдер.

### LLM (заготовка)

`POST /api/v1/llm/chat` — stub: эхо последнего user-сообщения. Требует JWT.  
Дальше сюда подключаются реальные LLM/VLM (`LLM_PROVIDER` в `.env`).

### ERP SQL

| Переменная | Смысл |
|------------|--------|
| `ERP_SQL_SERVER=ii1` | Внутренний хост (= `192.168.1.157`), TCP **1433**, не localhost |
| `ERP_SQL_DATABASE=erp_pm` | База 1С |
| `ERP_SQL_TRUSTED_CONNECTION=no` | SQL login (`ERP_SQL_USER`/`ERP_SQL_PASSWORD`, read-only от DBA) |
| `AUTH_ERP_GATEWAY_URL` | Fallback login на LAN gateway (`192.168.1.157:7812`), если локальный ERP SQL недоступен |

Только чтение. Сырой IP вместо hostname ломает Windows Auth (если включите `Trusted_Connection=yes`).

### App Postgres

Черновики агентов, пользователи приложения и связанные данные — в общей БД:

`DATABASE_URL=postgresql+psycopg://constructor:constructor@192.168.1.157:5435/constructor`

## Как должно работать дальше

Backend остаётся единственной точкой для моделей и оркестрации агентов: анализ инструкций, VLM по документам/скринам, компиляция workflow, права по отделу. Auth через 1С сохраняется как есть.

## Запуск

```powershell
cd backend
python -m pip install -e .
copy .env.example .env
python -m app.main
```

API: `http://127.0.0.1:7812`

Деплой LAN gateway (`192.168.1.157:7812`, без VPN на клиентах): [docs/DEPLOY_CONSTRUCTOR_GATEWAY.md](docs/DEPLOY_CONSTRUCTOR_GATEWAY.md).

Расписание агентов и KPI считает **Celery worker**, не каждый десктоп. Redis + worker + beat:

```powershell
docker compose up -d constructor-redis constructor-worker constructor-beat
```

Postgres на сервере: `192.168.1.157:5435` (`constructor-pg`). Redis: `REDIS_URL=redis://192.168.1.157:6382/0` (или локальный `:6382`, если поднят `run_redis_dev.bat`).
На Windows worker можно поднять без Docker: `celery -A app.celery_app worker` и `celery -A app.celery_app beat` (нужен Redis).

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/health` | Статус + ERP |
| GET | `/api/v1/auth/users?search=` | Автодополнение ФИО |
| POST | `/api/v1/auth/login` | Вход → JWT + профиль |
| GET | `/api/v1/auth/me` | Текущий пользователь |
| POST | `/api/v1/llm/chat` | Stub LLM (Bearer) |

Утилиты экспорта/проверки пароля: [`scripts/README.md`](scripts/README.md).

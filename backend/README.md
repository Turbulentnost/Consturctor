# Constructor Backend

FastAPI-сервис между desktop и внешними системами (1С `erp_pm`, LLM/VLM).

Общая схема: [корневой README](../README.md).

## Как работает

### Аутентификация 1С

1. `POST /api/v1/auth/login` с `{ fio, password }`.
2. Поиск пользователя в `dbo.v8users` (точное совпадение `Name` или `Descr`).
3. Проверка пароля по полю `Data` — модуль [`tools/onec/password.py`](tools/onec/password.py).
4. Отдел: join сотрудника `_Reference366` и подразделений `_Reference513` (несколько полей FK, берётся первое непустое).
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
| `ERP_SQL_SERVER=ii1` | Внутренний хост (= `192.168.1.157`), не localhost |
| `ERP_SQL_DATABASE=erp_pm` | База 1С |
| `ERP_SQL_TRUSTED_CONNECTION=yes` | Windows Auth |

Только чтение. Сырой IP вместо hostname ломает Trusted Connection.

## Как должно работать дальше

Backend остаётся единственной точкой для моделей и оркестрации агентов: анализ инструкций, VLM по документам/скринам, компиляция workflow, права по отделу. Auth через 1С сохраняется как есть.

## Запуск

```powershell
cd c:\Users\testii\Downloads\projects_Mangasaryan\Constructor\backend
python -m pip install -e .
copy .env.example .env
python -m app.main
```

API: `http://127.0.0.1:7812`

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/health` | Статус + ERP |
| GET | `/api/v1/auth/users?search=` | Автодополнение ФИО |
| POST | `/api/v1/auth/login` | Вход → JWT + профиль |
| GET | `/api/v1/auth/me` | Текущий пользователь |
| POST | `/api/v1/llm/chat` | Stub LLM (Bearer) |

Утилиты экспорта/проверки пароля: [`scripts/README.md`](scripts/README.md).

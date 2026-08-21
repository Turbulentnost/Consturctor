# RegAgent — десктопный агент документооборота (поручения, OData, Excel)

Запуск из **корня репозитория** `Consturctor/` (этот каталог — `RegAgent/`).

## Требования

- **Windows 10/11**
- **Python 3.12** (`py -3.12` в PATH)
- Доступ к backend **constructor-gateway** на **`http://192.168.1.157:7812`** (или свой `BACKEND_URL` в `.env`)
- **CURSOR_API_KEY** — ключ Cursor API для агента (Composer)
- Для OData/COM: сеть до 1С (`ONEC_COM_*`, `ODATA_*` в `.env.example`)

## 1. Backend (constructor-gateway)

Gateway слушает порт **7812** и нужен для авторизации desktop/RegAgent и вызова tools.

```powershell
cd infra
copy .env.example .env
docker compose up -d --build constructor-gateway
```

Проверка (на машине с gateway или по LAN):

```powershell
curl http://192.168.1.157:7812/health
```

Ожидается `"status":"ok"`. На сервере gateway можно использовать `http://127.0.0.1:7812`.

Полный стек платформы (опционально): `docker compose up -d --build` — см. [../PLATFORM.md](../PLATFORM.md).

## 2. Первичная настройка RegAgent

```powershell
cd RegAgent
copy .env.example .env
```

В `.env` обязательно задайте:

- `CURSOR_API_KEY=...`
- `BACKEND_URL=http://192.168.1.157:7812` (если gateway на другом хосте — укажите свой URL)

Остальные переменные — по комментариям в `.env.example` (OData, COM, тестовый вход).

Файл **`.env` не коммитится** (секреты).

## 3. Запуск RegAgent

Из каталога `RegAgent/`:

```cmd
run.bat
```

Скрипт создаёт `.venv`, ставит `requirements.txt` и запускает `python main.py`.

## 4. Тестовый вход (без backend)

Для локальной отладки UI можно включить bypass (см. `.env.example`):

```env
REGAGENT_TEST_LOGIN=1
REGAGENT_TEST_FIO=Ilchenko Evgeniy Aleksandrovich
REGAGENT_TEST_PASSWORD=123
```

(ФИО — как в вашей базе 1С; пример: **Ilchenko** / пароль **123**.)

## 5. Опционально: turbobot desktop

Клиент конструктора агентов (PySide6), тот же backend:

```powershell
cd desktop
copy .env.example .env
```

В `.env`: `BACKEND_URL=http://192.168.1.157:7812`, при необходимости `HOST_IP=192.168.1.157`.

```cmd
run.bat
```

Dev-режим без exe: [../desktop/README.md](../desktop/README.md).


## Конвейер создания агента

Мастер создания карточки агента из регламента (страницы `create` → `review` → `process` → `passport` → `demo` → `schedule` → рабочая область). Логика фаз — `app/models.py` (`CardPhase`), оркестрация — `app/agent/pipeline.py`, промпты — `app/agent/prompts_create.py`.

| Шаг | Фаза (`CardPhase`) | UI | Суть |
|-----|-------------------|-----|------|
| 1 | `intake` | загрузка регламента | Файл регламента, создание карточки и workspace |
| 2 | `review` | review | Разбор регламента, уточнения |
| 3 | `functions` | process | Группы функций агента (Cursor SDK) |
| 4 | `passport` | passport | Паспорт агента, KPI |
| 5 | `demo` | demo | Демо-сценарий в workspace |
| 6 | `schedule` / `published` | schedule | Публикация карточки |
| 7 | workspace | workspace | Запуск опубликованного агента |

Промежуточные фазы `readiness` и `design` используются при необходимости между functions и demo.

**Требования:** задан `CURSOR_API_KEY` в `.env`; генерация идёт через **локальный Cursor SDK** (`cursor-sdk` / `app/agent/harness.py`), без облачного агента в этом конвейере.

Тесты конвейера (без API): `python -m pytest tests/test_pipeline.py -q`.

## Документация

- Поручения / docflow: [docs/task-docflow-porucheniya.md](docs/task-docflow-porucheniya.md)
- Карта репозитория для агента: [../AGENT_BUILDER.md](../AGENT_BUILDER.md)
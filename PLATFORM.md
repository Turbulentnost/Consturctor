# Constructor Platform — Tools & KPI

Модульная платформа инструментов для ИИ-агентов и KPI.

## Структура

- `backend/` — API Gateway (auth, proxy `/tools`, `/runs`, `/kpi`)
- `platform-contracts/` — общие Pydantic-схемы
- `platform-db/` — SQLAlchemy модели PostgreSQL
- `platform-service-common/` — FastAPI factory для tool-сервисов
- `services/` — микросервисы (Docker + Windows native)
- `infra/` — docker-compose (PostgreSQL, RabbitMQ)

## Быстрый старт

```powershell
cd Consturctor
.\scripts\install_platform.ps1

cd infra
docker compose up -d postgres rabbitmq

# Терминалы (USE_STUBS=true):
python -m platform_kpi.main              # :7820
python -m platform_tool_imap.main        # :7821
python -m platform_tool_onec.main        # :7822
python -m platform_tool_shell.main       # :7823 (Windows)
python -m platform_tool_browser.main       # :7824 (Windows)
python -m platform_orchestrator.api_main # :7825
celery -A platform_orchestrator.celery_app worker -Q default,imap,onec,shell,browser -l info

cd backend
python -m app.main                       # :7812
```

Полный стек Docker:

```powershell
cd infra
docker compose --profile full up -d
```

## API Gateway

| Метод | Путь |
|-------|------|
| POST | `/api/v1/tools/{name}/invoke` |
| GET | `/api/v1/tools` |
| POST | `/api/v1/runs` |
| GET | `/api/v1/runs/{id}` |
| GET | `/api/v1/kpi/summary` |
| POST | `/api/v1/kpi/review` |
| GET | `/health` |

## Тесты

```powershell
pytest tests/test_platform_contracts.py -q
pytest tests/test_platform_tools_stub.py -q
```

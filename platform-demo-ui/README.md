# Platform Demo UI v2

Путь в репозитории: `Consturctor/platform-demo-ui/`

Фронт для ручной проверки **новой архитектуры v2**:
Gateway → Agent Runtime → RabbitMQ → Tool workers.

## FigJam

[Constructor Platform v2 Agent Pipeline](https://www.figma.com/board/d3SqK8NI5SejQtfy8yzpxF)

Mermaid-источник: `diagram.mmd`

## Быстрый старт

```cmd
rem 1. Platform (Docker — всё сразу)
cd c:\Users\mdj\Desktop\конструктор\Consturctor
scripts\docker_up.cmd

rem Demo UI уже на http://127.0.0.1:8790/
```

## Mock agent scenarios

| # | Кнопка | Действие |
|---|--------|----------|
| Simulate | Синхронный прогон stub-инструментов (plan + tool steps в логе) |
| Run (Celery) | Async run через Agent Runtime + RabbitMQ |

CLI (без JWT, напрямую orchestrator :7825):

```cmd
cd Consturctor
scripts\run_agent_mocks.cmd --all
```

| # | Кнопка | Что проверяет |
|---|--------|---------------|
| 1 | Войти | Gateway auth → ERP SQL |
| 2 | Health | HTTP :7812–:7825 |
| 3 | Demo run | POST /runs → Runtime → queue imap → worker |
| 4 | Tool via Runtime | POST /tools/invoke → Runtime (не напрямую в tool) |
| 5 | KPI | GET /api/v1/kpi/summary |

## Если run/tool зависает в pending/error

Убедитесь, что запущены Celery workers:

```cmd
py -3.12 -m celery -A platform_orchestrator.celery_app worker -Q default -l info
py -3.12 -m celery -A platform_orchestrator.celery_app beat -l info
py -3.12 -m celery -A platform_tool_imap.celery_app worker -Q imap -l info
```

Логи: `Consturctor\logs\`

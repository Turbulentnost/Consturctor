# Архитектура платформы

> **Карта файлов, tools и API:** [AGENT_BUILDER.md](AGENT_BUILDER.md)

## Целевая модель (как должно быть)

**Агент — снаружи контура.** Платформа — сервер обработки: tools, очереди, audit, KPI по карточке агента.

Подробно: [`AGENT_INTERACTION.md`](AGENT_INTERACTION.md)

```
External Agent Server (LLM, planning)     ← вне контура
    │ HTTPS / MCP-style tool API
    ▼
Gateway (:7812)          — auth, карточка агента, KPI read
    │
    ▼
Tool Execution (:7825)   — исполнение tools по запросу агента (НЕ «мозг» агента)
    │
    ├── Celery Beat      — poll IMAP, poll 1C (триггеры для агента)
    │
    ▼
RabbitMQ                 — очереди backpressure по доменам инструментов
    │
    ▼
Tool workers             — IMAP, 1C, Shell, Browser
    │
    ▼
PostgreSQL               — runs, tool_events, agent_cards, kpi
```

### Принципы

1. **Gateway не вызывает tools напрямую** — только проксирует запросы **внешнего агента** в Tool Execution (:7825).
2. **Карточка агента** — бизнес-задачи и KPI-критерии оценки **работы агента**. Не связана с tool_registry.
3. **Инструментарий** (`tool_registry`) — отдельный слой; агент вызывает tools по необходимости.
4. **Celery Beat** — фоновые события; агент сам решает, реагировать ли.
5. **RabbitMQ** — backpressure на tool-вызовы, не на бизнес-задачи агента.

| Компонент | Статус |
|-----------|--------|
| Gateway → Agent Runtime для `/runs` | ✅ |
| Gateway → Agent Runtime для `/tools/invoke` | ✅ (исправлено) |
| Tool invoke через очереди `imap` / `onec` | ✅ |
| Celery Beat: poll IMAP / 1C | ✅ stub (интервал настраивается) |
| Отдельные workers `imap`, `onec` | ⚠️ нужно запускать вручную или `docker compose --profile full` |
| LLM / MCP planning в runtime | ❌ агент снаружи; LLM stub на gateway не связан |
| KPI по карточке агента | 📋 schema + SQL seed; API агрегации — следующий шаг |
| shell / browser через очередь | ⚠️ пока sync HTTP (Windows native, worker опционален) |

## Запуск workers

В Docker всё уже в `infra/docker-compose.yml`:

```cmd
scripts\docker_up.cmd
```

Локально (только dev):

```cmd
py -3.12 -m celery -A platform_orchestrator.celery_app worker -Q default -l info
py -3.12 -m celery -A platform_orchestrator.celery_app beat -l info
py -3.12 -m celery -A platform_tool_imap.celery_app worker -Q imap -l info
py -3.12 -m celery -A platform_tool_onec.celery_app worker -Q onec -l info
```

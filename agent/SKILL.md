---
name: constructor-agent
description: >-
  Локальный coding-agent runtime Constructor: tool-calling цикл, 9 инструментов
  (read/write/patch/delete/glob/grep/shell/lints/todos), sandbox и CLI.
  Использовать при работе с agent/, main.py, run_agent, MockLLM, офлайн-демо
  или интеграции автономного агента в Constructor.
---

# Constructor Agent Runtime

Справочник для AI-агентов и сборщиков: что умеет локальный coding-agent в `agent/` и как его запускать.

**Источник правды** — файлы на диске. Модель не пишет файлы напрямую; хост выполняет инструменты и возвращает JSON в цикл до завершения задачи.

## Когда использовать

- Автономное редактирование кода в workspace Constructor (CLI `main.py` или `run_agent()`).
- Офлайн-проверка цикла без API-ключа (`--mock`, `MockLLMClient`).
- Разработка/тестирование runtime: `agent/loop.py`, `tool_registry.py`, `safety.py`, `tests/test_agent_runtime.py`.
- **Не путать** с platform-orchestrator (`fs.*`, `shell.*` на портах 7823–7828) — это **отдельный** локальный runtime; см. раздел «Интеграция».

## Жёсткие правила (Cursor-style)

| Правило | Детали |
|---------|--------|
| **Без shell-записей** | Создание/перезапись — `write_file`; патч — `str_replace`; удаление — `delete_file`. Запрещены `echo >`, `>>`, `tee`, `sed -i`, `curl -o`, pipe в файл. |
| **Читать перед правкой** | Перед `str_replace` — `read_file` с точным фрагментом `old_string`. |
| **Sandbox workspace** | Все пути внутри `AGENT_WORKSPACE`; traversal (`../../`) блокируется. |
| **Секреты** | Запись в `.env`, `.env.local`, `credentials.json`, `secrets.json` запрещена без явного запроса пользователя. |
| **Shell только run/test/build** | `run_terminal` — allowlist префиксов + denylist деструктивных команд. |

## Контракт результата инструмента

Каждый вызов возвращает JSON:

```json
{"ok": true, "tool": "write_file", "data": {"path": "hello.py", "bytes_written": 42}, "error": null}
{"ok": false, "tool": "str_replace", "data": null, "error": {"code": "not_found", "message": "..."}}
```

## Цикл агента

1. LLM получает system prompt (`prompts/system.md`) + цель пользователя + схемы инструментов.
2. Пока `steps < max_steps` (по умолчанию **25**):
   - если есть `tool_calls` → выполнить инструменты → добавить role=`tool` в историю → следующий шаг;
   - иначе → финальный текстовый ответ, выход.
3. **Параллельность**: read-only инструменты (`read_file`, `glob`, `grep`, `read_lints`) в одном шаге — параллельно (до 8 workers); мутирующие — последовательно.
4. Превышение `max_steps` → `aborted=true`, `abort_reason="Reached max_steps=N"`.

## Инструменты (9 core)

### `read_file`

**Аргументы:** `path` (обяз.), `offset` (1-based), `limit` (число строк).

**Успех (`data`):** `path`, `content`, `start_line`, `end_line`, `total_lines`, `truncated`.

**Когда:** перед правкой; просмотр больших файлов окном.

**Ошибки:** `not_found`, `not_a_file`, `binary_file`, `path_outside_workspace`.

---

### `write_file`

**Аргументы:** `path`, `contents`.

**Успех:** `path`, `bytes_written`, `lines_written`, `created`.

**Когда:** новый файл или полная перезапись. Лимит: `max_file_write_bytes` (512 KB).

**Ошибки:** `file_too_large`, `secret_file`, `path_outside_workspace`.

---

### `str_replace`

**Аргументы:** `path`, `old_string`, `new_string`, `replace_all` (default `false`).

**Успех:** `path`, `replacements`, `bytes_written`.

**Когда:** предпочтительный способ правки существующих файлов. `old_string` должен быть уникален (или `replace_all=true`).

**Ошибки:** `not_found`, `ambiguous`, `binary_file`, `secret_file`.

---

### `delete_file`

**Аргументы:** `path`.

**Успех:** `path`, `deleted: true`.

**Когда:** удаление файла в workspace (не через `rm`/`del` в shell).

---

### `glob`

**Аргументы:** `pattern` (обяз., авто-префикс `**/`), `target_directory` (опц.).

**Успех:** `pattern`, `target_directory`, `matches[]`, `count`.

**Когда:** найти файлы по шаблону. Пропускает `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`.

---

### `grep`

**Аргументы:** `pattern` (regex, обяз.), `path`, `glob`, `case_insensitive`, `head_limit`.

**Успех:** `pattern`, `matches[{path,line,content}]`, `formatted[]` (`path:line:content`), `count`, `truncated`.

**Когда:** поиск символов/строк в коде.

---

### `run_terminal`

**Аргументы:** `command`, `cwd`, `timeout_ms`, `env`.

**Успех:** `command`, `cwd`, `exit_code`, `stdout`, `stderr`, `stdout_truncated`, `stderr_truncated`, `duration_ms`.

**Когда:** pytest, python, git status, npm test, ruff, mypy и т.п.

**Allowlist префиксов:** `python`, `py`, `pytest`, `pip`, `git`, `npm`, `node`, `ruff`, `mypy`, `uv`, `cargo`, `go`, `make`, `dir`, `ls`, `type`, `echo` (без редиректа), `where`, `which`, `cd`.

**Denylist:** `rm`, `del`, `format`, `git push --force`, `git reset --hard`, редиректы `>`/`>>`, `tee`, `curl -o`, и др.

---

### `read_lints`

**Аргументы:** `paths[]` (опц.).

**Сейчас:** всегда `ok=false`, `error.code="unavailable"` — честная заглушка. Используйте `run_terminal` с ruff/pytest/mypy.

Read-only → может выполняться параллельно с другими read-only.

---

### `todo_write`

**Аргументы:** `todos[{id, content, status}]`, `merge` (default `true`).

**Статусы:** `pending`, `in_progress`, `completed`, `cancelled`.

**Успех:** `todos[]`, `count`. Хранится in-memory на время run.

**Когда:** многошаговые задачи (3+ шага).

## Лимиты безопасности

| Лимит | Значение |
|-------|----------|
| `max_steps` | 25 (env `AGENT_MAX_STEPS`) |
| `max_file_write_bytes` | 512 000 |
| `max_output_bytes` | 256 000 (stdout/stderr `run_terminal`) |
| Path traversal | блок `path_outside_workspace` |
| Секретные файлы | блок `secret_file` при write/str_replace/delete |

## Запуск

Из корня репозитория `Consturctor/`:

```bash
# Офлайн-демо (без API-ключа)
py -3.12 main.py --mock "Create hello.py with add(a,b) and a pytest test"

# Реальный LLM (OpenAI-compatible)
set AGENT_API_KEY=sk-...
set AGENT_MODEL=gpt-4o-mini
py -3.12 main.py "Add a utility function and run tests"

# Отладка и лимит шагов
py -3.12 main.py --debug --max-steps 15 "Refactor foo"
```

### Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `AGENT_WORKSPACE` | Корень workspace (default: cwd) |
| `AGENT_API_KEY` / `OPENAI_API_KEY` | API-ключ |
| `AGENT_MODEL` / `OPENAI_MODEL` | Модель (default `gpt-4o-mini`) |
| `AGENT_BASE_URL` / `OPENAI_BASE_URL` | Совместимый API base |
| `AGENT_MAX_STEPS` | Лимит шагов (default 25) |
| `AGENT_PROVIDER` | `openai` или `mock` |
| `AGENT_DEBUG` | `1`/`true` — trace инструментов |
| `AGENT_BROWSER_ENABLED` | `true`/`false` — browser.* tools |

CLI: `--workspace`, `--mock`, `--debug`, `--max-steps`.

### Программный вызов

```python
from agent import run_agent, load_config_from_env, create_llm_client

config = load_config_from_env(".")
result = run_agent("Refactor foo", config, create_llm_client(config))
print(result.final_answer)
```

## Интеграция с платформой

| | **agent/** (этот runtime) | **platform-orchestrator** |
|--|---------------------------|---------------------------|
| Запуск | `main.py`, `run_agent()` | Docker-сервисы :7825+ |
| Инструменты | `read_file`, `write_file`, … | `fs.*`, `shell.*`, browser, COM |
| Sandbox | один `AGENT_WORKSPACE` | allowlist папок, tool workers |
| Статус | standalone CLI, автономный цикл | оркестрация агентов платформы |

Оба следуют политике «файлы = источник правды, shell не для записи кода», но **не взаимозаменяемы** без адаптера.

> **Опционально:** при `AGENT_BROWSER_ENABLED=true` доступны `browser.*` (navigate, snapshot, click…) через worker `TOOL_BROWSER_URL`. Это расширение поверх 9 core tools — см. `tool_registry.py`.

## Примеры сценариев

### Создать файл

1. `write_file` → `src/utils.py` с содержимым.
2. `run_terminal` → `py -3.12 -m pytest tests/ -q` для проверки.

### Пропатчить функцию

1. `grep` → найти определение.
2. `read_file` → скопировать точный фрагмент.
3. `str_replace` → минимальная правка.
4. `run_terminal` → pytest.

### Прогнать pytest (mock e2e)

```bash
py -3.12 main.py --mock "hello demo"
# → examples/hello.py, examples/test_hello.py, str_replace fix, pytest pass
```

## Связанные файлы

- [README.md](README.md) — quick start и layout
- [prompts/system.md](prompts/system.md) — system prompt агента
- [../main.py](../main.py) — CLI
- [../tests/test_agent_runtime.py](../tests/test_agent_runtime.py) — тесты runtime

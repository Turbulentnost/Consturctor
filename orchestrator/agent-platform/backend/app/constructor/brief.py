"""План запуска агента, сформированного в Конструкторе.

Промпт такого агента лежит не в turbotest.agents, а в public.workflows: local_run.playbook
(инструкция, шаги, инструменты, входы), local_run.write_recipe (проба записи в 1С) и plan_json
(цель, ограничения, шаги паспорта). Сборка повторяет materials/agent.md Конструктора
(desktop/app/sdk_agent/files.py seed_agent_brief), но без правил его раннера: исполняет
конфигурация 2 платформы.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.constructor.owners import is_published

_VALUE_CHARS = 2000
_EXAMPLE_CHARS = 6000
_DOCUMENT_CHARS = 12000
_LAST_RESULT_CHARS = 4000


class ConstructorBrief(BaseModel):
    id: str
    title: str
    goal: str = ""
    owner_fio: str = ""
    owner_position: str = ""
    tools: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    plan: str = ""


class BriefError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _value(value: Any) -> str:
    """Поле playbook в одну строку: текст как есть, список строк через «; », остальное — JSON."""
    if isinstance(value, str):
        return _clip(" ".join(value.split()), _VALUE_CHARS)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return _clip("; ".join(" ".join(item.split()) for item in value if item.strip()), _VALUE_CHARS)
    if value in (None, {}, []):
        return ""
    return _clip(json.dumps(value, ensure_ascii=False, separators=(", ", ": ")), _VALUE_CHARS)


def _names(raw: Any) -> list[str]:
    names: list[str] = []
    for item in _list(raw):
        name = _str(item.get("name") or item.get("tool")) if isinstance(item, dict) else _str(item)
        if name and name not in names:
            names.append(name)
    return names


def _bullets(title: str, items: Any) -> list[str]:
    lines = [f"- {_value(item)}" for item in _list(items) if _value(item)]
    return ["", f"## {title}", *lines] if lines else []


def _section(title: str, text: str) -> list[str]:
    return ["", f"## {title}", text] if text else []


_STEP_FIELDS = (
    ("action", "Что сделать"),
    ("system", "Система"),
    ("entity", "Объект"),
    ("operation", "Операция"),
    ("required_params", "Параметры"),
    ("data_expectation", "Ожидаемые данные"),
    ("done_when", "Готово, когда"),
    ("on_empty", "Если пусто"),
    ("on_error", "Если ошибка"),
    ("proven_call", "Проверенный вызов"),
)


def _step_tool(step: Mapping[str, Any]) -> str:
    candidates = [_str(item) for item in _list(step.get("tool_candidates")) if _str(item)]
    tool = _str(step.get("tool"))
    if tool:
        return f"`{tool}`"
    return " или ".join(f"`{item}`" for item in candidates)


def _step_lines(steps: list[Any]) -> list[str]:
    lines: list[str] = []
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            text = _value(raw)
            if text:
                lines.append(f"{index}. {text}")
            continue
        title = _str(raw.get("title") or raw.get("id")) or f"Шаг {index}"
        tool = _step_tool(raw)
        optional = " (необязательный)" if raw.get("required") is False else ""
        lines.append(f"{index}. {title}{f' — {tool}' if tool else ''}{optional}")
        for key, label in _STEP_FIELDS:
            text = _value(raw.get(key))
            if text:
                lines.append(f"   - {label}: {text}")
    return lines


def _step_titles(steps: list[Any]) -> list[str]:
    titles: list[str] = []
    for index, raw in enumerate(steps, start=1):
        step = _dict(raw)
        title = _str(step.get("title") or step.get("id") or step.get("action")) if step else _value(raw)
        if title:
            titles.append(f"{index}. {title}")
    return titles


def _run_inputs(raw: Any) -> list[str]:
    lines: list[str] = []
    for item in _list(raw):
        if not isinstance(item, dict):
            text = _value(item)
            if text:
                lines.append(f"- {text}")
            continue
        name = _str(item.get("name")) or "файл"
        accept = _str(item.get("accept"))
        description = _value(item.get("description"))
        line = f"- {name}" + (f" ({accept})" if accept else "") + (f" — {description}" if description else "")
        lines.append(line)
    if not lines:
        return []
    return [
        "",
        "## Входные данные запуска",
        *lines,
        "",
        "Если нужного файла нет среди вложений запуска, спроси его через ask_user. "
        "Не подменяй файл пользователя другим источником.",
    ]


def _recipes(recipe: Mapping[str, Any], plan_playbook: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    found = [item for item in _list(recipe.get("recipes")) if isinstance(item, dict)]
    if not found and isinstance(recipe.get("recipe"), dict):
        found = [recipe["recipe"]]
    if not found and recipe.get("tool"):
        found = [recipe]
    if not found:
        found = [item for item in _list(plan_playbook.get("write_recipes")) if isinstance(item, dict)]
    return found


def _recipe_line(recipe: Mapping[str, Any]) -> str:
    parts = [f"`{_str(recipe.get('tool'))}`" if _str(recipe.get("tool")) else "", _str(recipe.get("entity"))]
    create = _dict(recipe.get("create"))
    if create:
        fields = _value(create.get("fields"))
        parts.append(f"создание{f' (поля: {fields})' if fields else ''}")
    for key in ("update", "update_status"):
        update = _dict(recipe.get(key))
        if update:
            field = _str(update.get("field"))
            via = _str(update.get("via"))
            parts.append(f"изменение {field or 'полей'}{f' через {via}' if via else ''}")
    before, after = _str(recipe.get("verified_status_from")), _str(recipe.get("verified_status_to"))
    if before and after:
        parts.append(f"проверен переход «{before}» → «{after}»")
    return ", ".join(part for part in parts if part)


def _write_recipe(raw: Any, playbook: Mapping[str, Any], plan_playbook: Mapping[str, Any]) -> list[str]:
    recipe = _dict(raw) or _dict(playbook.get("write_recipe")) or _dict(plan_playbook.get("write_recipe"))
    recipes = _recipes(recipe, plan_playbook)
    if not recipe and not recipes:
        return []
    lines = ["", "## Проверенная запись в 1С"]
    if recipe and not recipe.get("ok") and not recipes:
        reason = _str(recipe.get("error") or recipe.get("summary")) or "нет механизма"
        lines.append(f"Проба записи в 1С при формировании не удалась: {reason}. Не выдумывай вызов записи — спроси человека.")
        return lines
    lines.append(
        "Конструктор при формировании создал тестовые объекты CONSTRUCTOR_PROBE, проверил на них эти "
        "вызовы и удалил их. Пиши в 1С только так; каждую запись подтверждает человек."
    )
    lines.extend(f"- {line}" for line in (_recipe_line(item) for item in recipes) if line)
    return lines


def build_brief(row: Mapping[str, Any]) -> ConstructorBrief:
    if not is_published(row):
        raise BriefError("Агент ещё не сформирован в Конструкторе", status_code=409)
    plan = _dict(row.get("plan_json"))
    plan_playbook = _dict(plan.get("playbook"))
    playbook = _dict(row.get("playbook")) or plan_playbook

    def pick(key: str) -> Any:
        value = playbook.get(key)
        return value if value not in (None, "", [], {}) else plan_playbook.get(key)

    instructions = _str(pick("instructions"))
    if not instructions:
        raise BriefError("У агента нет инструкции запуска")
    title = _str(plan.get("title")) or _str(row.get("title")) or "ИИ-агент"
    goal = _str(plan.get("goal") or pick("goal"))
    steps = _list(pick("steps")) or _list(plan.get("steps"))
    tools = _names(pick("tools"))
    notes = _str(row.get("notes"))

    parts: list[str] = [f"# {title}"]
    parts += _section("Цель", goal)
    parts += _section("Инструкция запуска", instructions)
    parts += _run_inputs(pick("run_inputs") or plan.get("run_inputs"))
    chain = _str(pick("chain"))
    if chain:
        parts += _section("Проверенная цепочка", chain)
    elif steps:
        parts += [
            "",
            "## Шаги",
            "Маршрут отработан при формировании агента: иди по шагам в этом порядке теми же инструментами, "
            "меняй только параметры запуска.",
            *_step_lines(steps),
        ]
    if tools:
        parts += ["", "## Инструменты агента", ", ".join(f"`{name}`" for name in tools)]
    parts += _section("Ожидаемый результат", _str(pick("expected_result")))
    parts += _bullets("Ограничения", plan.get("constraints"))
    parts += _bullets("Вне объёма", plan.get("out_of_scope"))
    parts += _bullets("Критерии проверки", plan.get("test_criteria"))
    parts += _write_recipe(row.get("write_recipe"), playbook, plan_playbook)
    parts += _section("Пример пробного запуска", _clip(_str(pick("example_run")), _EXAMPLE_CHARS))
    if notes and not notes.startswith("platform:"):
        parts += _section("Заметки", notes)
    document = _str(row.get("document_text"))
    if document:
        name = _str(row.get("document_name")) or "документ"
        parts += _section(f"Документ, по которому сформирован агент ({name})", _clip(document, _DOCUMENT_CHARS))
    last = _str(row.get("last_result"))
    if last:
        parts += _section("Итог прошлого запуска (кратко)", _clip(last, _LAST_RESULT_CHARS))

    return ConstructorBrief(
        id=_str(row.get("id")),
        title=title,
        goal=goal,
        owner_fio=_str(row.get("fio")),
        owner_position=_str(row.get("position")) or _str(row.get("department")),
        tools=tools,
        steps=_step_titles(steps),
        plan="\n".join(parts).strip() + "\n",
    )

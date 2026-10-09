"""Промпты конфигураций с plan_instruction: задача на план, запуск по плану, история прогона."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app import tool_settings
from app.platform.sessions import PLANNING_SEPARATOR, LastRun, RunStep, attach_workspace

_STATUS = {"finished": "завершён", "error": "ошибка", "cancelled": "остановлен"}


def _credential_files() -> str:
    paths = [tool_settings.LOCAL_ENV, *(path for _label, path in tool_settings.constructor_sources())]
    found = [path for path in paths if path.is_file()] or [tool_settings.LOCAL_ENV]
    return ", ".join(f"`{path}`" for path in found)


def _direct_access() -> str:
    return (
        "Инструменты — готовые обёртки, а не единственный путь. Если подходящего инструмента нет, он "
        "падает или отдаёт неполные данные, работай с системой напрямую: напиши скрипт в рабочей папке "
        "и обращайся к 1С (OData) (Если нужно обращаться к 1С), Exchange (EWS), файлам сам. Адреса и учётки бери из "
        f"{_credential_files()} или из задачи; в план, файлы и чат их не пиши. "
        "Исходный код TurboTester и папку platform/data не изучай: это реализация инструментов и "
        "прошлые прогоны, о живых данных они ничего не говорят. "
        "Код пиши и запускай только встроенными инструментами: файлы — встроенной записью, команды и "
        "скрипты — Shell. В режиме плана Shell работает, а запись файлов (кроме markdown) запрещена: "
        "проверочный скрипт передай в Shell через stdin (`python -` с here-string PowerShell). "
        "Подагента (Task) запускай с узкой задачей и понятным моментом, когда остановиться; тип — "
        "generalPurpose, model — inherit: подагент explore всегда работает на слабой быстрой модели. "
    )


def planning_prompt(task: str) -> str:
    return (
        f"{task.strip()}{PLANNING_SEPARATOR}"
        "Составь план выполнения этой задачи. "
        f"{_direct_access()}"
        "Всё, что можно найти в системах, выясняй сам и не спрашивай: какие записи и поля есть, как "
        "называются справочники и документы, кто сотрудник, его адрес и должность, что вернёт "
        "инструмент. Человека спрашивай только о том, чего в системах нет: правила и намерения "
        "(что считать успехом, кому отправлять, как поступать в спорных случаях), выбор между "
        "равноценными вариантами, смысл терминов и сокращений задачи, которые не нашлись в данных. "
        "Сначала проверь, что можешь, потом задай все вопросы одним вызовом MCP-инструмента ask_user "
        "(выбор из готовых вариантов — ask_choice) — встроенный askQuestion здесь не работает. "
        "Ответы человека запиши в план как принятые решения, мелочи решай сам и записывай как допущения. "
        "Прежде чем писать план, проверь на живой системе, только чтением, что ключевые данные "
        "достаются: источник отвечает, нужные записи есть, поля называются так, как ты думаешь. "
        "Пункт, который не проверить ни инструментом, ни напрямую и который человек не прояснил, "
        "пометь в плане «не проверено». Ничего не меняй. "
        "Не ставь в плане остановку на сбое отдельного вызова — укажи, чем его заменить. "
        "Оформи итог инструментом createPlan: план в markdown с целью, допущениями, шагами (чем "
        "выполнить — инструмент или скрипт — и с какими данными) и критериями готовности. Этот план "
        "станет инструкцией агента, который выполнит его без тебя."
    )


def run_prompt(plan: str, workspace: Path, last_run: LastRun | None = None) -> str:
    parts = [
        "Выполни задачу по этому плану. План задаёт цель, решения человека и порядок работы. "
        "Если шаг не срабатывает (инструмент упал, вернул пусто или его нет), не останавливайся: "
        "дойди до того же результата другим путём в рамках решений плана. Пустой или подозрительно "
        "малый ответ инструмента перепроверь напрямую, прежде чем считать, что данных нет. "
        f"{_direct_access()}"
        "Останавливайся, только если без ответа человека пришлось бы угадывать или действие меняет "
        "данные сверх того, что разрешает план. В конце коротко отчитайся о результате и о том, "
        "где отступил от плана.\n"
        f"Рабочая папка этого запуска: `{workspace}`. Все пути плана и истории — в ней.",
        attach_workspace(plan.strip(), workspace),
    ]
    if last_run is not None:
        parts.append(history_block(last_run, workspace))
    return "\n\n".join(parts)


def _short(text: str) -> str:
    """Аргументы и ответы приходят JSON-строкой; разворачиваем их в компактный однострочный вид."""
    try:
        value: Any = json.loads(text)
    except (TypeError, ValueError):
        return " ".join(text.split())
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _step_line(index: int, step: RunStep, workspace: Path) -> str:
    status = "ошибка" if step.status == "error" else "выполнен" if step.status == "completed" else step.status
    line = f"{index}. `{step.name}` — {status or 'без статуса'}"
    if step.args:
        line += f"\n   Вход: {_short(attach_workspace(step.args, workspace, escaped=True))}"
    if step.result:
        line += f"\n   Результат: {_short(attach_workspace(step.result, workspace, escaped=True))}"
    return line


def history_block(run: LastRun, workspace: Path) -> str:
    steps = "\n".join(_step_line(index, step, workspace) for index, step in enumerate(run.steps, 1))
    lines = [
        "---",
        "## История последнего запуска",
        "Учти историю прошлого запуска этого агента: какие инструменты он вызывал, с какими данными "
        "и что получил. Выбери более оптимальный путь: не повторяй вызовы, которые завершились "
        "ошибкой или ничего не дали, сразу используй то, что сработало, и не делай лишних шагов.",
        "",
        f"Статус: {_STATUS.get(run.status, run.status)}, вызовов инструментов: {len(run.steps)}.",
    ]
    if run.error:
        lines.append(f"Ошибка запуска: {run.error}")
    lines.append("")
    lines.append("### Вызовы инструментов")
    lines.append(steps or "Инструменты не вызывались.")
    if run.answer:
        lines.extend(["", "### Итог прошлого запуска", attach_workspace(run.answer.strip(), workspace)])
    return "\n".join(lines)

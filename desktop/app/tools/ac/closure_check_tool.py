"""Итог проверки поручений к закрытию для реестра, порциями по ходу запуска.

Агент отдаёт выводы по 2–3 поручения за вызов, инструмент копит их в папке
агента. В конце запуска sidecar сам дописывает в ответ блок ```closure-check
из этого файла: модели не нужно переписывать весь JSON одним сообщением, а
при обрыве или лимите времени готовая часть всё равно доходит до реестра.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.ac.agent_workspace import AgentWorkspaceResolver, WorkspaceError
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)

CLOSURE_CHECK_TOOL_NAME = "report.closure_check"
CLOSURE_CHECK_FILE = Path("materials") / "closure_check.json"

_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "n": {"type": "integer", "description": "Порядковый номер задачи ДО в поручении, с 1"},
        "performer": {"type": "string", "description": "Исполнитель задачи, фамилия И.О."},
        "task": {"type": "string", "description": "Что поручено в задаче, до 80 символов"},
        "conclusion": {
            "type": "string",
            "enum": ["Можно закрывать", "Вернуть на доработку", "Не выполнено"],
            "description": "Вердикт по задаче",
        },
        "evidence": {"type": "string", "description": "Чем подтверждено, до 120 символов"},
        "task_state": {"type": "string", "description": "label задачи дословно"},
        "advice": {"type": "string", "description": "Предлагаемое действие текстом"},
        "comment": {
            "type": "string",
            "description": "Для «Можно закрывать» и «Вернуть на доработку»: короткое заключение, 1–2 предложения, до 250 символов",
        },
        "action": {"type": "string", "enum": ["close", "return"]},
        "task_id": {"type": "string", "description": "open_check_task_id задачи дословно"},
        "step": {"type": "string", "description": "open_check_step задачи дословно"},
        "title": {"type": "string", "description": "open_check_name задачи дословно"},
        "reason": {"type": "string", "description": "Почему action, 1 предложение"},
        "open_task_id": {"type": "string", "description": "open_execute_task_id задачи дословно"},
    },
    "required": ["n", "performer", "conclusion"],
}

_ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "number": {"type": "string", "description": "Номер поручения, например АСТ00-00113"},
        "target_id": {"type": "string", "description": "ref_key поручения дословно"},
        "conclusion": {
            "type": "string",
            "enum": [
                "Можно закрыть",
                "Нельзя закрыть — выполнено частично",
                "Нельзя закрыть — нет оснований",
            ],
        },
        "done": {"type": "integer", "description": "Задач принято автором (docflow_summary.accepted)"},
        "total": {"type": "integer", "description": "Задач в ДО всего (docflow_summary.total)"},
        "reason": {"type": "string", "description": "Обоснование, 1 предложение"},
        "tasks": {"type": "array", "items": _TASK_SCHEMA},
    },
    "required": ["number", "conclusion", "done", "total", "tasks"],
}


def closure_check_path(directory: str | Path) -> Path:
    return Path(directory) / CLOSURE_CHECK_FILE


def load_closure_check(directory: str | Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(closure_check_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("assignments") if isinstance(data, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def clear_closure_check(directory: str | Path) -> None:
    try:
        closure_check_path(directory).unlink()
    except OSError:
        pass


def closure_check_block(directory: str | Path) -> str:
    """Блок ```closure-check для ответа агента; пусто, если инструмент не вызывали."""
    items = load_closure_check(directory)
    if not items:
        return ""
    rows = ",\n".join(json.dumps(item, ensure_ascii=False) for item in items)
    return f'```closure-check\n{{"assignments":[\n{rows}\n]}}\n```'


def _persist_reviews(incoming: list[dict[str, Any]], workflow_id: str) -> dict[str, Any]:
    """Пишет снимок и вердикты в БД Constructor. Нет сессии — только локальный JSON."""
    try:
        from app.tools.runtime_api import request
    except Exception:  # noqa: BLE001
        return {}
    try:
        result = request(
            "POST",
            "/api/v1/assignment-reviews",
            json={"assignments": incoming, "workflow_id": workflow_id},
            timeout=120.0,
        )
    except Exception as exc:  # noqa: BLE001
        return {"db_error": str(exc)[:240]}
    return {"db": result} if isinstance(result, dict) else {}


def _merge(previous: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Повторный вызов по тому же номеру заменяет поручение, порядок первого вызова сохраняется."""
    merged = {str(item.get("number") or ""): item for item in previous}
    for item in incoming:
        merged[str(item["number"])] = item
    return list(merged.values())


class ClosureCheckTool(BaseTool):
    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name=CLOSURE_CHECK_TOOL_NAME,
                title="Итог проверки поручений для реестра",
                description=(
                    "Сохраняет выводы проверки поручений к закрытию для реестра поручений. "
                    "Вызывай по ходу работы, по 2–3 поручения за вызов, сразу после вывода по ним. "
                    "Каждый вызов дописывает поручения к уже сохранённым; повтор того же number "
                    "заменяет поручение. В ответ блок ```closure-check сам не пиши: "
                    "Оркестратор добавит его из сохранённого."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=120,
                max_retries=0,
                input_schema={
                    "type": "object",
                    "properties": {
                        "assignments": {"type": "array", "items": _ASSIGNMENT_SCHEMA},
                    },
                    "required": ["assignments"],
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        raw = input_data.get("assignments") if isinstance(input_data, dict) else None
        incoming = [
            item for item in raw or [] if isinstance(item, dict) and str(item.get("number") or "").strip()
        ]
        if not incoming:
            return self._fail("EMPTY", "Нет поручений: передай assignments с number, conclusion и tasks.")
        try:
            workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))
        items = _merge(load_closure_check(workspace.directory), incoming)
        path = closure_check_path(workspace.directory)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"assignments": items}, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            return self._fail("WRITE_ERROR", str(exc))
        stored = _persist_reviews(incoming, str(self._resolver.agent_id_from_input(input_data)))
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "saved": [str(item["number"]) for item in incoming],
                "total_saved": len(items),
                "numbers": [str(item.get("number") or "") for item in items],
                **stored,
            },
        )

    def _fail(self, error_type: str, message: str) -> ToolCallResult:
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type=error_type,
            error_message=message,
        )


def register_closure_check_tool(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    tool = ClosureCheckTool(resolver)
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)

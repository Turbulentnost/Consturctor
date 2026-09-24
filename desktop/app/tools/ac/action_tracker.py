"""Запись Action Tracker из уже снятых выборок 1С, без перечисления строк моделью."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.tools.ac.agent_workspace import AgentWorkspaceResolver, WorkspaceError
from app.tools.ac.base import BaseTool
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)

TRACKER_HEADERS = [
    "ID",
    "Источник",
    "Дата решения",
    "Поручение (результат/артефакт)",
    "Заказчик",
    "Владелец",
    "Срок",
    "Приоритет",
    "Статус",
    "Риск/эскалация",
    "Ссылка на результат/документы",
    "Комментарий",
]

_STATUS_COMMENT = {
    "Создано": "1С: Создано",
    "НаИсполнении": "1С: На исполнении",
    "Подготовлен": "1С: Подготовлен, на проверке",
    "Закрыт": "1С: Закрыт",
}

_ASSIGNMENT_PREFIX = "onec.erp_assignments_"
_PROTOCOL_PREFIX = "onec.meeting_protocols_"


class ActionTrackerError(Exception):
    """Выборки 1С нельзя записать в трекер как есть."""


def _day(value: object) -> str:
    return str(value or "")[:10]


def _tracker_status(status_1c: str) -> str:
    return "DONE" if status_1c == "Закрыт" else "IN PROGRESS"


def _comment(status_1c: str) -> str:
    return _STATUS_COMMENT.get(status_1c, f"1С: {status_1c}" if status_1c else "1С")


def latest_result_file(workspace: Path, prefix: str) -> Path | None:
    folder = workspace / "tool_results"
    if not folder.is_dir():
        return None
    matches = [
        path
        for path in folder.glob(f"{prefix}*.json")
        if path.is_file()
    ]
    if not matches:
        return None
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActionTrackerError(f"Не прочитан {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ActionTrackerError(f"{path.name} не объект JSON")
    nested = payload.get("result")
    if isinstance(nested, dict) and (
        isinstance(nested.get("assignments"), list) or isinstance(nested.get("protocols"), list)
    ):
        return nested
    return payload


def _require_rows(payload: dict[str, Any], key: str, *, label: str) -> list[dict[str, Any]]:
    if payload.get("truncated") is True:
        raise ActionTrackerError(
            f"{label} обрезана (truncated=true). Повтори выборку целиком и не записывай часть."
        )
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise ActionTrackerError(
            f"В файле {label} нет списка {key}. Сначала вызови инструмент 1С, не читай JSON сам."
        )
    return [row for row in rows if isinstance(row, dict)]


def assignment_rows(items: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for index, item in enumerate(items, start=1):
        lines = item.get("lines") if isinstance(item.get("lines"), list) else []
        first = lines[0] if lines and isinstance(lines[0], dict) else {}
        text = str(first.get("text") or item.get("topic") or "")
        owner = str(first.get("executor") or item.get("reporter") or "")
        status_1c = str(item.get("status") or "")
        rows.append(
            [
                f"ACT-{index:04d}",
                str(item.get("number") or ""),
                _day(item.get("date")),
                text,
                str(item.get("customer") or ""),
                owner,
                _day(item.get("due")),
                "",
                _tracker_status(status_1c),
                "просрочка" if item.get("overdue") else "",
                "",
                _comment(status_1c),
            ]
        )
    return rows


def protocol_rows(items: list[dict[str, Any]], *, start_index: int, customer: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for offset, item in enumerate(items):
        status_1c = str(item.get("status") or "")
        when = _day(item.get("date"))
        rows.append(
            [
                f"ACT-{start_index + offset:04d}",
                str(item.get("number") or ""),
                when,
                str(item.get("meeting_topic") or item.get("topic") or ""),
                customer,
                "",
                when,
                "",
                _tracker_status(status_1c),
                "",
                "",
                _comment(status_1c),
            ]
        )
    return rows


def build_tracker_rows(
    assignments_payload: dict[str, Any],
    protocols_payload: dict[str, Any],
) -> tuple[list[list[Any]], dict[str, int]]:
    assignments = _require_rows(assignments_payload, "assignments", label="поручений")
    protocols = _require_rows(protocols_payload, "protocols", label="протоколов")
    customer = ""
    for item in assignments:
        customer = str(item.get("customer") or "").strip()
        if customer:
            break
    if not customer:
        customer = "Амураль Игорь Борисович"
    assignment_table = assignment_rows(assignments)
    protocol_table = protocol_rows(protocols, start_index=len(assignment_table) + 1, customer=customer)
    today = date.today().isoformat()
    stats = {
        "assignments": len(assignment_table),
        "protocols": len(protocol_table),
        "open_assignments": sum(1 for item in assignments if item.get("open") is True),
        "overdue": sum(1 for item in assignments if item.get("overdue") is True),
        "due_today": sum(
            1
            for item in assignments
            if _day(item.get("due")) == today
        )
        + sum(1 for item in protocols if _day(item.get("date")) == today),
    }
    return assignment_table + protocol_table, stats


def write_tracker_file(
    path: Path,
    rows: list[list[Any]],
    *,
    stats: dict[str, int],
) -> None:
    from openpyxl import Workbook

    from app.tools.ac.office_style import write_excel_sheet

    today = date.today().strftime("%d.%m.%Y")
    workbook = Workbook()
    write_excel_sheet(
        workbook,
        sheet="Action Tracker",
        headers=TRACKER_HEADERS,
        rows=rows,
        title="Action Tracker — поручения Амураль И.Б.",
        subtitle=(
            f"Сверка {today}. Поручения АСТ00: {stats['assignments']}, все статусы. "
            f"Протоколы ПСД: {stats['protocols']}, включая закрытые."
        ),
        kpis=[
            {"label": "Поручения АСТ00", "value": stats["assignments"]},
            {"label": "Открытые поручения", "value": stats["open_assignments"]},
            {"label": "Просроченные", "value": stats["overdue"]},
            {"label": "Протоколы ПСД", "value": stats["protocols"]},
            {"label": "На сегодня", "value": stats["due_today"]},
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def write_action_tracker(workspace: Path, filename: str = "ActionTracker.xlsx") -> dict[str, Any]:
    assignments_path = latest_result_file(workspace, _ASSIGNMENT_PREFIX)
    protocols_path = latest_result_file(workspace, _PROTOCOL_PREFIX)
    if assignments_path is None or protocols_path is None:
        raise ActionTrackerError(
            "Нет файлов выборки в tool_results. Сначала вызови onec.erp_assignments "
            "и onec.meeting_protocols. JSON сам не читай."
        )
    rows, stats = build_tracker_rows(_load_json(assignments_path), _load_json(protocols_path))
    target = (workspace / filename).resolve()
    if workspace.resolve() != target and workspace.resolve() not in target.parents:
        raise ActionTrackerError("Путь файла выходит за пределы рабочей папки")
    write_tracker_file(target, rows, stats=stats)
    return {
        "filename": target.name,
        "path": str(target),
        "rows": len(rows),
        **stats,
        "assignments_file": assignments_path.name,
        "protocols_file": protocols_path.name,
        "summary": (
            f"Action Tracker записан: поручений {stats['assignments']}, "
            f"протоколов ПСД {stats['protocols']}."
        ),
    }


class ExcelWriteActionTrackerTool(BaseTool):
    """Пишет весь журнал АСТ00 и протоколы ПСД в Action Tracker одним вызовом."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="excel.write_action_tracker",
                title="Запись Action Tracker",
                description=(
                    "Записывает в ActionTracker.xlsx все поручения и все протоколы ПСД "
                    "из последних файлов tool_results (onec.erp_assignments и onec.meeting_protocols). "
                    "Строки передавать не нужно и JSON выборок читать не нужно. "
                    "Один вызов после обеих выборок 1С. Если truncated=true, файл не пишет."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=True,
                timeout_seconds=120,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Книга в папке агента. По умолчанию ActionTracker.xlsx",
                        },
                    },
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        try:
            workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
        except WorkspaceError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="WORKSPACE_ERROR",
                error_message=str(exc),
            )
        filename = str(input_data.get("filename") or "ActionTracker.xlsx").strip()
        if not filename.lower().endswith(".xlsx"):
            filename = f"{filename}.xlsx"
        try:
            output = write_action_tracker(workspace.directory, filename)
        except ActionTrackerError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="TRACKER_WRITE_ERROR",
                error_message=str(exc),
            )
        return ToolCallResult(ok=True, tool_name=self.definition.name, output_data=output)

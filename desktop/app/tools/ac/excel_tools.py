"""Инструменты работы с Excel в изолированной рабочей папке агента.

Инструменты позволяют агенту создавать, читать и редактировать .xlsx-файлы.
Все файлы лежат в песочнице агента (``<root>/<agent_id>/``); выйти за её
пределы нельзя. Инструменты работают локально (без COM), используя openpyxl.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ac.agent_workspace import (
    AgentWorkspaceResolver,
    WorkspaceError,
)
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry


def _cell_value(value: object) -> object:
    """Привести значение ячейки к JSON-совместимому виду."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _ensure_xlsx(name: str) -> str:
    """Гарантировать расширение .xlsx у имени файла."""
    name = str(name).strip()
    if not name.lower().endswith(".xlsx"):
        name = f"{name}.xlsx"
    return name


class _WorkspaceTool(BaseTool):
    """Базовый Excel-инструмент, знающий про рабочую папку агента."""

    def __init__(self, definition: ToolDefinition, resolver: AgentWorkspaceResolver) -> None:
        """Сохранить паспорт и резолвер рабочих папок."""
        super().__init__(definition)
        self._resolver = resolver

    def _workspace(self, input_data: dict):
        """Вернуть рабочую папку агента по runtime_context."""
        agent_id = self._resolver.agent_id_from_input(input_data)
        return self._resolver.for_agent(agent_id)

    def _fail(self, error_type: str, message: str) -> ToolCallResult:
        """Собрать неуспешный результат инструмента."""
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type=error_type,
            error_message=message,
        )


class ExcelListFilesTool(_WorkspaceTool):
    """Список файлов в рабочей папке агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент списка файлов."""
        super().__init__(
            ToolDefinition(
                name="excel.list_files",
                title="Список файлов агента",
                description="Возвращает список файлов в рабочей папке агента.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object"},
            ),
            resolver,
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть файлы рабочей папки агента."""
        try:
            workspace = self._workspace(input_data)
            files = workspace.list_files()
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"files": files, "count": len(files)},
        )


class ExcelReadWorkbookTool(_WorkspaceTool):
    """Чтение содержимого .xlsx из рабочей папки агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент чтения книги Excel."""
        super().__init__(
            ToolDefinition(
                name="excel.read_workbook",
                title="Чтение Excel",
                description="Читает данные листа .xlsx (заголовки и строки).",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "sheet": {"type": "string"},
                        "max_rows": {"type": "integer"},
                    },
                    "required": ["filename"],
                },
                output_schema={"type": "object"},
            ),
            resolver,
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Прочитать выбранный лист книги Excel."""
        from openpyxl import load_workbook

        try:
            workspace = self._workspace(input_data)
            path = workspace.resolve(
                _ensure_xlsx(input_data.get("filename", "")), must_exist=True
            )
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        max_rows = int(input_data.get("max_rows") or 500)
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - openpyxl бросает разные типы
            return self._fail("EXCEL_READ_ERROR", str(exc))

        try:
            sheet_names = list(workbook.sheetnames)
            requested = input_data.get("sheet")
            if requested and requested not in sheet_names:
                return self._fail(
                    "SHEET_NOT_FOUND",
                    f"Лист {requested!r} не найден. Доступны: {sheet_names}",
                )
            worksheet = workbook[requested] if requested else workbook.active
            rows: list[list] = []
            for index, row in enumerate(worksheet.iter_rows(values_only=True)):
                if index >= max_rows:
                    break
                rows.append([_cell_value(cell) for cell in row])
        finally:
            workbook.close()

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "filename": path.name,
                "sheet": worksheet.title,
                "sheets": sheet_names,
                "row_count": len(rows),
                "rows": rows,
                "truncated": len(rows) >= max_rows,
            },
        )


class ExcelCreateWorkbookTool(_WorkspaceTool):
    """Создание нового .xlsx в рабочей папке агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент создания книги Excel."""
        super().__init__(
            ToolDefinition(
                name="excel.create_workbook",
                title="Создание Excel",
                description="Создаёт новый .xlsx с заголовками и строками.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "sheet": {"type": "string"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["filename"],
                },
                output_schema={"type": "object"},
            ),
            resolver,
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Создать новую книгу Excel с данными."""
        from openpyxl import Workbook

        try:
            workspace = self._workspace(input_data)
            path = workspace.resolve(_ensure_xlsx(input_data.get("filename", "")))
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        if path.exists() and not input_data.get("overwrite"):
            return self._fail(
                "FILE_EXISTS",
                f"Файл {path.name} уже существует. Передайте overwrite=true "
                "или используйте excel.edit_workbook.",
            )

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = str(input_data.get("sheet") or "Лист1")[:31]
        headers = input_data.get("headers") or []
        if headers:
            worksheet.append([str(header) for header in headers])
        for row in input_data.get("rows") or []:
            worksheet.append(list(row) if isinstance(row, (list, tuple)) else [row])

        try:
            workbook.save(path)
        except Exception as exc:  # noqa: BLE001
            return self._fail("EXCEL_WRITE_ERROR", str(exc))
        finally:
            workbook.close()

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "file": str(path),
                "filename": path.name,
                "sheet": worksheet.title,
                "written_rows": len(input_data.get("rows") or [])
                + (1 if headers else 0),
                "path": str(path),
            },
        )


class ExcelEditWorkbookTool(_WorkspaceTool):
    """Редактирование существующего .xlsx набором операций."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент редактирования книги Excel."""
        super().__init__(
            ToolDefinition(
                name="excel.edit_workbook",
                title="Редактирование Excel",
                description=(
                    "Изменяет существующий .xlsx: добавляет строки, задаёт ячейки, "
                    "добавляет/удаляет листы."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "Существующий .xlsx в папке агента"},
                        "operations": {
                            "type": "array",
                            "description": (
                                "Правки существующего листа: add_sheet, delete_sheet, "
                                "append_row, set_cell. Новый файл так не создают."
                            ),
                        },
                    },
                    "required": ["filename", "operations"],
                },
                output_schema={"type": "object"},
            ),
            resolver,
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Применить операции редактирования к книге Excel."""
        from openpyxl import load_workbook

        operations = input_data.get("operations")
        if not isinstance(operations, list) or not operations:
            return self._fail(
                "INVALID_OPERATIONS", "Передайте непустой список operations."
            )

        try:
            workspace = self._workspace(input_data)
            path = workspace.resolve(
                _ensure_xlsx(input_data.get("filename", "")), must_exist=True
            )
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        try:
            workbook = load_workbook(path)
        except Exception as exc:  # noqa: BLE001
            return self._fail("EXCEL_READ_ERROR", str(exc))

        applied: list[str] = []
        try:
            for operation in operations:
                error = self._apply_operation(workbook, operation, applied)
                if error is not None:
                    workbook.close()
                    return self._fail("INVALID_OPERATION", error)
            workbook.save(path)
        except Exception as exc:  # noqa: BLE001
            return self._fail("EXCEL_WRITE_ERROR", str(exc))
        finally:
            workbook.close()

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "file": str(path),
                "filename": path.name,
                "applied": applied,
                "path": str(path),
            },
        )

    def _apply_operation(self, workbook, operation: dict, applied: list[str]) -> str | None:
        """Применить одну операцию; вернуть текст ошибки или None."""
        if not isinstance(operation, dict):
            return "Операция должна быть объектом"
        action = operation.get("action")

        if action == "add_sheet":
            name = str(operation.get("name") or "").strip()
            if not name:
                return "add_sheet требует name"
            workbook.create_sheet(title=name[:31])
            applied.append(f"add_sheet:{name}")
            return None

        if action == "delete_sheet":
            name = str(operation.get("name") or "").strip()
            if name not in workbook.sheetnames:
                return f"delete_sheet: лист {name!r} не найден"
            del workbook[name]
            applied.append(f"delete_sheet:{name}")
            return None

        sheet_name = operation.get("sheet")
        if sheet_name and sheet_name not in workbook.sheetnames:
            return f"Лист {sheet_name!r} не найден"
        worksheet = workbook[sheet_name] if sheet_name else workbook.active

        if action == "append_row":
            values = operation.get("values")
            if not isinstance(values, list):
                return "append_row требует values (список)"
            worksheet.append(values)
            applied.append(f"append_row:{worksheet.title}")
            return None

        if action == "set_cell":
            cell = operation.get("cell")
            if not cell:
                return "set_cell требует cell (например 'B2')"
            worksheet[str(cell)] = operation.get("value")
            applied.append(f"set_cell:{worksheet.title}!{cell}")
            return None

        return (
            f"Неизвестное действие: {action!r}. "
            "Допустимы add_sheet, delete_sheet, append_row, set_cell. "
            "Новый файл — excel.create_workbook (filename, headers, rows), не action=export."
        )


def register_excel_tools(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать Excel-инструменты в реестре."""
    for tool in [
        ExcelListFilesTool(resolver),
        ExcelReadWorkbookTool(resolver),
        ExcelCreateWorkbookTool(resolver),
        ExcelEditWorkbookTool(resolver),
    ]:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)

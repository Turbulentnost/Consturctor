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


_EXCEL_SUFFIXES = (".xlsx", ".xlsm")


def _is_excel_name(name: str) -> bool:
    lower = str(name).strip().lower()
    return any(lower.endswith(suffix) for suffix in _EXCEL_SUFFIXES)


def _ensure_xlsx(name: str) -> str:
    """Гарантировать расширение Excel, не склеивая его с .txt/.md и т.п."""
    name = str(name).strip().replace("\\", "/")
    if _is_excel_name(name):
        return name
    path = Path(name)
    if path.suffix:
        return path.with_suffix(".xlsx").as_posix()
    return f"{name}.xlsx"


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
                description=(
                    "Возвращает список файлов в рабочей папке агента, "
                    "включая materials/ и загруженные Excel."
                ),
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
                description=(
                    "Читает данные листа .xlsx/.xlsm (заголовки и строки). "
                    "Только книги Excel. Тексты, регламент и notes.txt — "
                    "встроенным Read, не этим инструментом. "
                    "filename — имя или путь из excel.list_files, "
                    "включая materials/attachments/."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": (
                                "Имя или относительный путь из excel.list_files, "
                                "например materials/attachments/002_report.xlsx"
                            ),
                        },
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
            path = self._resolve_workbook(workspace, input_data.get("filename", ""))
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))
        if isinstance(path, ToolCallResult):
            return path

        max_rows = int(input_data.get("max_rows") or 500)
        try:
            workbook = load_workbook(path, data_only=True)
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
            from app.tools.ac.office_style import data_start_row

            start = max(1, data_start_row(workbook, worksheet))
            last = worksheet.max_row or start
            end = min(last, start + max(1, max_rows) - 1)
            rows: list[list] = []
            for row in worksheet.iter_rows(min_row=start, max_row=end, values_only=True):
                rows.append([_cell_value(cell) for cell in row])
            while rows and all(cell in (None, "") for cell in rows[-1]):
                rows.pop()
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

    def _resolve_workbook(self, workspace, filename: object):
        """Найти .xlsx или сказать, что файл есть, но это не Excel."""
        raw = str(filename or "").strip()
        if not raw:
            return self._fail("INVALID_FILENAME", "Укажи filename книги Excel.")
        try:
            existing = workspace.resolve(raw, must_exist=True)
        except WorkspaceError:
            existing = None
        if existing is not None:
            if _is_excel_name(existing.name):
                return existing
            relative = existing.relative_to(workspace.directory.resolve()).as_posix()
            return self._fail(
                "NOT_EXCEL",
                f"Файл на месте: {relative}. Это не Excel "
                f"({existing.suffix or 'без расширения'}). "
                "Тексты и регламент читай встроенным Read; "
                "excel.read_workbook — только для .xlsx/.xlsm.",
            )
        if _is_excel_name(raw) or not Path(raw.replace("\\", "/")).suffix:
            return workspace.resolve(_ensure_xlsx(raw), must_exist=True)
        raise WorkspaceError(f"Файл не найден: {raw}")


class ExcelCreateWorkbookTool(_WorkspaceTool):
    """Создание нового .xlsx в рабочей папке агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент создания книги Excel."""
        super().__init__(
            ToolDefinition(
                name="excel.create_workbook",
                title="Создание Excel",
                description=(
                    "Создаёт или перезаписывает оформленный .xlsx: баннер, тема, "
                    "цветная шапка, зебра, автофильтр, ширины колонок. "
                    "Голую таблицу не пишет. title/kpis усиливают шапку, "
                    "без title берётся имя файла."
                ),
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
                        "title": {"type": "string", "description": "Заголовок отчёта над таблицей"},
                        "subtitle": {"type": "string", "description": "Подзаголовок или период"},
                        "theme": {
                            "type": "string",
                            "enum": ["navy", "forest", "graphite", "wine", "sand"],
                            "description": "Цветовая тема оформления. По умолчанию navy.",
                        },
                        "kpis": {
                            "type": "array",
                            "description": "Плашки над таблицей: [{label, value, hint}]",
                        },
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
        try:
            workspace = self._workspace(input_data)
            path = workspace.resolve(_ensure_xlsx(input_data.get("filename", "")))
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        return _save_workbook(
            path,
            sheet=str(input_data.get("sheet") or "Лист1"),
            headers=input_data.get("headers") or [],
            rows=input_data.get("rows") or [],
            tool_name=self.definition.name,
            title=str(input_data.get("title") or path.stem),
            subtitle=str(input_data.get("subtitle") or ""),
            theme=input_data.get("theme"),
            kpis=input_data.get("kpis"),
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
        headers = input_data.get("headers")
        rows = input_data.get("rows")
        if (not isinstance(operations, list) or not operations) and (
            headers or rows is not None
        ):
            try:
                workspace = self._workspace(input_data)
                path = workspace.resolve(_ensure_xlsx(input_data.get("filename", "")))
            except WorkspaceError as exc:
                return self._fail("WORKSPACE_ERROR", str(exc))
            return _save_workbook(
                path,
                sheet=str(input_data.get("sheet") or "Лист1"),
                headers=headers or [],
                rows=rows or [],
                tool_name=self.definition.name,
                title=str(input_data.get("title") or path.stem),
                subtitle=str(input_data.get("subtitle") or ""),
                theme=input_data.get("theme"),
                kpis=input_data.get("kpis"),
            )
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
            from app.tools.ac.office_style import restyle_excel_workbook

            restyle_excel_workbook(
                workbook,
                theme=input_data.get("theme"),
                title=str(input_data.get("title") or path.stem),
            )
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


def _save_workbook(
    path: Path,
    *,
    sheet: str,
    headers: object,
    rows: object,
    tool_name: str,
    title: str = "",
    subtitle: str = "",
    theme: object = None,
    kpis: object | None = None,
) -> ToolCallResult:
    from openpyxl import Workbook

    from app.tools.ac.office_style import normalize_table, pretty_title, write_excel_sheet

    header_list, row_list = normalize_table(headers, rows)
    workbook = Workbook()
    try:
        worksheet = write_excel_sheet(
            workbook,
            sheet=sheet,
            headers=header_list,
            rows=row_list,
            title=pretty_title(title, path.name, sheet),
            subtitle=subtitle,
            theme=theme,
            kpis=kpis,
        )
        workbook.save(path)
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            error_type="EXCEL_WRITE_ERROR",
            error_message=str(exc),
        )
    finally:
        workbook.close()
    return ToolCallResult(
        ok=True,
        tool_name=tool_name,
        output_data={
            "file": str(path),
            "filename": path.name,
            "sheet": worksheet.title,
            "written_rows": len(row_list) + (1 if header_list else 0),
            "theme": str(theme or "navy"),
            "styled": True,
            "path": str(path),
        },
    )

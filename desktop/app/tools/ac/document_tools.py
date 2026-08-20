"""Создание и дополнение .docx в рабочей папке агента."""

from __future__ import annotations

from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspaceResolver, WorkspaceError
from app.tools.ac.base import BaseTool
from app.tools.ac.files_tools import resolve_local_path
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.plan_export import desktop_dir


def _write_docx(path: Path, *, title: str, paragraphs: list[str]) -> None:
    from docx import Document

    document = Document()
    if title.strip():
        document.add_heading(title.strip(), level=0)
    for block in paragraphs:
        text = (block or "").strip()
        if text:
            document.add_paragraph(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))


def _append_docx(path: Path, *, heading: str, paragraphs: list[str]) -> None:
    from docx import Document

    if path.is_file():
        document = Document(str(path))
    else:
        document = Document()
    if heading.strip():
        document.add_heading(heading.strip(), level=1)
    for block in paragraphs:
        text = (block or "").strip()
        if text:
            document.add_paragraph(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))


class DocumentWriteDocxTool(BaseTool):
    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="document.write_docx",
                title="Создать Word (.docx)",
                description=(
                    "Создаёт .docx в рабочей папке агента (out/). "
                    "Передайте title и paragraphs (список абзацев). "
                    "save_to_desktop=true — только если пользователь явно просил файл на рабочий стол."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "path": {"type": "string"},
                        "title": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                        "save_to_desktop": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        filename = str(input_data.get("filename") or "report.docx").strip()
        if not filename.lower().endswith(".docx"):
            filename += ".docx"
        workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
        raw_path = str(input_data.get("path") or "").strip()
        try:
            if raw_path:
                target = resolve_local_path(raw_path)
                if not workspace.is_path_allowed(target):
                    target = workspace.resolve_output(Path(raw_path).name)
            elif input_data.get("save_to_desktop"):
                target = desktop_dir() / Path(filename).name
            else:
                target = workspace.resolve_output(filename)
        except WorkspaceError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="WORKSPACE_ERROR",
                error_message=str(exc),
            )
        title = str(input_data.get("title") or "")
        paragraphs_raw = input_data.get("paragraphs") or []
        paragraphs = [str(p) for p in paragraphs_raw if str(p).strip()] if isinstance(paragraphs_raw, list) else []
        try:
            _write_docx(target, title=title, paragraphs=paragraphs)
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="DOCX_WRITE_ERROR",
                error_message=str(exc),
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "path": str(target),
                "workspace_path": str(target),
                "filename": target.name,
                "paragraph_count": len(paragraphs),
            },
        )


class DocumentAppendDocxTool(BaseTool):
    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="document.append_docx",
                title="Дописать в Word (.docx)",
                description="Добавляет раздел в конец существующего .docx в рабочей папке агента.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "heading": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["path"],
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        raw_path = str(input_data.get("path") or "").strip()
        if not raw_path:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_PATH",
                error_message="Укажите path к .docx",
            )
        workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
        target = resolve_local_path(raw_path)
        if not workspace.is_path_allowed(target):
            try:
                target = workspace.resolve_output(Path(raw_path).name, must_exist=True)
            except WorkspaceError:
                return ToolCallResult(
                    ok=False,
                    tool_name=self.definition.name,
                    error_type="WORKSPACE_ERROR",
                    error_message="Редактирование .docx разрешено только в рабочей папке агента.",
                )
        heading = str(input_data.get("heading") or "")
        paragraphs_raw = input_data.get("paragraphs") or []
        paragraphs = [str(p) for p in paragraphs_raw if str(p).strip()] if isinstance(paragraphs_raw, list) else []
        try:
            _append_docx(target, heading=heading, paragraphs=paragraphs)
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="DOCX_APPEND_ERROR",
                error_message=str(exc),
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "path": str(target),
                "workspace_path": str(target),
                "filename": target.name,
                "appended_paragraphs": len(paragraphs),
            },
        )


def register_document_tools(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    for tool in (DocumentWriteDocxTool(resolver), DocumentAppendDocxTool(resolver)):
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)

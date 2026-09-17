"""Чтение Word, PDF и картинок — вместо встроенного Read, который зависает на бинарниках."""

from __future__ import annotations

from pathlib import Path

from app.attachment_text import UNREADABLE, extract_attachment_text
from app.tools.ac.agent_workspace import AgentWorkspaceResolver, WorkspaceError
from app.tools.ac.base import BaseTool
from app.tools.ac.office_vision import VISION_MAX_PAGES, VisionRenderError, render_document_pages
from app.tools.ac.readable_files import (
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    READABLE_SUFFIXES,
    kind_for_suffix,
    resolve_readable_path,
)
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)

_DEFAULT_MAX_CHARS = 16_000
_SCAN_TEXT_CHARS = 80
_VISION_NEXT_STEP = (
    "Страницы уже переданы в модель Cursor SDK как изображения. "
    "Прочитай их глазами. Не вызывай Read, Grep и не ищи OCR."
)


class OfficeReadFileTool(BaseTool):
    """Текст из Word/PDF; сканы и фото — в зрение Cursor SDK."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="office.read_file",
                title="Чтение Word, PDF и картинок",
                description=(
                    "Читает Word (.docx), PDF и картинки (jpg/png/tif и др.). "
                    "Если есть текстовый слой — вернёт текст. "
                    "Скан или фото передаёт в зрение модели Cursor SDK "
                    "(страницы в ответе инструмента). "
                    "filename — имя из excel.list_files или saved_path после "
                    "onec.download_artifact (Temp/constructor-onec-artifacts). "
                    "Не используй встроенные Read и Grep для этих файлов: они зависают. "
                    "Excel — excel.read_workbook. Старый .doc не читается, нужен .docx."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=180,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": (
                                "Имя, относительный путь или saved_path "
                                "из onec.download_artifact"
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": "То же, что filename (saved_path)",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Обрезать текст, по умолчанию 16000",
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Для PDF: сколько страниц читать с начала",
                        },
                    },
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        raw = str(input_data.get("filename") or input_data.get("path") or "").strip()
        if not raw:
            return self._fail("INVALID_FILENAME", "Укажи filename или path.")
        try:
            workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
            path = resolve_readable_path(workspace, raw)
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        suffix = path.suffix.lower()
        kind = kind_for_suffix(suffix)
        if suffix == ".doc":
            return self._fail(
                "DOC_UNSUPPORTED",
                f"{path.name}: старый .doc не читается. Нужен .docx, PDF или картинка.",
            )
        if suffix not in READABLE_SUFFIXES:
            hint = "Excel — excel.read_workbook." if suffix in {".xlsx", ".xlsm"} else ""
            return self._fail(
                "UNSUPPORTED_TYPE",
                f"{path.name}: office.read_file читает Word, PDF и картинки. {hint}".strip(),
            )

        max_chars = _as_int(input_data.get("max_chars"), _DEFAULT_MAX_CHARS, lo=200, hi=80_000)
        max_pages = _as_int(input_data.get("max_pages"), 20, lo=1, hi=80)
        try:
            text = extract_attachment_text(
                str(path),
                max_chars=max_chars,
                max_pages=max_pages,
                ocr=False,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail("READ_ERROR", str(exc))

        usable = "" if UNREADABLE in (text or "") else (text or "").strip()
        wants_vision = kind == "image" or suffix in IMAGE_SUFFIXES
        if suffix in PDF_SUFFIXES and (not usable or len(usable) < _SCAN_TEXT_CHARS):
            wants_vision = True

        render_error = ""
        if wants_vision:
            vision_limit = min(max_pages, VISION_MAX_PAGES)
            try:
                rendered = render_document_pages(
                    path,
                    workspace.directory / "materials" / "vision",
                    max_pages=vision_limit,
                )
            except VisionRenderError as exc:
                render_error = str(exc)
                rendered = None
            except Exception as exc:  # noqa: BLE001
                render_error = str(exc)
                rendered = None
            if rendered and rendered.get("pages"):
                pages = [
                    {
                        "page": item["page"],
                        "path": _rel_to_workspace(workspace.directory, Path(item["path"])),
                        "mimeType": item["mimeType"],
                        "width": item["width"],
                        "height": item["height"],
                    }
                    for item in rendered["pages"]
                ]
                truncated = bool(rendered.get("truncated")) or usable.endswith("…")
                return ToolCallResult(
                    ok=True,
                    tool_name=self.definition.name,
                    output_data={
                        "filename": path.name,
                        "path": str(path),
                        "kind": kind,
                        "ocr": False,
                        "vision": True,
                        "vision_source": "cursor_sdk",
                        "text": usable,
                        "char_count": len(usable),
                        "truncated": truncated,
                        "page_count": rendered.get("page_count"),
                        "vision_pages": pages,
                        "max_pages": max_pages if suffix in PDF_SUFFIXES else None,
                        "next_step": _VISION_NEXT_STEP,
                    },
                )

        if not usable:
            return self._fail("UNREADABLE", _unreadable_message(path, kind, suffix, render_error))

        truncated = text.endswith("…") or text.endswith("\n…")
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "filename": path.name,
                "path": str(path),
                "kind": kind,
                "ocr": False,
                "vision": False,
                "text": usable,
                "char_count": len(usable),
                "truncated": truncated,
                "max_pages": max_pages if suffix in PDF_SUFFIXES else None,
            },
        )

    def _fail(self, error_type: str, message: str) -> ToolCallResult:
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type=error_type,
            error_message=message,
        )


def _rel_to_workspace(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _unreadable_message(path, kind: str, suffix: str, render_error: str = "") -> str:
    parts = [f"{path.name}: текст не извлечён."]
    if suffix in PDF_SUFFIXES:
        hint = _pdf_layer_hint(path)
        parts.append(hint or "В PDF нет текстового слоя.")
    elif kind == "image" or suffix in IMAGE_SUFFIXES:
        parts.append("Это картинка.")
    if render_error:
        parts.append(f"Страницы для Cursor SDK не сняты: {render_error[:180]}")
    else:
        parts.append("Не удалось передать страницы в модель Cursor SDK.")
    return " ".join(part for part in parts if part)


def _pdf_layer_hint(path) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        document = fitz.open(path)
        try:
            pages = len(document)
            chars = sum(len((page.get_text() or "").strip()) for page in document)
        finally:
            document.close()
    except Exception:  # noqa: BLE001
        return ""
    if chars:
        return f"Текстовый слой почти пустой ({chars} симв., {pages} стр.)."
    return f"PDF без текстового слоя ({pages} стр.) — скан."


def _as_int(value: object, default: int, *, lo: int, hi: int) -> int:
    try:
        number = int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        number = default
    return max(lo, min(hi, number))


def register_office_read_tools(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    tool = OfficeReadFileTool(resolver)
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)

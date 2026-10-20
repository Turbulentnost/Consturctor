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
    with_detected_suffix,
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
# One call returns a few pages of this file. The caller asks for the rest.
_VISION_PAGES_PER_CALL = 4
_FILE_MORE_STEP = (
    "В ответе страницы {start}–{last} файла {name}. "
    "Дальше этот же файл: office.read_file, тот же filename, start_page={next_start}."
)
_FILE_DONE_STEP = "Файл {name} прочитан. Страницы в ответе инструмента."


class OfficeReadFileTool(BaseTool):
    """Текст из Word/PDF; сканы и фото — в зрение Cursor SDK."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="office.read_file",
                title="Чтение Word, PDF и картинок",
                description=(
                    "Читает Word (.docx и старый .doc, включая таблицы), PDF, презентации .pptx "
                    "и картинки (jpg/png/tif и др.). "
                    "Если есть текстовый слой — вернёт текст. "
                    "Скан или фото передаёт в зрение модели Cursor SDK "
                    "(страницы в ответе инструмента). "
                    "filename — имя из excel.list_files или saved_path после "
                    "onec.download_artifact (Temp/constructor-onec-artifacts). "
                    "Не используй встроенные Read и Grep для этих файлов: они зависают. "
                    "Excel — excel.read_workbook."
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
                            "description": "Для PDF: сколько страниц читать после start_page",
                        },
                        "start_page": {
                            "type": "integer",
                            "description": (
                                "С какой страницы читать. 2 — пропустить обложку. "
                                "Если в файле одна страница, читается она."
                            ),
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
            path = with_detected_suffix(resolve_readable_path(workspace, raw))
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        suffix = path.suffix.lower()
        kind = kind_for_suffix(suffix)
        if suffix not in READABLE_SUFFIXES:
            hint = "Excel — excel.read_workbook." if suffix in {".xlsx", ".xlsm"} else ""
            return self._fail(
                "UNSUPPORTED_TYPE",
                f"{path.name}: office.read_file читает Word, PDF и картинки. {hint}".strip(),
            )

        max_chars = _as_int(input_data.get("max_chars"), _DEFAULT_MAX_CHARS, lo=200, hi=80_000)
        max_pages = _as_int(input_data.get("max_pages"), 20, lo=1, hi=80)
        start_page = _as_int(input_data.get("start_page"), 1, lo=1, hi=80)
        try:
            text = extract_attachment_text(
                str(path),
                max_chars=max_chars,
                max_pages=max_pages,
                start_page=start_page,
                ocr=False,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail("READ_ERROR", str(exc))

        usable = "" if UNREADABLE in (text or "") else (text or "").strip()
        wants_vision = kind == "image" or suffix in IMAGE_SUFFIXES
        if suffix in PDF_SUFFIXES and (not usable or len(usable) < _SCAN_TEXT_CHARS):
            wants_vision = True
        if kind in {"word", "slides"} and not usable:
            wants_vision = True

        render_error = ""
        if wants_vision:
            vision_limit = min(max_pages, _VISION_PAGES_PER_CALL, VISION_MAX_PAGES)
            try:
                if kind == "word":
                    rendered = _render_word_images(
                        path,
                        workspace.directory / "materials" / "vision",
                        max_pages=vision_limit,
                    )
                elif kind == "slides":
                    rendered = _render_slide_images(
                        path,
                        workspace.directory / "materials" / "vision",
                        max_pages=vision_limit,
                    )
                else:
                    rendered = render_document_pages(
                        path,
                        workspace.directory / "materials" / "vision",
                        max_pages=vision_limit,
                        start_page=start_page,
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
                delivered = len(pages)
                start = int(rendered.get("start_page") or start_page)
                total = int(rendered.get("page_count") or 0)
                last_page = start + delivered - 1 if delivered else start
                more = bool(total and last_page < total)
                next_start = last_page + 1
                if more:
                    next_step = _FILE_MORE_STEP.format(
                        name=path.name,
                        start=start,
                        last=last_page,
                        next_start=next_start,
                    )
                else:
                    next_step = _FILE_DONE_STEP.format(name=path.name)
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
                        "cached": False,
                        "text": usable,
                        "char_count": len(usable),
                        "truncated": truncated or more,
                        "page_count": total or rendered.get("page_count"),
                        "delivered_pages": delivered,
                        "start_page": start,
                        "next_start": next_start if more else None,
                        "vision_pages": pages,
                        "max_pages": max_pages if suffix in PDF_SUFFIXES else None,
                        "next_step": next_step,
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
                "start_page": start_page if suffix in PDF_SUFFIXES else None,
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


def _render_word_images(source: Path, dest_dir: Path, *, max_pages: int) -> dict | None:
    """Pictures inside a Word file that has no paragraph or table text."""
    try:
        import docx
    except ImportError:
        return None
    document = docx.Document(str(source))
    blobs: list[tuple[str, bytes]] = []
    for rel in document.part.rels.values():
        if "image" not in str(getattr(rel, "reltype", "")):
            continue
        part = getattr(rel, "target_part", None)
        blob = getattr(part, "blob", b"") or b""
        if len(blob) < 2048:
            continue
        blobs.append((str(getattr(part, "content_type", "") or ""), blob))
    return _write_vision_blobs(source, dest_dir, blobs, max_pages=max_pages)


def _render_slide_images(source: Path, dest_dir: Path, *, max_pages: int) -> dict | None:
    import zipfile

    blobs: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(source) as archive:
            names = sorted(name for name in archive.namelist() if name.startswith("ppt/media/"))
            for name in names:
                blob = archive.read(name)
                if len(blob) < 2048:
                    continue
                blobs.append((name, blob))
    except Exception:  # noqa: BLE001
        return None
    return _write_vision_blobs(source, dest_dir, blobs, max_pages=max_pages)


def _write_vision_blobs(
    source: Path,
    dest_dir: Path,
    blobs: list[tuple[str, bytes]],
    *,
    max_pages: int,
) -> dict | None:
    if not blobs:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = "".join(ch if ch.isalnum() else "-" for ch in source.stem)[:40] or "page"
    limit = max(1, int(max_pages or 1))
    pages: list[dict] = []
    for index, (hint, blob) in enumerate(blobs[:limit], start=1):
        folded = hint.casefold()
        if blob.startswith(b"\x89PNG") or "png" in folded:
            ext, mime = ".png", "image/png"
        else:
            ext, mime = ".jpg", "image/jpeg"
        dest = dest_dir / f"{stem}-p{index:03d}{ext}"
        dest.write_bytes(blob)
        pages.append(
            {
                "page": index,
                "path": str(dest.resolve()),
                "mimeType": mime,
                "width": 0,
                "height": 0,
            }
        )
    return {
        "pages": pages,
        "page_count": len(blobs),
        "start_page": 1,
        "truncated": len(blobs) > len(pages),
    }


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

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".xml",
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".log",
    ".ini",
    ".cfg",
    ".conf",
    ".rtf",
}
DOC_SUFFIXES = {".pdf", ".docx", ".doc"}
SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | DOC_SUFFIXES | SPREADSHEET_SUFFIXES | IMAGE_SUFFIXES
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


class DocumentError(Exception):
    pass


def load_attachment_bytes(name: str, raw: bytes, *, ocr: bool = True) -> dict:
    suffix = Path(name).suffix.lower()
    file_name = Path(name).name or "file"
    if not raw:
        raise DocumentError("Файл пустой.")
    if suffix in IMAGE_SUFFIXES:
        return _load_image(name, raw, suffix, ocr=ocr)
    if len(raw) > MAX_FILE_BYTES:
        raise DocumentError(
            f"{file_name}: слишком большой файл ({len(raw) // (1024 * 1024)} МБ). "
            f"Лимит — {MAX_FILE_BYTES // (1024 * 1024)} МБ."
        )
    if suffix == ".pdf":
        try:
            text = _read_pdf_bytes(raw)
        except DocumentError:
            text = ""
        if not text.strip() and ocr:
            text = _ocr_visual(file_name, raw)
        kind = "text"
        mime = "application/pdf"
    elif suffix == ".docx":
        text = _read_docx_bytes(raw)
        kind = "text"
        mime = _guess_text_mime(suffix)
    elif suffix in SPREADSHEET_SUFFIXES:
        try:
            text = _read_xlsx_bytes(raw)
        except DocumentError:
            if suffix != ".xls":
                raise
            text = ""
        kind = "text"
        mime = _guess_text_mime(suffix)
    elif suffix in TEXT_SUFFIXES:
        text = _read_text_bytes(raw)
        kind = "text"
        mime = _guess_text_mime(suffix)
    else:
        text = ""
        kind = "binary"
        mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    text = (text or "").strip()
    if not text:
        text = f"[файл {file_name}: текст не извлечён, исходный файл сохранён]"
    return {
        "name": file_name,
        "text": text,
        "kind": kind,
        "mime_type": mime,
        "data_b64": "",
    }


def compose_document(attachments: list[dict], notes: str = "") -> tuple[str, str]:
    parts: list[str] = []
    names: list[str] = []
    image_n = 0
    for att in attachments:
        name = str(att.get("name") or "file")
        names.append(name)
        if att.get("kind") == "image":
            image_n += 1
            parts.append(
                f"===== IMAGE: {name} =====\n"
                f"(изображение #{image_n}, mime={att.get('mime_type') or 'image'}; "
                f"передано агенту как vision-вложение)\n"
                f"===== END IMAGE ====="
            )
            continue
        body = str(att.get("text") or "").strip()
        if not body:
            continue
        parts.append(f"===== FILE: {name} =====\n{body}\n===== END FILE =====")
    notes_text = (notes or "").strip()
    if notes_text:
        parts.append(f"===== NOTES =====\n{notes_text}\n===== END NOTES =====")
    if not parts and not names:
        return "", ""
    if names:
        real = [name for name in names if name.casefold() not in {"notes.txt", "notes", "file"}]
        if real:
            document_name = real[0] if len(real) == 1 else f"{len(real)} файлов"
        else:
            document_name = "материалы"
    else:
        document_name = "материалы"
    return document_name, "\n\n".join(parts)


def collect_prompt_images(attachments: list[dict]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for att in attachments:
        if att.get("kind") != "image":
            continue
        data = str(att.get("data_b64") or "").strip()
        mime = str(att.get("mime_type") or "").strip()
        if not data:
            # Fallback: reload bytes from stored path (e.g. after payload slim/migrate).
            path = str(att.get("path") or "").strip()
            if path and Path(path).is_file():
                raw = Path(path).read_bytes()
                if raw and len(raw) <= MAX_IMAGE_BYTES:
                    data = base64.b64encode(raw).decode("ascii")
                    if not mime:
                        suffix = Path(path).suffix.lower()
                        mime = _MIME_BY_SUFFIX.get(suffix) or "image/png"
        if not data or not mime:
            continue
        images.append({"data": data, "mimeType": mime})
        if len(images) >= MAX_IMAGES:
            break
    return images


def _ocr_visual(name: str, raw: bytes) -> str:
    try:
        from app.services.ocr_extract import extract_visual_text

        return (extract_visual_text(name, raw) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "attachment ocr failed name=%s detail=%s",
            ascii(name),
            ascii(str(exc)),
        )
        return ""


def _load_image(name: str, raw: bytes, suffix: str, *, ocr: bool = True) -> dict:
    mime = _MIME_BY_SUFFIX.get(suffix) or mimetypes.guess_type(name)[0] or "image/png"
    file_name = Path(name).name
    if not raw:
        raise DocumentError("Изображение пустое.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise DocumentError(
            f"{file_name}: слишком большой файл ({len(raw) // (1024 * 1024)} МБ). "
            f"Лимит API — {MAX_IMAGE_BYTES // (1024 * 1024)} МБ."
        )
    text = _ocr_visual(file_name, raw) if ocr else ""
    if not text:
        text = f"[изображение: {file_name}]"
    return {
        "name": file_name,
        "text": text,
        "kind": "image",
        "mime_type": mime,
        "data_b64": base64.b64encode(raw).decode("ascii"),
    }


def _guess_text_mime(suffix: str) -> str:
    return {
        ".json": "application/json",
        ".xml": "application/xml",
        ".html": "text/html",
        ".htm": "text/html",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    }.get(suffix, "text/plain")


def _read_text_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentError("Не удалось прочитать текстовый файл (кодировка).")


def _read_pdf_bytes(raw: bytes) -> str:
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise DocumentError("Для PDF нужен pymupdf") from exc
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        parts = [page.get_text() or "" for page in doc]
        doc.close()
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Не удалось разобрать PDF: {exc}") from exc
    return "\n\n".join(parts)


def _read_docx_bytes(raw: bytes) -> str:
    try:
        import docx
    except ImportError as exc:
        raise DocumentError("Для DOCX нужен python-docx") from exc
    try:
        document = docx.Document(io.BytesIO(raw))
        parts = [para.text for para in document.paragraphs]
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Не удалось разобрать DOCX: {exc}") from exc
    return "\n".join(parts)


def _read_xlsx_bytes(raw: bytes) -> str:
    try:
        import openpyxl
    except ImportError as exc:
        raise DocumentError("Для XLSX нужен openpyxl") from exc
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in workbook.worksheets:
            parts.append(f"===== SHEET: {sheet.title} =====")
            for row in sheet.iter_rows(values_only=True):
                values = [str(cell).strip() if cell is not None else "" for cell in row]
                while values and not values[-1]:
                    values.pop()
                if values:
                    parts.append("\t".join(values))
        workbook.close()
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Не удалось разобрать XLSX: {exc}") from exc
    return "\n".join(parts)

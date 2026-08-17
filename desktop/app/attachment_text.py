"""Извлечение текста из вложений паспорта (txt/md и по возможности pdf/docx)."""

from __future__ import annotations

from pathlib import Path

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_MAX_CHARS = 12_000


def extract_attachment_text(path: str) -> str:
    file_path = Path(path)
    name = file_path.name
    suffix = file_path.suffix.lower()
    if not file_path.is_file():
        return f"файл {name} прикреплён, текст не извлечён (файл не найден)"
    try:
        if suffix in _TEXT_SUFFIXES:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            text = _read_pdf(file_path)
        elif suffix == ".docx":
            text = _read_docx(file_path)
        elif suffix == ".doc":
            text = _read_doc(file_path)
        else:
            text = ""
    except Exception:  # noqa: BLE001
        text = ""
    text = (text or "").strip()
    if not text:
        return f"файл {name} прикреплён, текст не извлечён"
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS].rstrip() + "\n…"
    return text


def format_attachments_block(paths: list[str]) -> str:
    if not paths:
        return ""
    parts: list[str] = ["", "Прикреплено:"]
    for path in paths:
        name = Path(path).name
        extracted = extract_attachment_text(path)
        parts.append(f"— {name}")
        parts.append(extracted)
    return "\n".join(parts).rstrip()


def _read_pdf(path: Path) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    doc = fitz.open(path)
    try:
        return "\n\n".join((page.get_text() or "") for page in doc)
    finally:
        doc.close()


def _read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        return ""
    document = docx.Document(str(path))
    return "\n".join(para.text for para in document.paragraphs)


def _read_doc(path: Path) -> str:
    # Старый .doc без внешних утилит обычно не разбирается.
    return ""

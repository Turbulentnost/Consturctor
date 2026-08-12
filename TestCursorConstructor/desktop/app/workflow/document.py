from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from app.workflow.models import AttachedFile

# Text-like formats read as UTF text.
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

# Office / PDF → extracted text.
DOC_SUFFIXES = {".pdf", ".docx"}

# Vision-capable images for Cloud Agents API (prompt.images).
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

SUPPORTED_SUFFIXES = TEXT_SUFFIXES | DOC_SUFFIXES | IMAGE_SUFFIXES

# API: max 5 images, ≤ 15 MB each.
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 15 * 1024 * 1024

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class DocumentError(Exception):
    pass


def supported_filter_label() -> str:
    return (
        "Документы и изображения "
        f"({', '.join(sorted(SUPPORTED_SUFFIXES))})"
    )


def load_document(path: str | Path) -> tuple[str, str]:
    """Backward-compatible: return (name, text). Images get a short placeholder text."""
    att = load_attachment(path)
    if att.kind == "image":
        return att.name, att.text or f"[изображение: {att.name}]"
    return att.name, att.text


def load_attachment(path: str | Path) -> AttachedFile:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise DocumentError(f"Файл не найден: {p}")

    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DocumentError(
            f"Формат «{suffix or 'без расширения'}» не поддерживается. "
            f"Допустимо: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    resolved = str(p.resolve())
    if suffix in IMAGE_SUFFIXES:
        return _load_image(p, resolved)
    if suffix == ".pdf":
        text = _read_pdf(p)
        kind = "text"
    elif suffix == ".docx":
        text = _read_docx(p)
        kind = "text"
    else:
        text = _read_text(p)
        kind = "text"

    text = text.strip()
    if not text:
        raise DocumentError("Документ пуст или не удалось извлечь текст.")
    return AttachedFile(
        name=p.name,
        text=text,
        path=resolved,
        kind=kind,
        mime_type=_guess_text_mime(suffix),
    )


def compose_document(
    attachments: list[AttachedFile],
    notes: str = "",
) -> tuple[str, str]:
    """Build (document_name, document_text) from files + optional notes."""
    parts: list[str] = []
    names: list[str] = []
    image_n = 0
    for att in attachments:
        names.append(att.name)
        if att.kind == "image":
            image_n += 1
            parts.append(
                f"===== IMAGE: {att.name} =====\n"
                f"(изображение #{image_n}, mime={att.mime_type or 'image'}; "
                f"передано агенту как vision-вложение)\n"
                f"===== END IMAGE ====="
            )
            continue
        body = (att.text or "").strip()
        if not body:
            continue
        parts.append(f"===== FILE: {att.name} =====\n{body}\n===== END FILE =====")
    notes_text = (notes or "").strip()
    if notes_text:
        parts.append(f"===== NOTES =====\n{notes_text}\n===== END NOTES =====")
    if not parts and not names:
        return "", ""
    if not parts and names:
        # only empty images somehow
        return (names[0] if len(names) == 1 else f"{len(names)} файлов"), ""
    if names:
        document_name = names[0] if len(names) == 1 else f"{len(names)} файлов"
    else:
        document_name = "notes"
    return document_name, "\n\n".join(parts)


def collect_prompt_images(attachments: list[AttachedFile]) -> list[dict[str, str]]:
    """Build Cloud Agents prompt.images payloads (max MAX_IMAGES)."""
    images: list[dict[str, str]] = []
    for att in attachments:
        if att.kind != "image":
            continue
        data = (att.data_b64 or "").strip()
        mime = (att.mime_type or "").strip()
        if not data and att.path:
            try:
                refreshed = _load_image(Path(att.path), att.path)
                data = refreshed.data_b64
                mime = refreshed.mime_type
            except DocumentError:
                continue
        if not data or not mime:
            continue
        images.append({"data": data, "mimeType": mime})
        if len(images) >= MAX_IMAGES:
            break
    return images


def _load_image(p: Path, resolved: str) -> AttachedFile:
    suffix = p.suffix.lower()
    mime = _MIME_BY_SUFFIX.get(suffix) or mimetypes.guess_type(p.name)[0] or "image/png"
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise DocumentError(f"Не удалось прочитать изображение: {exc}") from exc
    if not raw:
        raise DocumentError("Изображение пустое.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise DocumentError(
            f"{p.name}: слишком большой файл ({len(raw) // (1024 * 1024)} МБ). "
            f"Лимит API — {MAX_IMAGE_BYTES // (1024 * 1024)} МБ."
        )
    b64 = base64.b64encode(raw).decode("ascii")
    return AttachedFile(
        name=p.name,
        text=f"[изображение: {p.name}]",
        path=resolved,
        kind="image",
        mime_type=mime,
        data_b64=b64,
    )


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
    }.get(suffix, "text/plain")


def _read_text(p: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return p.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    raise DocumentError("Не удалось прочитать текстовый файл (кодировка).")


def _read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # noqa: BLE001
        raise DocumentError(
            "Для PDF установите зависимость: pip install pypdf"
        ) from exc
    try:
        reader = PdfReader(str(p))
        parts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Не удалось разобрать PDF: {exc}") from exc
    return "\n\n".join(parts)


def _read_docx(p: Path) -> str:
    try:
        import docx  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise DocumentError(
            "Для DOCX установите зависимость: pip install python-docx"
        ) from exc
    try:
        document = docx.Document(str(p))
        parts = [para.text for para in document.paragraphs]
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Не удалось разобрать DOCX: {exc}") from exc
    return "\n".join(parts)

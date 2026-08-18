from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

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
DOC_SUFFIXES = {".pdf", ".docx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | DOC_SUFFIXES | IMAGE_SUFFIXES
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


def load_attachment_bytes(name: str, raw: bytes) -> dict:
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DocumentError(
            f"Формат «{suffix or 'без расширения'}» не поддерживается. "
            f"Допустимо: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    if suffix in IMAGE_SUFFIXES:
        return _load_image(name, raw, suffix)
    if suffix == ".pdf":
        text = _read_pdf_bytes(raw)
        kind = "text"
    elif suffix == ".docx":
        text = _read_docx_bytes(raw)
        kind = "text"
    else:
        text = _read_text_bytes(raw)
        kind = "text"
    text = text.strip()
    if not text:
        raise DocumentError("Документ пуст или не удалось извлечь текст.")
    return {
        "name": Path(name).name,
        "text": text,
        "kind": kind,
        "mime_type": _guess_text_mime(suffix),
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


def _load_image(name: str, raw: bytes, suffix: str) -> dict:
    mime = _MIME_BY_SUFFIX.get(suffix) or mimetypes.guess_type(name)[0] or "image/png"
    if not raw:
        raise DocumentError("Изображение пустое.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise DocumentError(
            f"{name}: слишком большой файл ({len(raw) // (1024 * 1024)} МБ). "
            f"Лимит API — {MAX_IMAGE_BYTES // (1024 * 1024)} МБ."
        )
    return {
        "name": Path(name).name,
        "text": f"[изображение: {Path(name).name}]",
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
    import io

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

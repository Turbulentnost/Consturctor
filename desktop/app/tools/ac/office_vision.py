"""Снять страницы документа для зрения Cursor SDK — без LM Studio OCR."""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
VISION_MAX_PAGES = 8
_MAX_WIDTH = 1280
_JPEG_QUALITY = 72
_SAFE_STEM = re.compile(r"[^\w\-]+", re.UNICODE)


class VisionRenderError(Exception):
    """Не удалось снять страницы для модели Cursor."""


def render_document_pages(
    source: Path,
    dest_dir: Path,
    *,
    max_pages: int = VISION_MAX_PAGES,
) -> dict:
    """Вернуть JPEG-страницы: pages[{page, path, mimeType, width, height}]."""
    path = Path(source)
    if not path.is_file():
        raise VisionRenderError(f"файл не найден: {path.name}")
    try:
        import fitz
    except ImportError as exc:
        raise VisionRenderError("нет pymupdf, страницы для Cursor SDK не снять") from exc

    limit = max(1, min(int(max_pages or VISION_MAX_PAGES), VISION_MAX_PAGES))
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(path.name)
    suffix = path.suffix.lower()

    if suffix in PDF_SUFFIXES:
        document = fitz.open(path)
    elif suffix in IMAGE_SUFFIXES:
        document = _open_image(fitz, path)
    else:
        raise VisionRenderError(f"зрение SDK не умеет {suffix or 'этот тип'}")

    pages: list[dict] = []
    try:
        total = len(document)
        if total <= 0:
            raise VisionRenderError("в файле нет страниц")
        for index, page in enumerate(document, start=1):
            if index > limit:
                break
            pix = _page_pixmap(page)
            dest = dest_dir / f"{stem}-p{index:03d}"
            saved, mime = _save_pixmap(pix, dest)
            pages.append(
                {
                    "page": index,
                    "path": str(saved.resolve()),
                    "mimeType": mime,
                    "width": int(pix.width),
                    "height": int(pix.height),
                }
            )
    finally:
        document.close()

    if not pages:
        raise VisionRenderError("страницы не сняты")
    return {
        "pages": pages,
        "page_count": total,
        "truncated": total > limit,
    }


def _open_image(fitz, path: Path):
    try:
        return fitz.open(path)
    except Exception as exc:
        raise VisionRenderError(f"не открыть картинку: {exc}") from exc


def _page_pixmap(page):
    import fitz

    width = max(float(page.rect.width), 1.0)
    zoom = min(2.0, _MAX_WIDTH / width)
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)


def _save_pixmap(pix, dest: Path) -> tuple[Path, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    jpeg = dest.with_suffix(".jpg")
    try:
        pix.save(str(jpeg), jpg_quality=_JPEG_QUALITY)
        return jpeg, "image/jpeg"
    except TypeError:
        pass
    except Exception:
        pass
    png = dest.with_suffix(".png")
    pix.save(str(png))
    return png, "image/png"


def _safe_stem(name: str) -> str:
    cleaned = _SAFE_STEM.sub("_", Path(name).stem).strip("._")[:80]
    return cleaned or "page"

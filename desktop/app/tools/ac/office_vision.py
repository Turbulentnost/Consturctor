"""Снять страницы документа для зрения Cursor SDK — без LM Studio OCR."""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
VISION_MAX_PAGES = 16
_MAX_WIDTH = 800
_JPEG_QUALITY = 36
_MAX_JPEG_BYTES = 80_000
_SAFE_STEM = re.compile(r"[^\w\-]+", re.UNICODE)


class VisionRenderError(Exception):
    """Не удалось снять страницы для модели Cursor."""


def render_document_pages(
    source: Path,
    dest_dir: Path,
    *,
    max_pages: int = VISION_MAX_PAGES,
    start_page: int = 1,
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
    start = max(1, int(start_page or 1))
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
    reused_count = 0
    try:
        total = len(document)
        if total <= 0:
            raise VisionRenderError("в файле нет страниц")
        if start > total:
            start = 1
        taken = 0
        for index, page in enumerate(document, start=1):
            if index < start:
                continue
            if taken >= limit:
                break
            dest = dest_dir / f"{stem}-p{index:03d}"
            reused = _reuse_page(dest)
            if reused:
                reused_count += 1
                pages.append({"page": index, **reused})
            else:
                pix = _page_pixmap(page)
                saved, mime = _save_pixmap(pix, dest, page=page)
                pages.append(
                    {
                        "page": index,
                        "path": str(saved.resolve()),
                        "mimeType": mime,
                        "width": int(pix.width),
                        "height": int(pix.height),
                    }
                )
            taken += 1
    finally:
        document.close()

    if not pages:
        raise VisionRenderError("страницы не сняты")
    last = int(pages[-1]["page"])
    return {
        "pages": pages,
        "page_count": total,
        "start_page": start,
        "truncated": last < total,
        "cached": reused_count == len(pages),
    }


def _reuse_page(dest: Path) -> dict | None:
    for suffix, mime in ((".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".png", "image/png")):
        existing = dest.with_suffix(suffix)
        if not existing.is_file():
            continue
        size = existing.stat().st_size
        if 800 < size <= _MAX_JPEG_BYTES:
            return {
                "path": str(existing.resolve()),
                "mimeType": mime,
                "width": 0,
                "height": 0,
            }
    return None


def _open_image(fitz, path: Path):
    try:
        return fitz.open(path)
    except Exception as exc:
        raise VisionRenderError(f"не открыть картинку: {exc}") from exc


def _page_pixmap(page, *, max_width: int = _MAX_WIDTH):
    import fitz

    width = max(float(page.rect.width), 1.0)
    zoom = min(1.4, max(240, int(max_width)) / width)
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)


def _save_pixmap(pix, dest: Path, page=None) -> tuple[Path, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    jpeg = dest.with_suffix(".jpg")
    quality = _JPEG_QUALITY
    current = pix
    max_width = max(int(getattr(pix, "width", 0) or _MAX_WIDTH), 240)
    for _ in range(5):
        try:
            current.save(str(jpeg), jpg_quality=quality)
            if jpeg.is_file() and jpeg.stat().st_size <= _MAX_JPEG_BYTES:
                return jpeg, "image/jpeg"
        except TypeError:
            break
        except Exception:
            break
        quality = max(22, quality - 6)
        if page is not None and max_width > 560:
            max_width = int(max_width * 0.8)
            current = _page_pixmap(page, max_width=max_width)
    if jpeg.is_file() and jpeg.stat().st_size > 800:
        return jpeg, "image/jpeg"
    png = dest.with_suffix(".png")
    pix.save(str(png))
    return png, "image/png"


def _safe_stem(name: str) -> str:
    cleaned = _SAFE_STEM.sub("_", Path(name).stem).strip("._")[:80]
    return cleaned or "page"

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.services.regulation.types import ExtractedDocument
from app.services.regulation.vlm_client import VlmError, recognize_pages


def extract_pdf_scan(path: Path, *, work_dir: Path) -> ExtractedDocument:
    images = _render_pages(path, work_dir=work_dir)
    blocks: list[ExtractedBlock] = []
    batch_size = max(1, settings.ocr_pages_per_batch)
    for start in range(0, len(images), batch_size):
        batch = images[start : start + batch_size]
        try:
            blocks.extend(recognize_pages(batch))
        except VlmError as exc:
            raise RuntimeError(str(exc)) from exc
    return ExtractedDocument(page_count=len(images), blocks=blocks, is_scan=True)


def _render_pages(path: Path, *, work_dir: Path) -> list[tuple[int, Path]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Для подготовки PDF-скана к отправке в LM Studio требуется pymupdf") from exc

    out_dir = work_dir / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    images: list[tuple[int, Path]] = []
    doc = fitz.open(str(path))
    try:
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_path = out_dir / f"page-{idx:03d}.png"
            pix.save(str(image_path))
            images.append((idx, image_path))
    finally:
        doc.close()
    return images

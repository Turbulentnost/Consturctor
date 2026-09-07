from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.services.regulation.types import ExtractedBlock, ExtractedDocument
from app.services.regulation.vlm_client import VlmError, recognize_pages

logger = logging.getLogger(__name__)


def extract_pdf_scan(path: Path, *, work_dir: Path) -> ExtractedDocument:
    images = _render_pages(path, work_dir=work_dir)
    if not images:
        raise RuntimeError("PDF scan has 0 renderable pages")
    blocks: list[ExtractedBlock] = []
    batch_size = max(1, settings.ocr_pages_per_batch)
    last_error: Exception | None = None
    for start in range(0, len(images), batch_size):
        batch = images[start : start + batch_size]
        first_page = batch[0][0]
        last_page = batch[-1][0]
        logger.info(
            "lm studio ocr batch start pages=%s-%s of %s",
            first_page,
            last_page,
            len(images),
        )
        try:
            part = recognize_pages(batch)
        except VlmError as exc:
            last_error = exc
            logger.warning(
                "lm studio ocr batch failed pages=%s-%s detail=%s",
                first_page,
                last_page,
                ascii(str(exc)),
            )
            if blocks:
                logger.warning(
                    "lm studio ocr keep %s blocks from earlier pages",
                    len(blocks),
                )
                break
            raise RuntimeError(str(exc)) from exc
        blocks.extend(part)
        logger.info(
            "lm studio ocr batch ok pages=%s-%s blocks=%s",
            first_page,
            last_page,
            len(part),
        )
    if not blocks:
        raise RuntimeError(str(last_error or "LM Studio OCR returned no text"))
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

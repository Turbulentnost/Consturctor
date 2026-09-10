"""OCR for workflow attachments: scanned PDFs and images via LM Studio VLM."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from app.services.regulation.pdf_ocr import extract_pdf_scan
from app.services.regulation.types import ExtractedBlock
from app.services.regulation.vlm_client import ATTACHMENT_OCR_PROMPT, recognize_pages

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def compose_ocr_text(blocks: list[ExtractedBlock]) -> str:
    parts: list[str] = []
    for block in blocks:
        table = block.table
        if table is not None:
            if table.headers:
                parts.append("\t".join(table.headers))
            for row in table.rows:
                parts.append("\t".join(row))
            continue
        text = (block.text or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def extract_visual_text(name: str, raw: bytes) -> str:
    """Recognize text from a scanned PDF or image. Raises VlmError/RuntimeError on failure."""
    suffix = Path(name or "").suffix.lower()
    safe_name = ascii(Path(name or "file").name)
    if suffix not in IMAGE_SUFFIXES and suffix != ".pdf":
        return ""
    if not raw:
        return ""
    with tempfile.TemporaryDirectory(prefix="attach-ocr-") as tmp:
        work = Path(tmp)
        source = work / (Path(name).name or ("scan.pdf" if suffix == ".pdf" else "page.png"))
        source.write_bytes(raw)
        if suffix == ".pdf":
            logger.info("attachment ocr pdf start name=%s bytes=%s", safe_name, len(raw))
            extracted = extract_pdf_scan(source, work_dir=work, prompt=ATTACHMENT_OCR_PROMPT)
            text = compose_ocr_text(extracted.blocks)
            logger.info(
                "attachment ocr pdf ok name=%s pages=%s chars=%s",
                safe_name,
                extracted.page_count,
                len(text),
            )
            return text
        png = work / "page-001.png"
        _to_png(source, png)
        logger.info("attachment ocr image start name=%s bytes=%s", safe_name, len(raw))
        blocks = recognize_pages([(1, png)], prompt=ATTACHMENT_OCR_PROMPT)
        text = compose_ocr_text(blocks)
        logger.info("attachment ocr image ok name=%s chars=%s", safe_name, len(text))
        return text


def _to_png(source: Path, dest: Path) -> None:
    if source.suffix.lower() == ".png":
        dest.write_bytes(source.read_bytes())
        return
    try:
        import fitz
    except ImportError:
        dest.write_bytes(source.read_bytes())
        return
    try:
        pix = fitz.Pixmap(str(source))
        if pix.n >= 5:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        pix.save(str(dest))
    except Exception:  # noqa: BLE001
        dest.write_bytes(source.read_bytes())

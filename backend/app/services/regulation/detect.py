from __future__ import annotations

from pathlib import Path

from app.services.regulation.pdf_text import pdf_text_profile

_PDF_SCAN_TEXT_THRESHOLD = 80


def is_scan_pdf(path: Path) -> tuple[bool, int]:
    page_count, text_chars = pdf_text_profile(path)
    return text_chars < _PDF_SCAN_TEXT_THRESHOLD, page_count

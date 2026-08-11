from __future__ import annotations

from pathlib import Path

from app.services.regulation.types import ExtractedBlock, ExtractedDocument


def extract_text_file(path: Path) -> ExtractedDocument:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="ignore").strip()
    blocks = [
        ExtractedBlock(page=1, text=part, confidence=1.0)
        for part in _split_text(text)
        if part.strip()
    ]
    return ExtractedDocument(page_count=1, blocks=blocks)


def _split_text(text: str) -> list[str]:
    if not text:
        return []
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    # Plain TXT often has headings and list items line-by-line without blank paragraphs.
    return [line.strip() for line in text.splitlines() if line.strip()]

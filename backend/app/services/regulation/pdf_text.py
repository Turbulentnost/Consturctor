from __future__ import annotations

from pathlib import Path

from app.services.regulation.types import ExtractedBlock, ExtractedDocument, ExtractedTable


def pdf_text_profile(path: Path) -> tuple[int, int]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Для PDF требуется зависимость pdfplumber") from exc

    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)
        chars = 0
        for page in pdf.pages[: min(3, page_count)]:
            chars += len((page.extract_text() or "").strip())
    return page_count, chars


def extract_pdf_text(path: Path) -> ExtractedDocument:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Для PDF требуется зависимость pdfplumber") from exc

    blocks: list[ExtractedBlock] = []
    with pdfplumber.open(str(path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text(x_tolerance=1, y_tolerance=3) or "").strip()
            if text:
                for piece in _split_text_blocks(text):
                    blocks.append(ExtractedBlock(page=idx, text=piece, confidence=1.0))

            for table in page.extract_tables() or []:
                rows = [[(cell or "").strip() for cell in row] for row in table if row]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                headers = rows[0]
                body = rows[1:] if len(rows) > 1 else []
                table_text = "\n".join(" | ".join(cell for cell in row if cell) for row in rows)
                blocks.append(
                    ExtractedBlock(
                        page=idx,
                        text=table_text,
                        kind="table",
                        table=ExtractedTable(headers=headers, rows=body),
                        confidence=1.0,
                    )
                )

        return ExtractedDocument(page_count=len(pdf.pages), blocks=blocks)


def _split_text_blocks(text: str) -> list[str]:
    parts = [part.strip() for part in text.split("\n\n") if part.strip()]
    return parts or [text.strip()]

from __future__ import annotations

from pathlib import Path

from app.services.regulation.types import ExtractedBlock, ExtractedDocument, ExtractedTable


def extract_docx(path: Path) -> ExtractedDocument:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("Для DOCX требуется зависимость python-docx") from exc

    doc = Document(str(path))
    blocks: list[ExtractedBlock] = []
    current_section = ""
    page = 1

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
        kind = "list" if "list" in style else "text"
        is_heading = "heading" in style or "заголовок" in style
        is_bold = any(run.bold for run in paragraph.runs)
        font_sizes = [
            run.font.size.pt
            for run in paragraph.runs
            if run.font is not None and run.font.size is not None
        ]
        font_size = max(font_sizes) if font_sizes else None
        numbering = _leading_numbering(text)
        if is_heading:
            current_section = text
        blocks.append(
            ExtractedBlock(
                page=page,
                section=current_section,
                text=text,
                kind=kind,
                block_type="heading" if is_heading else ("list_item" if kind == "list" else "paragraph"),
                font_size=font_size,
                is_bold=is_bold or is_heading,
                numbering=numbering,
                confidence=1.0,
            )
        )
        if _paragraph_has_page_break(paragraph):
            page += 1

    for table in doc.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows:
            continue
        headers = rows[0]
        body = rows[1:] if len(rows) > 1 else []
        text = "\n".join(" | ".join(cell for cell in row if cell) for row in rows)
        blocks.append(
            ExtractedBlock(
                page=max(1, page),
                section=current_section,
                text=text,
                kind="table",
                block_type="table",
                table=ExtractedTable(headers=headers, rows=body),
                confidence=1.0,
            )
        )

    return ExtractedDocument(page_count=max(1, page), blocks=blocks)


def _paragraph_has_page_break(paragraph) -> bool:
    for run in paragraph.runs:
        xml = run._element.xml  # noqa: SLF001 - python-docx exposes break details only via XML.
        if 'w:type="page"' in xml or "lastRenderedPageBreak" in xml:
            return True
    return False


def _leading_numbering(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    first = parts[0].rstrip(".)")
    if first and all(piece.isdigit() for piece in first.split(".")):
        return first
    return None

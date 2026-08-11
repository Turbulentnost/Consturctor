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
        if "heading" in style or "заголовок" in style:
            current_section = text
        blocks.append(
            ExtractedBlock(
                page=page,
                section=current_section,
                text=text,
                kind=kind,
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

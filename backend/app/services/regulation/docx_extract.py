from __future__ import annotations

import hashlib
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

    for paragraph_index, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name or "" if paragraph.style is not None else ""
        style = style_name.lower()
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
                location={
                    "documentPart": "word/document.xml",
                    "paragraphIndex": paragraph_index,
                    "paragraphXmlId": _paragraph_xml_id(paragraph),
                    "sectionPath": [current_section] if current_section else [],
                },
                style=style_name,
                content_hash=_content_hash(text),
            )
        )
        if _paragraph_has_page_break(paragraph):
            page += 1

    for table_index, table in enumerate(doc.tables):
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
                location={"documentPart": "word/document.xml", "tableIndex": table_index},
                style="table",
                content_hash=_content_hash(text),
            )
        )

    return ExtractedDocument(page_count=max(1, page), blocks=blocks)


def _paragraph_has_page_break(paragraph) -> bool:
    for run in paragraph.runs:
        xml = run._element.xml  # noqa: SLF001 - python-docx exposes break details only via XML.
        if 'w:type="page"' in xml or "lastRenderedPageBreak" in xml:
            return True
    return False


def _paragraph_xml_id(paragraph) -> str:
    element = paragraph._element  # noqa: SLF001 - python-docx exposes XML ids only here.
    for key in ("{http://schemas.microsoft.com/office/word/2010/wordml}paraId", "w14:paraId"):
        value = element.get(key)
        if value:
            return str(value)
    return ""


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _leading_numbering(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    first = parts[0].rstrip(".)")
    if first and all(piece.isdigit() for piece in first.split(".")):
        return first
    return None

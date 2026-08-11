from __future__ import annotations

import re

from app.schemas.regulation import RegulationFragment, RegulationParseResult, RegulationTable
from app.services.regulation.quality import recognition_quality
from app.services.regulation.types import ExtractedBlock, ExtractedDocument

_SPACE_RE = re.compile(r"[ \t]+")


def normalize_text(value: str) -> str:
    lines = [_SPACE_RE.sub(" ", line).strip() for line in (value or "").splitlines()]
    return "\n".join(line for line in lines if line)


def looks_like_heading(text: str) -> bool:
    t = normalize_text(text)
    if not t or len(t) > 140:
        return False
    if t.endswith(".") and len(t.split()) > 4:
        return False
    lower = t.lower()
    heading_words = (
        "раздел",
        "глава",
        "общие положения",
        "обязанности",
        "ответственность",
        "права",
        "порядок",
        "требования",
    )
    return (
        any(lower.startswith(word) for word in heading_words)
        or bool(re.match(r"^\d+(\.\d+)*[\).]?\s+\S+", t))
        or (t.isupper() and len(t) > 3)
    )


def build_result(
    *,
    regulation_id: str,
    filename: str,
    extracted: ExtractedDocument,
) -> RegulationParseResult:
    fragments: list[RegulationFragment] = []
    sections: list[str] = []
    current_section = ""
    page_counts: dict[int, int] = {}

    for block in extracted.blocks:
        block.text = normalize_text(block.text)
        if block.section.strip():
            current_section = normalize_text(block.section)
        elif block.kind == "text" and looks_like_heading(block.text):
            current_section = block.text

        if current_section and current_section not in sections:
            sections.append(current_section)

        page = max(1, int(block.page or 1))
        page_counts[page] = page_counts.get(page, 0) + 1
        fragment_id = f"{regulation_id}-page-{page:02d}-block-{page_counts[page]:02d}"
        table = None
        if block.table is not None:
            table = RegulationTable(headers=block.table.headers, rows=block.table.rows)
        fragments.append(
            RegulationFragment(
                fragmentId=fragment_id,
                page=page,
                section=current_section,
                kind=block.kind if block.kind in {"text", "table", "list"} else "text",
                text=block.text,
                table=table,
                ocrConfidence=max(0.0, min(1.0, block.confidence)),
            )
        )

    table_count = sum(1 for fragment in fragments if fragment.kind == "table")
    return RegulationParseResult(
        regulationId=regulation_id,
        fileName=filename,
        pageCount=max(extracted.page_count, max(page_counts.keys(), default=0)),
        tableCount=table_count,
        sectionCount=len(sections),
        recognitionQuality=recognition_quality(extracted.blocks),
        isScan=extracted.is_scan,
        sections=sections,
        fragments=fragments,
    )

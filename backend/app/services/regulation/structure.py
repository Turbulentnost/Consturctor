from __future__ import annotations

from app.schemas.regulation import RegulationFragment, RegulationParseResult, RegulationTable
from app.services.regulation.document_structure import (
    normalize_text,
    prepare_blocks,
    section_nodes_to_dicts,
)
from app.services.regulation.quality import recognition_quality
from app.services.regulation.types import ExtractedDocument


def build_result(
    *,
    regulation_id: str,
    filename: str,
    extracted: ExtractedDocument,
) -> RegulationParseResult:
    fragments: list[RegulationFragment] = []
    sections: list[str] = []
    page_counts: dict[int, int] = {}
    blocks, section_tree = prepare_blocks(extracted.blocks)
    by_id = {block.block_id: block for block in blocks}

    for block in blocks:
        block.text = normalize_text(block.text)
        section_path = block.section_path or ([block.section] if block.section else [])
        current_section = section_path[-1] if section_path else normalize_text(block.section)
        for section in section_path or ([current_section] if current_section else []):
            if section and section not in sections:
                sections.append(section)

        page = max(1, int(block.page or 1))
        page_counts[page] = page_counts.get(page, 0) + 1
        fragment_id = f"{regulation_id}-{block.block_id or f'page-{page:02d}-block-{page_counts[page]:02d}'}"
        table = None
        if block.table is not None:
            table = RegulationTable(headers=block.table.headers, rows=block.table.rows)
        previous_block = by_id.get(block.previous_fragment_id or "")
        next_block = by_id.get(block.next_fragment_id or "")
        fragments.append(
            RegulationFragment(
                fragmentId=fragment_id,
                page=page,
                section=current_section,
                sectionPath=section_path,
                kind=block.kind if block.kind in {"text", "table", "list"} else "text",
                blockType=_public_block_type(block.block_type),
                text=block.text,
                table=table,
                tableHeaders=block.table_headers,
                cells=block.cells,
                rowIndex=block.row_index,
                bbox=list(block.bbox) if block.bbox is not None else None,
                fontSize=block.font_size,
                isBold=block.is_bold,
                numbering=block.numbering,
                location=block.location,
                style=block.style,
                contentHash=block.content_hash,
                context={
                    "previousFragmentId": (
                        f"{regulation_id}-{previous_block.block_id}" if previous_block else None
                    ),
                    "previousText": previous_block.text if previous_block else "",
                    "nextFragmentId": f"{regulation_id}-{next_block.block_id}" if next_block else None,
                    "nextText": next_block.text if next_block else "",
                },
                ocrConfidence=max(0.0, min(1.0, block.confidence)),
            )
        )

    table_count = sum(1 for block in blocks if block.block_type == "table")
    return RegulationParseResult(
        regulationId=regulation_id,
        fileName=filename,
        pageCount=max(extracted.page_count, max(page_counts.keys(), default=0)),
        tableCount=table_count,
        sectionCount=len(sections),
        recognitionQuality=recognition_quality(extracted.blocks),
        isScan=extracted.is_scan,
        sections=sections,
        sectionTree=section_nodes_to_dicts(section_tree),
        fragments=fragments,
    )


def _public_block_type(value: str) -> str:
    if value in {"paragraph", "heading", "list_item", "table", "table_row", "note"}:
        return value
    return "paragraph"

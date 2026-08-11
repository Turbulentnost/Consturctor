from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.regulation.types import ExtractedBlock

_SPACE_RE = re.compile(r"[ \t]+")
_NUMBERING_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)(?:[\).])?\s+(?P<title>\S.*)$")
_TERMINAL_DOT_RE = re.compile(r"[.!?…]$")


@dataclass(slots=True)
class SectionNode:
    title: str
    level: int
    page: int
    section_id: str
    children: list["SectionNode"] = field(default_factory=list)


def normalize_text(value: str) -> str:
    lines = [_SPACE_RE.sub(" ", line).strip() for line in (value or "").splitlines()]
    return "\n".join(line for line in lines if line)


def prepare_blocks(blocks: list[ExtractedBlock]) -> tuple[list[ExtractedBlock], list[SectionNode]]:
    """Assign block ids, detect section paths, split table rows, and add neighbor context."""
    structured: list[ExtractedBlock] = []
    roots: list[SectionNode] = []
    stack: list[SectionNode] = []
    counters: dict[int, int] = {}

    for raw in blocks:
        raw.text = normalize_text(raw.text)
        page = max(1, int(raw.page or 1))
        counters[page] = counters.get(page, 0) + 1
        raw.block_id = raw.block_id or f"B-{page:04d}-{counters[page]:04d}"

        heading = detect_heading(raw)
        if heading is not None:
            title, level = heading
            node = SectionNode(
                title=title,
                level=level,
                page=page,
                section_id=f"S-{len(_flatten_sections(roots)) + 1:04d}",
            )
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
            raw.block_type = "heading"
            raw.section = title
            raw.section_path = [item.title for item in stack]
            structured.append(raw)
            continue

        raw.section_path = [item.title for item in stack]
        if raw.section and not raw.section_path:
            raw.section_path = [normalize_text(raw.section)]
        if raw.section_path:
            raw.section = raw.section_path[-1]

        if raw.kind == "table" and raw.table is not None:
            raw.block_type = "table"
            structured.append(raw)
            structured.extend(_table_rows(raw))
        else:
            raw.block_type = "list_item" if raw.kind == "list" else raw.block_type
            structured.append(raw)

    for prev, current, nxt in _with_neighbors(structured):
        current.previous_fragment_id = prev.block_id if prev is not None else None
        current.next_fragment_id = nxt.block_id if nxt is not None else None

    return structured, roots


def detect_heading(block: ExtractedBlock) -> tuple[str, int] | None:
    text = normalize_text(block.section or block.text)
    if not text or len(text) > 160:
        return None
    if text.startswith(("- ", "• ", "– ")):
        return None
    numbering = block.numbering or _extract_numbering(text)
    lower = text.lower()
    heading_words = (
        "раздел",
        "глава",
        "общие положения",
        "обязанности",
        "ответственность",
        "права",
        "порядок",
        "требования",
        "термины",
        "функции",
        "организация работы",
    )
    signals = 0
    if numbering:
        signals += 2
    if block.font_size and block.font_size >= 13:
        signals += 1
    if block.is_bold:
        signals += 1
    if len(text.split()) <= 9:
        signals += 1
    if not _TERMINAL_DOT_RE.search(text):
        signals += 1
    if text.isupper() and len(text) > 3:
        signals += 1
    if any(lower.startswith(word) for word in heading_words):
        signals += 2
    if block.section and block.section.strip() == block.text.strip():
        signals += 1
    if signals < 2:
        return None
    return text, _heading_level(text, numbering)


def section_nodes_to_dicts(nodes: list[SectionNode]) -> list[dict]:
    return [
        {
            "title": node.title,
            "level": node.level,
            "page": node.page,
            "sectionId": node.section_id,
            "children": section_nodes_to_dicts(node.children),
        }
        for node in nodes
    ]


def _table_rows(block: ExtractedBlock) -> list[ExtractedBlock]:
    assert block.table is not None
    headers = [normalize_text(header) for header in block.table.headers]
    width = max(len(headers), *(len(row) for row in block.table.rows), 1)
    if len(headers) < width:
        headers = headers + [f"Колонка {i + 1}" for i in range(len(headers), width)]
    inherited = [""] * width
    out: list[ExtractedBlock] = []
    for idx, row in enumerate(block.table.rows, start=1):
        values = [normalize_text(cell) for cell in row] + [""] * (width - len(row))
        for col, value in enumerate(values):
            if value:
                inherited[col] = value
            else:
                values[col] = inherited[col]
        cells = {headers[col] or f"Колонка {col + 1}": values[col] for col in range(width)}
        text = "; ".join(f"{key}: {value}" for key, value in cells.items() if value)
        out.append(
            ExtractedBlock(
                page=block.page,
                block_id=f"{block.block_id}-R-{idx:03d}",
                block_type="table_row",
                text=text,
                section=block.section,
                kind="table",
                confidence=block.confidence,
                table_headers=headers,
                cells=cells,
                row_index=idx,
                section_path=list(block.section_path),
            )
        )
    return out


def _extract_numbering(text: str) -> str | None:
    match = _NUMBERING_RE.match(text)
    return match.group("num") if match else None


def _heading_level(text: str, numbering: str | None) -> int:
    value = numbering or _extract_numbering(text)
    if value:
        return min(9, value.count(".") + 1)
    lower = text.lower()
    if lower.startswith(("раздел", "глава")):
        return 1
    return 2


def _flatten_sections(nodes: list[SectionNode]) -> list[SectionNode]:
    out: list[SectionNode] = []
    for node in nodes:
        out.append(node)
        out.extend(_flatten_sections(node.children))
    return out


def _with_neighbors(items: list[ExtractedBlock]):
    for idx, item in enumerate(items):
        prev = items[idx - 1] if idx > 0 else None
        nxt = items[idx + 1] if idx + 1 < len(items) else None
        yield prev, item, nxt

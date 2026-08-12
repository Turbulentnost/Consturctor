from __future__ import annotations

from dataclasses import dataclass, field


BBox = tuple[float, float, float, float]


@dataclass(slots=True)
class ExtractedTable:
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedBlock:
    page: int
    block_id: str = ""
    block_type: str = "paragraph"
    text: str = ""
    section: str = ""
    kind: str = "text"
    table: ExtractedTable | None = None
    confidence: float = 1.0
    font_size: float | None = None
    is_bold: bool = False
    numbering: str | None = None
    bbox: BBox | None = None
    table_headers: list[str] = field(default_factory=list)
    cells: dict[str, str] = field(default_factory=dict)
    row_index: int | None = None
    section_path: list[str] = field(default_factory=list)
    previous_fragment_id: str | None = None
    next_fragment_id: str | None = None
    location: dict[str, object] = field(default_factory=dict)
    style: str = ""
    content_hash: str = ""


@dataclass(slots=True)
class ExtractedDocument:
    page_count: int
    blocks: list[ExtractedBlock] = field(default_factory=list)
    is_scan: bool = False

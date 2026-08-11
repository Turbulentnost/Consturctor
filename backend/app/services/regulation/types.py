from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedTable:
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedBlock:
    page: int
    text: str = ""
    section: str = ""
    kind: str = "text"
    table: ExtractedTable | None = None
    confidence: float = 1.0


@dataclass(slots=True)
class ExtractedDocument:
    page_count: int
    blocks: list[ExtractedBlock] = field(default_factory=list)
    is_scan: bool = False

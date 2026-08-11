from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


FragmentKind = Literal["text", "table", "list"]


class RegulationTable(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class RegulationFragment(BaseModel):
    fragmentId: str
    page: int
    section: str
    kind: FragmentKind = "text"
    text: str = ""
    table: RegulationTable | None = None
    ocrConfidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RegulationParseResult(BaseModel):
    regulationId: str
    fileName: str
    pageCount: int = 0
    tableCount: int = 0
    sectionCount: int = 0
    recognitionQuality: float = Field(default=0.0, ge=0.0, le=1.0)
    isScan: bool = False
    sections: list[str] = Field(default_factory=list)
    fragments: list[RegulationFragment] = Field(default_factory=list)
    createdAt: datetime | None = None

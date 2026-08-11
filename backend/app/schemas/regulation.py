from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


FragmentKind = Literal["text", "table", "list"]
BlockType = Literal["paragraph", "heading", "list_item", "table", "table_row", "note"]
RoleRelation = Literal[
    "executor",
    "recipient",
    "approver",
    "initiator",
    "consulted",
    "informed",
    "owner",
    "mentioned",
    "none",
]
MatchType = Literal[
    "direct_role_mention",
    "inherited_from_section",
    "assigned_action",
    "process_role_alias",
    "department_relation",
    "interaction",
    "related_artifact_or_system",
    "semantic_candidate",
]
MatchStatus = Literal["accepted", "probable", "pending", "rejected"]


class RegulationTable(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class DocumentSection(BaseModel):
    title: str
    level: int = 1
    page: int = 1
    sectionId: str = ""
    children: list["DocumentSection"] = Field(default_factory=list)


class RegulationFragmentContext(BaseModel):
    previousFragmentId: str | None = None
    previousText: str = ""
    nextFragmentId: str | None = None
    nextText: str = ""


class RegulationFragment(BaseModel):
    fragmentId: str
    page: int
    section: str
    sectionPath: list[str] = Field(default_factory=list)
    kind: FragmentKind = "text"
    blockType: BlockType = "paragraph"
    text: str = ""
    table: RegulationTable | None = None
    tableHeaders: list[str] = Field(default_factory=list)
    cells: dict[str, str] = Field(default_factory=dict)
    rowIndex: int | None = None
    bbox: list[float] | None = None
    fontSize: float | None = None
    isBold: bool = False
    numbering: str | None = None
    context: RegulationFragmentContext | None = None
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
    sectionTree: list[DocumentSection] = Field(default_factory=list)
    fragments: list[RegulationFragment] = Field(default_factory=list)
    createdAt: datetime | None = None


class RoleAlias(BaseModel):
    value: str
    status: Literal["verified", "candidate", "unverified"] = "candidate"
    reason: str = ""
    sourceFragments: list[str] = Field(default_factory=list)


class RoleProfile(BaseModel):
    canonicalTitle: str
    department: str = ""
    aliases: list[RoleAlias] = Field(default_factory=list)
    processRoles: list[RoleAlias] = Field(default_factory=list)
    systems: list[RoleAlias] = Field(default_factory=list)
    documents: list[RoleAlias] = Field(default_factory=list)


class MatchSignal(BaseModel):
    matchType: MatchType
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fragmentId: str
    quote: str = ""
    explanation: str = ""


class MatchEvidence(BaseModel):
    fragmentId: str
    quote: str


class FragmentRoleMatch(BaseModel):
    matchId: str
    fragmentId: str
    isRelevant: bool = False
    relation: RoleRelation = "none"
    matchTypes: list[MatchType] = Field(default_factory=list)
    signals: list[MatchSignal] = Field(default_factory=list)
    evidence: list[MatchEvidence] = Field(default_factory=list)
    explanation: str = ""
    modelConfidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    contradictions: list[str] = Field(default_factory=list)
    requiresUserConfirmation: bool = False
    status: MatchStatus = "pending"
    fragment: RegulationFragment


class RoleMatchRequest(BaseModel):
    position: str = ""
    department: str = ""


class RoleMatchDecisionRequest(BaseModel):
    status: Literal["accepted", "rejected"]


class RoleMatchResult(BaseModel):
    runId: str
    regulationId: str
    profile: RoleProfile
    matches: list[FragmentRoleMatch] = Field(default_factory=list)
    createdAt: datetime | None = None

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
    "graph_relation",
    "definition_link",
    "actor_inheritance",
]
MatchStatus = Literal["accepted", "probable", "pending", "rejected"]
RelationType = Literal[
    "parent_section",
    "previous_block",
    "next_block",
    "same_list",
    "same_table",
    "table_header",
    "explicit_reference",
    "actor_inheritance",
    "condition_for",
    "exception_for",
    "definition_of",
    "continuation_of",
    "input_for",
    "same_process",
    "contradicts",
]


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


class DocumentRole(BaseModel):
    canonicalTitle: str
    aliases: list[str] = Field(default_factory=list)
    sourceBlockIds: list[str] = Field(default_factory=list)
    status: Literal["verified", "candidate", "unverified"] = "candidate"


class DocumentProcess(BaseModel):
    name: str
    sections: list[str] = Field(default_factory=list)
    sourceBlockIds: list[str] = Field(default_factory=list)
    status: Literal["verified", "candidate", "unverified"] = "candidate"


class DocumentDefinition(BaseModel):
    term: str
    meaning: str
    scope: str = ""
    sourceBlockId: str = ""
    status: Literal["verified", "candidate", "unverified"] = "candidate"


class DocumentReference(BaseModel):
    fromBlockId: str
    toBlockId: str = ""
    referenceText: str = ""
    relation: RelationType = "explicit_reference"
    status: Literal["verified", "candidate", "unverified"] = "candidate"


class DocumentMap(BaseModel):
    roles: list[DocumentRole] = Field(default_factory=list)
    processes: list[DocumentProcess] = Field(default_factory=list)
    definitions: list[DocumentDefinition] = Field(default_factory=list)
    references: list[DocumentReference] = Field(default_factory=list)
    systems: list[RoleAlias] = Field(default_factory=list)
    documents: list[RoleAlias] = Field(default_factory=list)
    source: Literal["claudehub", "heuristic", "mixed"] = "heuristic"
    warnings: list[str] = Field(default_factory=list)


class BlockRelation(BaseModel):
    fromBlockId: str
    toBlockId: str
    relation: RelationType
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["verified", "candidate", "unverified"] = "candidate"


class ContextLinkedBlock(BaseModel):
    blockId: str
    relation: RelationType | str = ""
    text: str = ""
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ContextPackage(BaseModel):
    targetBlockId: str
    targetText: str = ""
    sectionTitle: str = ""
    parentSections: list[str] = Field(default_factory=list)
    previousBlockId: str | None = None
    previousText: str = ""
    nextBlockId: str | None = None
    nextText: str = ""
    linkedBlocks: list[ContextLinkedBlock] = Field(default_factory=list)
    knownEntities: dict[str, str] = Field(default_factory=dict)
    processSummary: str = ""


class FunctionActor(BaseModel):
    text: str = ""
    canonicalPosition: str = ""
    sourceBlockId: str = ""


class FunctionDependency(BaseModel):
    type: str = ""
    blockId: str = ""
    description: str = ""


class MatchSignal(BaseModel):
    matchType: MatchType
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fragmentId: str
    quote: str = ""
    explanation: str = ""


class MatchEvidence(BaseModel):
    fragmentId: str
    quote: str


class RoleFunction(BaseModel):
    functionId: str = ""
    targetBlockId: str = ""
    isFunction: bool = False
    actor: FunctionActor = Field(default_factory=FunctionActor)
    action: str = ""
    object: str = ""
    recipient: str = ""
    conditions: list[str] = Field(default_factory=list)
    dependencies: list[FunctionDependency] = Field(default_factory=list)
    evidence: list[MatchEvidence] = Field(default_factory=list)
    proofChain: list[ContextLinkedBlock] = Field(default_factory=list)
    explanation: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicateGroup: str = ""
    requiresUserConfirmation: bool = False


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
    function: RoleFunction | None = None


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
    documentMap: DocumentMap | None = None
    relations: list[BlockRelation] = Field(default_factory=list)
    functions: list[RoleFunction] = Field(default_factory=list)
    audit: dict = Field(default_factory=dict)
    createdAt: datetime | None = None

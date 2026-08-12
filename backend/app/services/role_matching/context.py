from __future__ import annotations

from app.schemas.regulation import (
    BlockRelation,
    ContextLinkedBlock,
    ContextPackage,
    DocumentMap,
    RegulationFragment,
    RegulationParseResult,
    RoleProfile,
)
from app.services.role_matching.candidates import Candidate

_ENTITY_ALIASES = {
    "он": "canonical",
    "она": "canonical",
    "они": "canonical",
    "данный сотрудник": "canonical",
    "указанный специалист": "canonical",
    "ответственное лицо": "canonical",
    "ответственный": "canonical",
}


def build_context_package(
    candidate: Candidate,
    *,
    result: RegulationParseResult,
    profile: RoleProfile,
    relations: list[BlockRelation],
    document_map: DocumentMap,
) -> ContextPackage:
    fragment = candidate.fragment
    by_id = {item.fragmentId: item for item in result.fragments}
    linked = _linked_blocks(fragment.fragmentId, relations, by_id)
    return ContextPackage(
        targetBlockId=fragment.fragmentId,
        targetText=fragment.text,
        sectionTitle=fragment.section,
        parentSections=fragment.sectionPath,
        previousBlockId=fragment.context.previousFragmentId if fragment.context else None,
        previousText=fragment.context.previousText if fragment.context else "",
        nextBlockId=fragment.context.nextFragmentId if fragment.context else None,
        nextText=fragment.context.nextText if fragment.context else "",
        linkedBlocks=linked,
        knownEntities=_known_entities(fragment, linked, profile, document_map),
        processSummary=_process_summary(fragment, document_map),
    )


def relations_for_block(block_id: str, relations: list[BlockRelation]) -> list[BlockRelation]:
    direct = [item for item in relations if item.fromBlockId == block_id]
    second_hop_ids = {item.toBlockId for item in direct}
    second = [
        item
        for item in relations
        if item.fromBlockId in second_hop_ids and item.relation in {"definition_of", "parent_section"}
    ]
    return sorted(
        [*direct, *second],
        key=lambda item: (
            item.relation not in {"actor_inheritance", "definition_of", "explicit_reference"},
            -item.confidence,
        ),
    )[:10]


def _linked_blocks(
    block_id: str,
    relations: list[BlockRelation],
    by_id: dict[str, RegulationFragment],
) -> list[ContextLinkedBlock]:
    out: list[ContextLinkedBlock] = []
    for relation in relations_for_block(block_id, relations):
        target = by_id.get(relation.toBlockId)
        if target is None:
            continue
        out.append(
            ContextLinkedBlock(
                blockId=target.fragmentId,
                relation=relation.relation,
                text=_fragment_text(target),
                evidence=relation.evidence,
                confidence=relation.confidence,
            )
        )
    return out


def _known_entities(
    fragment: RegulationFragment,
    linked: list[ContextLinkedBlock],
    profile: RoleProfile,
    document_map: DocumentMap,
) -> dict[str, str]:
    text = " ".join([fragment.text, *(item.text for item in linked)]).lower()
    entities: dict[str, str] = {}
    for alias, target in _ENTITY_ALIASES.items():
        if alias in text and target == "canonical":
            entities[alias] = profile.canonicalTitle
    for definition in document_map.definitions:
        if definition.term and definition.term.lower() in text:
            entities[definition.term] = definition.meaning
    return entities


def _process_summary(fragment: RegulationFragment, document_map: DocumentMap) -> str:
    section_names = set(fragment.sectionPath or ([fragment.section] if fragment.section else []))
    for process in document_map.processes:
        if section_names.intersection(process.sections):
            return process.name
    return fragment.section


def _fragment_text(fragment: RegulationFragment) -> str:
    if fragment.cells:
        return "; ".join(f"{key}: {value}" for key, value in fragment.cells.items() if value)
    return fragment.text

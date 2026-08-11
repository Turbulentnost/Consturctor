from __future__ import annotations

import re

from app.schemas.regulation import BlockRelation, DocumentMap, RegulationFragment, RegulationParseResult
from app.services.role_matching.normalize import contains_phrase

_POINT_REF_RE = re.compile(
    r"(?:пункт(?:а|е|ом)?|п\.|раздел(?:а|е|ом)?)\s*(?P<num>\d+(?:\.\d+)*)",
    re.I,
)
_ACTOR_WORDS = (
    "он",
    "она",
    "они",
    "данный сотрудник",
    "указанный специалист",
    "ответственное лицо",
    "ответственный",
    "последний",
    "соответствующее подразделение",
)
_ACTION_MARKERS = (
    "проверяет",
    "формирует",
    "направляет",
    "передает",
    "передаёт",
    "регистрирует",
    "согласовывает",
    "утверждает",
    "вносит",
    "получает",
)


def build_block_graph(result: RegulationParseResult, document_map: DocumentMap) -> list[BlockRelation]:
    fragments = result.fragments
    relations: list[BlockRelation] = []
    by_id = {fragment.fragmentId: fragment for fragment in fragments}
    heading_by_section = _heading_by_section(fragments)

    for idx, fragment in enumerate(fragments):
        if fragment.context and fragment.context.previousFragmentId:
            relations.append(
                _relation(
                    fragment.fragmentId,
                    fragment.context.previousFragmentId,
                    "previous_block",
                    "Предыдущий смысловой блок",
                    1.0,
                    "verified",
                )
            )
        if fragment.context and fragment.context.nextFragmentId:
            relations.append(
                _relation(
                    fragment.fragmentId,
                    fragment.context.nextFragmentId,
                    "next_block",
                    "Следующий смысловой блок",
                    1.0,
                    "verified",
                )
            )
        section_key = _section_key(fragment)
        if section_key in heading_by_section and heading_by_section[section_key] != fragment.fragmentId:
            relations.append(
                _relation(
                    fragment.fragmentId,
                    heading_by_section[section_key],
                    "parent_section",
                    "Фрагмент находится внутри раздела",
                    0.96,
                    "verified",
                )
            )
        if fragment.blockType == "table_row" and "-R-" in fragment.fragmentId:
            table_id = fragment.fragmentId.rsplit("-R-", 1)[0]
            if table_id in by_id:
                relations.append(
                    _relation(
                        fragment.fragmentId,
                        table_id,
                        "same_table",
                        "Строка принадлежит таблице",
                        1.0,
                        "verified",
                    )
                )
                if fragment.tableHeaders:
                    relations.append(
                        _relation(
                            fragment.fragmentId,
                            table_id,
                            "table_header",
                            "; ".join(fragment.tableHeaders[:8]),
                            1.0,
                            "verified",
                        )
                    )
        if fragment.blockType == "list_item":
            prev = fragments[idx - 1] if idx > 0 else None
            if prev and prev.blockType == "list_item" and _section_key(prev) == section_key:
                relations.append(
                    _relation(
                        fragment.fragmentId,
                        prev.fragmentId,
                        "same_list",
                        "Элементы одного списка",
                        0.94,
                        "verified",
                    )
                )
        relations.extend(_explicit_references(fragment, fragments))
        relations.extend(_definition_relations(fragment, document_map))
        relations.extend(_condition_relations(fragment, fragments, idx))
        relations.extend(_actor_inheritance(fragment, fragments, idx, document_map))

    relations.extend(_document_map_relations(document_map, by_id))
    return _dedupe_relations(relations)


def _heading_by_section(fragments: list[RegulationFragment]) -> dict[str, str]:
    out: dict[str, str] = {}
    for fragment in fragments:
        if fragment.blockType != "heading":
            continue
        key = _section_key(fragment)
        if key:
            out[key] = fragment.fragmentId
    return out


def _explicit_references(
    fragment: RegulationFragment,
    fragments: list[RegulationFragment],
) -> list[BlockRelation]:
    out: list[BlockRelation] = []
    text = fragment.text or ""
    for match in _POINT_REF_RE.finditer(text):
        number = match.group("num")
        target = _find_numbered_fragment(number, fragments)
        if target is None:
            continue
        out.append(
            _relation(
                fragment.fragmentId,
                target.fragmentId,
                "explicit_reference",
                match.group(0),
                0.95,
                "verified",
            )
        )
    return out


def _definition_relations(
    fragment: RegulationFragment,
    document_map: DocumentMap,
) -> list[BlockRelation]:
    out: list[BlockRelation] = []
    text = fragment.text or ""
    for definition in document_map.definitions:
        if not definition.sourceBlockId or definition.sourceBlockId == fragment.fragmentId:
            continue
        if contains_phrase(text, definition.term):
            out.append(
                _relation(
                    fragment.fragmentId,
                    definition.sourceBlockId,
                    "definition_of",
                    f"{definition.term} = {definition.meaning}",
                    0.82,
                    definition.status,
                )
            )
    return out


def _condition_relations(
    fragment: RegulationFragment,
    fragments: list[RegulationFragment],
    idx: int,
) -> list[BlockRelation]:
    text = (fragment.text or "").strip().lower()
    if not text.startswith(("при ", "если ", "за исключением", "кроме случаев")):
        return []
    target = _nearest_action_before(fragments, idx)
    if target is None:
        return []
    relation = "exception_for" if text.startswith(("за исключением", "кроме случаев")) else "condition_for"
    return [
        _relation(
            fragment.fragmentId,
            target.fragmentId,
            relation,
            fragment.text[:240],
            0.78,
            "candidate",
        )
    ]


def _actor_inheritance(
    fragment: RegulationFragment,
    fragments: list[RegulationFragment],
    idx: int,
    document_map: DocumentMap,
) -> list[BlockRelation]:
    text = (fragment.text or "").lower()
    if not any(word in text for word in _ACTOR_WORDS):
        return []
    target = _nearest_actor_definition(fragments, idx, document_map)
    if target is None:
        return []
    confidence = 0.86 if _section_key(target) == _section_key(fragment) else 0.64
    return [
        _relation(
            fragment.fragmentId,
            target.fragmentId,
            "actor_inheritance",
            "Исполнитель наследуется из связанного предыдущего блока",
            confidence,
            "candidate" if confidence < 0.9 else "verified",
        )
    ]


def _document_map_relations(
    document_map: DocumentMap,
    by_id: dict[str, RegulationFragment],
) -> list[BlockRelation]:
    out: list[BlockRelation] = []
    for ref in document_map.references:
        if ref.fromBlockId not in by_id:
            continue
        if ref.toBlockId and ref.toBlockId not in by_id:
            continue
        if not ref.toBlockId:
            continue
        out.append(
            _relation(
                ref.fromBlockId,
                ref.toBlockId,
                ref.relation,
                ref.referenceText,
                0.72,
                ref.status,
            )
        )
    return out


def _nearest_action_before(
    fragments: list[RegulationFragment],
    idx: int,
) -> RegulationFragment | None:
    current = fragments[idx]
    for prev in reversed(fragments[max(0, idx - 6) : idx]):
        if _section_key(prev) != _section_key(current):
            continue
        if any(marker in (prev.text or "").lower() for marker in _ACTION_MARKERS):
            return prev
    return None


def _nearest_actor_definition(
    fragments: list[RegulationFragment],
    idx: int,
    document_map: DocumentMap,
) -> RegulationFragment | None:
    current = fragments[idx]
    definition_ids = {
        definition.sourceBlockId
        for definition in document_map.definitions
        if definition.sourceBlockId
    }
    role_ids = {
        block_id
        for role in document_map.roles
        for block_id in role.sourceBlockIds
        if block_id
    }
    for prev in reversed(fragments[max(0, idx - 8) : idx]):
        if _section_key(prev) != _section_key(current):
            continue
        lower = (prev.text or "").lower()
        if (
            prev.fragmentId in definition_ids
            or prev.fragmentId in role_ids
            or "ответственн" in lower
            or "исполнител" in lower
        ):
            return prev
    return None


def _find_numbered_fragment(
    number: str,
    fragments: list[RegulationFragment],
) -> RegulationFragment | None:
    for fragment in fragments:
        numbering = fragment.numbering or ""
        text = fragment.text or ""
        if numbering == number or text.startswith(f"{number}.") or text.startswith(f"{number} "):
            return fragment
    return None


def _section_key(fragment: RegulationFragment) -> str:
    return " / ".join(fragment.sectionPath or ([fragment.section] if fragment.section else []))


def _relation(
    from_id: str,
    to_id: str,
    relation: str,
    evidence: str,
    confidence: float,
    status: str,
) -> BlockRelation:
    return BlockRelation(
        fromBlockId=from_id,
        toBlockId=to_id,
        relation=relation,
        evidence=evidence[:500],
        confidence=max(0.0, min(1.0, confidence)),
        status=status if status in {"verified", "candidate", "unverified"} else "candidate",
    )


def _dedupe_relations(items: list[BlockRelation]) -> list[BlockRelation]:
    by_key: dict[tuple[str, str, str], BlockRelation] = {}
    for item in items:
        if not item.fromBlockId or not item.toBlockId or item.fromBlockId == item.toBlockId:
            continue
        key = (item.fromBlockId, item.toBlockId, item.relation)
        current = by_key.get(key)
        if current is None or item.confidence > current.confidence:
            by_key[key] = item
    return list(by_key.values())

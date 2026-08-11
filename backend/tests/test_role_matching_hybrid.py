from __future__ import annotations

from app.schemas.regulation import (
    DocumentMap,
    DocumentRole,
    RegulationFragment,
    RegulationFragmentContext,
    RegulationParseResult,
)
from app.services.regulation.document_structure import prepare_blocks
from app.services.regulation.pdf_text import _split_text_blocks
from app.services.regulation.types import ExtractedBlock
from app.services.role_matching.candidates import collect_candidates
from app.services.role_matching.claudehub_client import _coerce_document_map_data
from app.services.role_matching.context import build_context_package
from app.services.role_matching.dedupe import dedupe_matches
from app.services.role_matching.graph import build_block_graph
from app.services.role_matching import llm_classifier
from app.services.role_matching.llm_classifier import classify_candidate
from app.services.role_matching.normalize import contains_phrase
from app.services.role_matching.profile import build_role_profile


def test_actor_inheritance_context_and_fallback_function(monkeypatch) -> None:
    monkeypatch.setattr(llm_classifier, "_post", lambda _payload: (_ for _ in ()).throw(RuntimeError("offline")))
    result = _sample_result()
    document_map = DocumentMap(
        roles=[
            DocumentRole(
                canonicalTitle="Менеджер по продажам",
                aliases=["менеджер"],
                sourceBlockIds=["B-001"],
                status="candidate",
            )
        ]
    )
    relations = build_block_graph(result, document_map)

    assert any(
        item.fromBlockId == "B-002"
        and item.toBlockId == "B-001"
        and item.relation == "actor_inheritance"
        for item in relations
    )

    profile = build_role_profile(
        position="Менеджер по продажам",
        department="Отдел продаж",
        result=result,
    )
    candidates = collect_candidates(result, profile, relations)
    inherited = next(item for item in candidates if item.fragment.fragmentId == "B-002")
    assert any(signal.matchType == "actor_inheritance" for signal in inherited.signals)

    context = build_context_package(
        inherited,
        result=result,
        profile=profile,
        relations=relations,
        document_map=document_map,
    )
    assert context.linkedBlocks
    assert context.knownEntities.get("он") == "Менеджер по продажам"

    classified = classify_candidate(inherited, profile, context)
    function = classified["function"]
    assert function.isFunction is True
    assert function.actor.canonicalPosition == "Менеджер по продажам"
    assert function.action == "проверяет"
    assert function.evidence


def test_dedupe_merges_same_function_evidence(monkeypatch) -> None:
    monkeypatch.setattr(llm_classifier, "_post", lambda _payload: (_ for _ in ()).throw(RuntimeError("offline")))
    result = _sample_result()
    document_map = DocumentMap(
        roles=[
            DocumentRole(
                canonicalTitle="Менеджер по продажам",
                aliases=["менеджер"],
                sourceBlockIds=["B-001"],
            )
        ]
    )
    relations = build_block_graph(result, document_map)
    profile = build_role_profile(
        position="Менеджер по продажам",
        department="Отдел продаж",
        result=result,
    )
    candidates = collect_candidates(result, profile, relations)
    matches = []
    from app.schemas.regulation import FragmentRoleMatch  # imported here to keep setup compact
    from app.services.role_matching.scoring import final_confidence, status_for_confidence

    functional_candidates = [
        candidate
        for candidate in candidates
        if candidate.fragment.fragmentId in {"B-002", "B-003"}
    ]
    for idx, candidate in enumerate(functional_candidates, start=1):
        context = build_context_package(
            candidate,
            result=result,
            profile=profile,
            relations=relations,
            document_map=document_map,
        )
        classified = classify_candidate(candidate, profile, context)
        confidence = final_confidence(candidate, classified)
        function = classified["function"]
        function.functionId = f"F-{idx:04d}"
        function.action = "проверяет"
        function.object = "заявку"
        function.recipient = ""
        function.confidence = confidence
        matches.append(
            FragmentRoleMatch(
                matchId=f"M-{idx:04d}",
                fragmentId=candidate.fragment.fragmentId,
                isRelevant=True,
                relation=classified["relation"],
                matchTypes=classified["matchTypes"],
                signals=candidate.signals,
                evidence=classified["evidence"],
                explanation=classified["explanation"],
                modelConfidence=0,
                confidence=confidence,
                requiresUserConfirmation=True,
                status=status_for_confidence(confidence, True),
                fragment=candidate.fragment,
                function=function,
            )
        )

    deduped = dedupe_matches(matches)

    assert len(deduped) == 1
    assert len(deduped[0].function.evidence) >= 1
    assert deduped[0].function.duplicateGroup


def test_process_stage_with_contacts_is_not_role_function_candidate() -> None:
    assert not contains_phrase("контактных лиц", "акт")

    result = RegulationParseResult(
        regulationId="reg-stage",
        fileName="stage.txt",
        pageCount=1,
        tableCount=0,
        sectionCount=1,
        recognitionQuality=1,
        sections=["Этапы внедрения"],
        fragments=[
            RegulationFragment(
                fragmentId="S-001",
                page=6,
                section="Этапы внедрения",
                sectionPath=["Этапы внедрения"],
                text=(
                    "6.2.2 Этап 1. Формирование и согласование ТЗ. "
                    "Выход: карточка инициативы с указанием цели, владельца, "
                    "ограничений и контактных лиц."
                ),
            )
        ],
    )
    profile = build_role_profile(
        position="Промпт-инженер 2 категории",
        department="Сектор по внедрению искусственного интеллекта",
        result=result,
    )

    assert collect_candidates(result, profile, []) == []


def test_position_category_uses_base_title_alias() -> None:
    result = RegulationParseResult(
        regulationId="reg-prompt",
        fileName="prompt.txt",
        pageCount=1,
        tableCount=0,
        sectionCount=1,
        recognitionQuality=1,
        sections=["Функции"],
        fragments=[
            RegulationFragment(
                fragmentId="P-001",
                page=8,
                section="Функции",
                sectionPath=["Функции"],
                text="Промпт-инженер разрабатывает, тестирует и документирует ИИ-решения.",
            )
        ],
    )
    profile = build_role_profile(
        position="Промпт-инженер 2 категории",
        department="Сектор по внедрению искусственного интеллекта",
        result=result,
    )

    candidates = collect_candidates(result, profile, [])

    assert candidates
    assert any(signal.matchType == "direct_role_mention" for signal in candidates[0].signals)


def test_pdf_split_keeps_prompt_engineer_actions_under_role_section() -> None:
    text = "\n".join(
        [
            "5 Ответственность",
            "5.3 Промпт-инженер",
            "- разрабатывает и оптимизирует промпт, утилиту или иную логику решения;",
            "- ведёт версионирование, журнал изменений и описание логики работы решения;",
            "- проводит обучение пользователей и готовит комплект документов для приёмки.",
        ]
    )

    pieces = _split_text_blocks(text)
    blocks = [
        ExtractedBlock(
            page=4,
            text=piece,
            kind="list" if piece.startswith("- ") else "text",
            block_type="list_item" if piece.startswith("- ") else "paragraph",
            numbering=piece.split(maxsplit=1)[0] if piece[:1].isdigit() else None,
        )
        for piece in pieces
    ]
    structured, _sections = prepare_blocks(blocks)

    actions = [block for block in structured if block.text.startswith("- ")]

    assert [block.text for block in structured[:2]] == [
        "5 Ответственность",
        "5.3 Промпт-инженер",
    ]
    assert len(actions) == 3
    assert all(block.block_type == "list_item" for block in actions)
    assert all(block.section == "5.3 Промпт-инженер" for block in actions)


def test_claudehub_map_coerces_named_systems_and_documents() -> None:
    data = {
        "roles": [],
        "processes": [],
        "definitions": [],
        "references": [
            {"fromBlockId": "B-1", "toBlockId": None, "relation": "role relation", "status": "found"}
        ],
        "systems": [{"name": "Реестр решений", "status": "found"}],
        "documents": [{"title": "ТЗ"}],
    }

    coerced = _coerce_document_map_data(data)

    assert coerced["references"][0]["relation"] == "actor_inheritance"
    assert coerced["references"][0]["status"] == "candidate"
    assert coerced["references"][0]["toBlockId"] == ""
    assert coerced["systems"][0]["value"] == "Реестр решений"
    assert coerced["systems"][0]["status"] == "candidate"
    assert coerced["documents"][0]["value"] == "ТЗ"


def _sample_result() -> RegulationParseResult:
    f1 = RegulationFragment(
        fragmentId="B-001",
        page=1,
        section="Порядок обработки заявки",
        sectionPath=["Порядок обработки заявки"],
        text="Ответственным за заявку является менеджер по продажам.",
        context=RegulationFragmentContext(nextFragmentId="B-002", nextText="Он проверяет реквизиты заявки."),
    )
    f2 = RegulationFragment(
        fragmentId="B-002",
        page=1,
        section="Порядок обработки заявки",
        sectionPath=["Порядок обработки заявки"],
        text="Он проверяет реквизиты заявки.",
        context=RegulationFragmentContext(
            previousFragmentId="B-001",
            previousText=f1.text,
            nextFragmentId="B-003",
            nextText="После этого он направляет заявку руководителю.",
        ),
    )
    f3 = RegulationFragment(
        fragmentId="B-003",
        page=1,
        section="Порядок обработки заявки",
        sectionPath=["Порядок обработки заявки"],
        text="После этого он направляет заявку руководителю.",
        context=RegulationFragmentContext(previousFragmentId="B-002", previousText=f2.text),
    )
    return RegulationParseResult(
        regulationId="reg-test",
        fileName="test.txt",
        pageCount=1,
        tableCount=0,
        sectionCount=1,
        recognitionQuality=1,
        sections=["Порядок обработки заявки"],
        fragments=[f1, f2, f3],
    )

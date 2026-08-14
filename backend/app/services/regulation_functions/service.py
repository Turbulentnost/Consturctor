from __future__ import annotations

import ast
import json
import re
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError
from app.config import settings
from app.models.regulation import RoleMatchRun
from app.schemas.regulation import (
    BlockRelation,
    ContextLinkedBlock,
    DocumentMap,
    DocumentProcess,
    FragmentRoleMatch,
    FunctionActor,
    FunctionDependency,
    MatchEvidence,
    RegulationFragment,
    RegulationParseResult,
    RoleFunction,
    RoleMatchResult,
    RoleProfile,
)
from app.services.regulation.full_text import compose_regulation_text
from app.services.regulation.storage import get_document
from app.services.role_matching.normalize import contains_phrase
from app.services.role_matching.profile import all_candidate_terms, build_role_profile, verified_aliases


class RegulationFunctionExtractionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_cursor_function_extraction(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    position: str,
    department: str,
) -> RoleMatchResult:
    position = position.strip()
    department = department.strip()
    if not position:
        raise RegulationFunctionExtractionError("Укажите должность")
    if not department:
        raise RegulationFunctionExtractionError("Укажите подразделение")
    doc = get_document(db, regulation_id=regulation_id, user_id=user_id)
    if doc is None:
        raise RegulationFunctionExtractionError("Регламент не найден", status_code=404)

    result = RegulationParseResult.model_validate(doc.result_json)
    prompt = _build_prompt(result, position=position, department=department)
    try:
        created = cursor_client.create_agent(
            prompt=prompt,
            model_id=settings.cursor_regulation_model,
            name="Выделение функциональных блоков",
            mode="agent",
            model_params=[{"id": "fast", "value": "true"}],
        )
        agent = created.get("agent") if isinstance(created.get("agent"), dict) else {}
        run = created.get("run") if isinstance(created.get("run"), dict) else {}
        agent_id = str(agent.get("id") or "")
        run_id = str(run.get("id") or "")
        if not agent_id or not run_id:
            raise CursorAgentError("Cursor API не вернул agent/run id")
        final = cursor_client.wait_for_run(agent_id, run_id)
    except CursorAgentError as exc:
        raise RegulationFunctionExtractionError(exc.message, status_code=exc.status_code) from exc

    parsed = _parse_agent_response(str(final.get("result") or ""))
    role_result = _map_agent_result(
        parsed,
        regulation=result,
        regulation_id=regulation_id,
        position=position,
        department=department,
        cursor_agent_id=agent_id,
        cursor_run_id=run_id,
    )
    run_row = RoleMatchRun(
        id=role_result.runId,
        regulation_id=regulation_id,
        user_id=user_id,
        position=position,
        department=department,
        result_json=role_result.model_dump(mode="json"),
    )
    run_row = db.merge(run_row)
    db.commit()
    db.refresh(run_row)
    return RoleMatchResult.model_validate(run_row.result_json)


def _build_prompt(result: RegulationParseResult, *, position: str, department: str) -> str:
    document_text = compose_regulation_text(result)
    return (
        "Ты Cursor Agent, который анализирует распознанный регламент и выделяет функциональные блоки "
        "только для должности текущего пользователя.\n"
        "КРИТИЧНО: верни функции ТОЛЬКО там, где исполнитель — должность пользователя "
        f"(или её явный алиас в тексте). Должность пользователя: «{position}». "
        f"Подразделение: «{department}».\n"
        "Любые другие должности и роли из документа НЕ включай как отдельные функции — "
        "даже если они соседние в том же разделе, таблице или процессе. "
        "Их можно кратко упомянуть только в sharedContext как внешний контекст взаимодействия.\n"
        "Если должность пользователя — администратор, ИТ, заказчик или любая другая, "
        f"выделяй именно её функции: ориентир всегда «{position}», а не фиксированный список ролей.\n"
        "Анализируй документ целиком, чтобы не потерять связанные обязанности именно этой должности "
        "через разные разделы, таблицы, входы, выходы и контрольные операции.\n\n"
        "Верни строго JSON без markdown и пояснений вне JSON. Контракт:\n"
        "{\n"
        '  "functions": [\n'
        "    {\n"
        '      "id": "f1",\n'
        '      "title": "краткое человекочитаемое название процесса на русском (не склеивай action+object+получателя)",\n'
        '      "description": "что происходит и почему это бизнес-функция именно этой должности",\n'
        '      "action": "глагол действия",\n'
        '      "object": "объект обработки/результат",\n'
        f'      "actor": "{position}",\n'
        '      "recipient": "получатель результата",\n'
        '      "conditions": ["условия запуска/ветвления"],\n'
        '      "inputs": ["входные данные/документы"],\n'
        '      "outputs": ["выходы/результаты"],\n'
        '      "systems": ["системы"],\n'
        '      "sourceRefs": [{"fragmentId": "FR-...", "sectionPath": ["..."], "quote": "..."}],\n'
        '      "relatedFunctionIds": ["f2"],\n'
        '      "sharedContext": "как связаны блоки этой должности",\n'
        '      "optimizableWhy": "что можно оптимизировать/автоматизировать",\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "questions": [\n'
        "    {\n"
        '      "id": "q1",\n'
        '      "functionId": "f1",\n'
        '      "relatedFunctionIds": ["f2"],\n'
        '      "field": "trigger|inputs|system|result|recipient|conditions|deadline|errors|approval|permissions|control|kpi",\n'
        '      "text": "точный вопрос пользователю",\n'
        '      "context": "полный нужный контекст из связанных фрагментов",\n'
        '      "sourceRefs": [{"fragmentId": "FR-...", "quote": "..."}]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Требования:\n"
        f"- В functions.actor указывай только «{position}» или её явный алиас из документа.\n"
        f"- Если фрагмент/заголовок явно про другую должность (не «{position}» и не её алиас), пропускай его.\n"
        "- title — отдельное короткое название (например «Регистрация карточки инициативы»), "
        "без стрелок «→» и без списка ролей/получателей.\n"
        "- action — глагол/сказуемое; object — объект в нужном падеже; recipient — отдельно, не в title.\n"
        "- Выделяй только реальные процессы/функции этой должности, которые можно оптимизировать или автоматизировать.\n"
        "- Для связанных блоков ЭТОЙ ЖЕ должности заполняй relatedFunctionIds и sharedContext.\n"
        "- Вопросы формируй только по включённым функциям, не теряя контекст.\n"
        "- sourceRefs.fragmentId должен соответствовать fragmentId из документа.\n"
        "- Если подходящих функций нет, верни пустые массивы functions и questions.\n\n"
        f"Распознанный документ:\n{document_text}"
    )


def _map_agent_result(
    data: dict[str, Any],
    *,
    regulation: RegulationParseResult,
    regulation_id: str,
    position: str,
    department: str,
    cursor_agent_id: str,
    cursor_run_id: str,
) -> RoleMatchResult:
    fragments = {item.fragmentId: item for item in regulation.fragments}
    fallback_fragment = next((item for item in regulation.fragments if (item.text or "").strip()), None)
    profile = build_role_profile(position=position, department=department, result=regulation)
    position_terms = _unique_terms([*verified_aliases(profile), *all_candidate_terms(profile)])
    raw_all = [item for item in (data.get("functions") or []) if isinstance(item, dict)]
    raw_functions = [
        item
        for item in raw_all
        if _function_belongs_to_position(
            item,
            position_terms=position_terms,
            fragments=fragments,
        )
    ]
    matches: list[FragmentRoleMatch] = []
    role_functions: list[RoleFunction] = []
    processes: list[DocumentProcess] = []
    relations: list[BlockRelation] = []
    id_map: dict[str, str] = {}

    for idx, item in enumerate(raw_functions, start=1):
        agent_id = str(item.get("id") or f"f{idx}")
        function_id = f"F-{len(role_functions) + 1:04d}"
        id_map[agent_id] = function_id
        fragment = _source_fragment(item, fragments, fallback_fragment)
        if fragment is None:
            continue
        title = _clean(item.get("title")) or _clean(item.get("description")) or function_id
        description = _clean(item.get("description"))
        action = _clean(item.get("action")) or _infer_action(title)
        obj = _clean(item.get("object"))
        if not obj or obj.casefold() == title.casefold():
            obj = _object_from_title(title, action) or obj or title
        conditions = _list_text(item.get("conditions"))
        inputs = _list_text(item.get("inputs"))
        outputs = _list_text(item.get("outputs"))
        systems = _list_text(item.get("systems"))
        shared_context = _clean(item.get("sharedContext"))
        optimizable = _clean(item.get("optimizableWhy"))
        evidence = _evidence(item, fragment)
        proof_chain = _proof_chain(item, fragments)
        dependencies = [
            FunctionDependency(type="input", blockId=fragment.fragmentId, description=value)
            for value in inputs
        ] + [
            FunctionDependency(type="output", blockId=fragment.fragmentId, description=value)
            for value in outputs
        ] + [
            FunctionDependency(type="system", blockId=fragment.fragmentId, description=value)
            for value in systems
        ]
        if shared_context:
            dependencies.append(
                FunctionDependency(type="related_context", blockId=fragment.fragmentId, description=shared_context)
            )
        role_function = RoleFunction(
            functionId=function_id,
            targetBlockId=fragment.fragmentId,
            isFunction=True,
            title=title,
            actor=FunctionActor(
                text=position,
                canonicalPosition=position,
                sourceBlockId=fragment.fragmentId,
            ),
            action=action,
            object=obj,
            recipient=_clean(item.get("recipient")),
            conditions=conditions,
            dependencies=dependencies,
            evidence=evidence,
            proofChain=proof_chain,
            explanation=" ".join(part for part in [description, optimizable] if part).strip(),
            confidence=_confidence(item.get("confidence")),
            duplicateGroup=f"cursor:{function_id}",
            requiresUserConfirmation=True,
        )
        match = FragmentRoleMatch(
            matchId=f"M-{len(matches) + 1:04d}",
            fragmentId=fragment.fragmentId,
            isRelevant=True,
            relation="executor",
            matchTypes=["semantic_candidate"],
            evidence=evidence,
            explanation=role_function.explanation,
            modelConfidence=role_function.confidence,
            confidence=role_function.confidence,
            requiresUserConfirmation=True,
            status="pending",
            fragment=fragment,
            function=role_function,
        )
        matches.append(match)
        role_functions.append(role_function)
        processes.append(
            DocumentProcess(
                name=title,
                sections=fragment.sectionPath or ([fragment.section] if fragment.section else []),
                sourceBlockIds=[fragment.fragmentId],
                status="verified",
            )
        )

    for idx, item in enumerate(raw_functions, start=1):
        from_id = id_map.get(str(item.get("id") or f"f{idx}"))
        if not from_id:
            continue
        from_block = _function_block(role_functions, from_id)
        for related in _list_text(item.get("relatedFunctionIds")):
            to_id = id_map.get(related)
            to_block = _function_block(role_functions, to_id) if to_id else ""
            if from_block and to_block:
                relations.append(
                    BlockRelation(
                        fromBlockId=from_block,
                        toBlockId=to_block,
                        relation="same_process",
                        evidence=_clean(item.get("sharedContext")),
                        confidence=0.8,
                        status="verified",
                    )
                )

    questions = [
        question
        for question in _normalize_questions(data.get("questions"), id_map)
        if question.get("functionId") in set(id_map.values())
        or any(related in set(id_map.values()) for related in (question.get("relatedFunctionIds") or []))
    ]
    audit = {
        "source": "cursor_agent",
        "cursorAgentId": cursor_agent_id,
        "cursorRunId": cursor_run_id,
        "cursorQuestions": questions,
        "diagnostics": {
            "fragmentsTotal": len(regulation.fragments),
            "functionsFromCursor": len(raw_all),
            "functionsKeptForPosition": len(role_functions),
            "functionsFilteredOut": max(0, len(raw_all) - len(raw_functions)),
            "questionsFromCursor": len(questions),
        },
    }
    return RoleMatchResult(
        runId=f"role-run-{uuid4().hex[:12]}",
        regulationId=regulation_id,
        profile=RoleProfile(canonicalTitle=position, department=department),
        matches=matches,
        documentMap=DocumentMap(processes=processes, source="mixed"),
        relations=relations,
        functions=role_functions,
        audit=audit,
    )


_ROLE_TITLE_WORDS = (
    "руководитель",
    "начальник",
    "директор",
    "заместитель",
    "менеджер",
    "администратор",
    "administrator",
    "заказчик",
    "разработчик",
    "аналитик",
    "инженер",
    "специалист",
    "эксперт",
    "координатор",
    "архитектор",
    "devops",
    "helpdesk",
    "service desk",
    "it ops",
    "ops/adm",
)


def _unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _function_belongs_to_position(
    item: dict[str, Any],
    *,
    position_terms: list[str],
    fragments: dict[str, RegulationFragment],
) -> bool:
    actor = _clean(item.get("actor"))
    title = _clean(item.get("title"))
    description = _clean(item.get("description"))
    # Не подмешиваем чужой fallback-фрагмент в фильтр.
    fragment = _source_fragment(item, fragments, None)
    quote_parts = _source_quotes(item)
    section_parts: list[str] = []
    if fragment is not None:
        section_parts.extend(fragment.sectionPath or [])
        if fragment.section:
            section_parts.append(fragment.section)
        if fragment.text:
            quote_parts.append(fragment.text[:800])
    evidence_blob = " ".join(part for part in [*quote_parts, *section_parts] if part)
    title_desc = " ".join(part for part in [title, description] if part)

    evidence_mentions_user = _mentions_position(evidence_blob, position_terms)
    actor_mentions_user = _mentions_position(actor, position_terms) if actor else False
    title_mentions_user = _mentions_position(title_desc, position_terms)
    foreign_evidence = _names_other_role(evidence_blob, position_terms)
    foreign_actor = _names_other_role(actor, position_terms) if actor else False

    # Доказательства явно про другую роль — отбрасываем, даже если agent подставил должность в actor.
    if foreign_evidence and not evidence_mentions_user:
        return False
    if foreign_actor and not actor_mentions_user:
        return False
    if evidence_mentions_user or title_mentions_user:
        return True
    if actor_mentions_user and not foreign_evidence and not foreign_actor:
        return True
    return False


def _source_quotes(item: dict[str, Any]) -> list[str]:
    refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        quote = _clean(ref.get("quote"))
        if quote:
            out.append(quote)
        path = ref.get("sectionPath")
        if isinstance(path, list):
            out.extend(_clean(part) for part in path if _clean(part))
    return out


def _mentions_position(text: str, position_terms: list[str]) -> bool:
    if not text:
        return False
    return any(contains_phrase(text, term) for term in position_terms if len(term) >= 3)


def _role_word_belongs_to_user(role_word: str, position_terms: list[str]) -> bool:
    needle = role_word.casefold()
    return any(needle in term.casefold() for term in position_terms)


def _names_other_role(text: str, position_terms: list[str]) -> bool:
    """True, если текст называет роль, несовместимую с должностью пользователя."""
    if not text:
        return False
    if _mentions_position(text, position_terms):
        return False
    lowered = text.casefold()
    for role_word in _ROLE_TITLE_WORDS:
        if role_word in lowered and not _role_word_belongs_to_user(role_word, position_terms):
            return True
    return False


def _parse_agent_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
            return parsed if isinstance(parsed, dict) else {}
        except (SyntaxError, ValueError):
            pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except (SyntaxError, ValueError):
                pass
    raise RegulationFunctionExtractionError("Cursor Agent не вернул корректный JSON")


def _source_fragment(
    item: dict[str, Any],
    fragments: dict[str, RegulationFragment],
    fallback: RegulationFragment | None,
) -> RegulationFragment | None:
    refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        fragment_id = str(ref.get("fragmentId") or "").strip()
        if fragment_id in fragments:
            return fragments[fragment_id]
    return fallback


def _evidence(item: dict[str, Any], fragment: RegulationFragment) -> list[MatchEvidence]:
    refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    out: list[MatchEvidence] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        quote = _clean(ref.get("quote"))
        fragment_id = _clean(ref.get("fragmentId")) or fragment.fragmentId
        if quote:
            out.append(MatchEvidence(fragmentId=fragment_id, quote=quote[:800]))
    if not out:
        out.append(MatchEvidence(fragmentId=fragment.fragmentId, quote=(fragment.text or "")[:800]))
    return out


def _proof_chain(item: dict[str, Any], fragments: dict[str, RegulationFragment]) -> list[ContextLinkedBlock]:
    refs = item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else []
    out: list[ContextLinkedBlock] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        fragment_id = _clean(ref.get("fragmentId"))
        fragment = fragments.get(fragment_id)
        if fragment is None:
            continue
        out.append(
            ContextLinkedBlock(
                blockId=fragment.fragmentId,
                relation="same_process",
                text=(fragment.text or _clean(ref.get("quote")))[:1000],
                evidence=_clean(ref.get("quote"))[:500],
                confidence=0.8,
            )
        )
    return out


def _normalize_questions(raw: Any, id_map: dict[str, str]) -> list[dict[str, Any]]:
    questions = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    allowed_fields = {
        "trigger",
        "inputs",
        "system",
        "result",
        "recipient",
        "conditions",
        "deadline",
        "errors",
        "approval",
        "permissions",
        "control",
        "kpi",
    }
    for idx, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            continue
        function_id = id_map.get(_clean(item.get("functionId")), _clean(item.get("functionId")))
        field = _clean(item.get("field")) or "inputs"
        if field not in allowed_fields:
            field = "inputs"
        out.append(
            {
                "questionId": _clean(item.get("id")) or f"CUR-Q-{idx:03d}",
                "functionId": function_id,
                "relatedFunctionIds": [
                    id_map.get(value, value)
                    for value in _list_text(item.get("relatedFunctionIds"))
                ],
                "targetField": field,
                "question": _clean(item.get("text")),
                "context": _clean(item.get("context")),
                "sourceRefs": item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else [],
            }
        )
    return [item for item in out if item["functionId"] and item["question"]]


def _function_block(functions: list[RoleFunction], function_id: str | None) -> str:
    if not function_id:
        return ""
    for function in functions:
        if function.functionId == function_id:
            return function.targetBlockId
    return ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.78


def _infer_action(title: str) -> str:
    first = title.split(" ", 1)[0].strip()
    return first or "выполняет"


def _object_from_title(title: str, action: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        return ""
    # Убрать хвост «→ получатели», если агент всё же вшил его в title.
    cleaned = re.split(r"\s*→\s*", cleaned, maxsplit=1)[0].strip()
    if action and cleaned.casefold().startswith(action.casefold()):
        rest = cleaned[len(action) :].strip(" —-:;")
        return rest
    return cleaned

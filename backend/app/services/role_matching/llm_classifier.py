from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas.regulation import (
    ContextLinkedBlock,
    ContextPackage,
    FunctionActor,
    FunctionDependency,
    MatchEvidence,
    RoleFunction,
    RoleProfile,
)
from app.services.role_matching.candidates import Candidate

_MATCH_TYPES = {
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
}

_ACTION_PATTERN = re.compile(
    r"\b("
    r"разрабатывает|оптимизирует|тестирует|документирует|обучает|внедряет|"
    r"подготавливает|готовит|проверяет|формирует|направляет|переда[её]т|"
    r"регистрирует|согласовывает|утверждает|вносит|получает|контролирует|"
    r"вед[её]т|выполняет|устраняет|оформляет|проводит|фиксирует|"
    r"составляет|настраивает|обеспечивает|организует|анализирует"
    r")\b",
    flags=re.I,
)


def classify_candidate(
    candidate: Candidate,
    profile: RoleProfile,
    context: ContextPackage | None = None,
) -> dict[str, Any]:
    if settings.llm_provider.strip().casefold() in {"stub", "none", "disabled"}:
        return _fallback_response(candidate, profile, context, reason="LLM provider is disabled")
    payload = _payload(candidate, profile, context)
    try:
        raw = _post(payload)
        data = _load_json(raw)
        return _validated(data, candidate, profile, context)
    except Exception as exc:  # noqa: BLE001 - keep role matching usable if LLM is offline.
        return _fallback_response(candidate, profile, context, reason=f"LM Studio недоступен: {exc}")


def _fallback_response(
    candidate: Candidate,
    profile: RoleProfile,
    context: ContextPackage | None,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "isRelevant": True,
        "relation": _default_relation(candidate),
        "matchTypes": [signal.matchType for signal in candidate.signals],
        "evidence": _rule_evidence(candidate),
        "explanation": f"Классификация выполнена по правилам; {reason}",
        "modelConfidence": 0.0,
        "contradictions": [],
        "requiresUserConfirmation": True,
        "function": _fallback_function(candidate, profile, context),
    }


def _payload(
    candidate: Candidate,
    profile: RoleProfile,
    context: ContextPackage | None,
) -> dict[str, Any]:
    fragment = candidate.fragment
    fragment_context = fragment.context
    prompt = {
        "instruction": (
            "Определи, содержит ли targetBlock функцию должности пользователя. "
            "Разбери доказательную цепочку: исполнитель, действие, объект, адресат, "
            "условия, зависимости и блоки-доказательства. Если исполнитель наследуется "
            "из другого блока, обязательно верни его blockId и тип связи. "
            "Учитывай должность и подразделение пользователя. "
            "Не считай фрагмент относящимся к должности только из-за упоминания "
            "подразделения, CRM, информационной системы или общего документа без связи с ролью. "
            "Используй только предоставленный текст. Верни только JSON без markdown."
        ),
        "roleProfile": profile.model_dump(mode="json"),
        "fragment": {
            "fragmentId": fragment.fragmentId,
            "sectionPath": fragment.sectionPath,
            "blockType": fragment.blockType,
            "text": fragment.text,
            "cells": fragment.cells,
            "previousText": fragment_context.previousText if fragment_context else "",
            "nextText": fragment_context.nextText if fragment_context else "",
        },
        "contextPackage": context.model_dump(mode="json") if context else {},
        "signals": [signal.model_dump(mode="json") for signal in candidate.signals],
        "responseSchema": {
            "fragmentId": fragment.fragmentId,
            "isRelevant": True,
            "relation": "executor|recipient|approver|initiator|consulted|informed|owner|mentioned|none",
            "matchTypes": ["direct_role_mention"],
            "evidence": [{"fragmentId": fragment.fragmentId, "quote": "точная цитата"}],
            "explanation": "краткое объяснение",
            "modelConfidence": 0.0,
            "contradictions": [],
            "requiresUserConfirmation": False,
            "function": {
                "isFunction": True,
                "actor": {
                    "text": "он",
                    "canonicalPosition": profile.canonicalTitle,
                    "sourceBlockId": "blockId with actor evidence",
                },
                "action": "направить",
                "object": "заявку",
                "recipient": "руководитель",
                "conditions": [],
                "dependencies": [
                    {
                        "type": "after",
                        "blockId": "previous blockId",
                        "description": "После проверки заявки",
                    }
                ],
                "evidence": [
                    {"fragmentId": fragment.fragmentId, "quote": "точная цитата действия"}
                ],
                "proofChain": [
                    {
                        "blockId": "source blockId",
                        "relation": "actor_inheritance",
                        "text": "текст доказательства",
                        "evidence": "почему связан",
                        "confidence": 0.9,
                    }
                ],
                "explanation": "кратко",
                "confidence": 0.0,
            },
        },
    }
    return {
        "model": settings.lm_studio_model,
        "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        "temperature": 0,
    }


def _post(payload: dict[str, Any]) -> str:
    url = f"{settings.lm_studio_base_url.rstrip('/')}/v1/chat/completions"
    with httpx.Client(timeout=90.0) as client:
        response = client.post(url, json=payload)
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"])


def _load_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _validated(
    data: dict[str, Any],
    candidate: Candidate,
    profile: RoleProfile,
    context: ContextPackage | None,
) -> dict[str, Any]:
    fragment = candidate.fragment
    evidence = []
    source_texts = _source_texts(fragment.text, fragment.cells, context)
    for item in data.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        if quote and _quote_in_sources(quote, source_texts):
            evidence.append({"fragmentId": str(item.get("fragmentId") or fragment.fragmentId), "quote": quote})
    if not evidence:
        evidence = [item.model_dump(mode="json") for item in _rule_evidence(candidate)]
    relation = str(data.get("relation") or _default_relation(candidate))
    if relation not in {
        "executor",
        "recipient",
        "approver",
        "initiator",
        "consulted",
        "informed",
        "owner",
        "mentioned",
        "none",
    }:
        relation = "mentioned"
    return {
        "isRelevant": bool(data.get("isRelevant", True)),
        "relation": relation,
        "matchTypes": _match_types(data.get("matchTypes") or [s.matchType for s in candidate.signals]),
        "evidence": evidence,
        "explanation": str(data.get("explanation") or "Классификация LM Studio"),
        "modelConfidence": _clamp(float(data.get("modelConfidence") or 0.0)),
        "contradictions": [str(x) for x in data.get("contradictions") or []],
        "requiresUserConfirmation": bool(data.get("requiresUserConfirmation", False)),
        "function": _validated_function(data.get("function"), candidate, profile, context, evidence),
    }


def _validated_function(
    raw: Any,
    candidate: Candidate,
    profile: RoleProfile,
    context: ContextPackage | None,
    fallback_evidence: list[dict],
) -> RoleFunction:
    if not isinstance(raw, dict):
        return _fallback_function(candidate, profile, context, fallback_evidence=fallback_evidence)
    fragment = candidate.fragment
    source_texts = _source_texts(fragment.text, fragment.cells, context)
    evidence = []
    for item in raw.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        block_id = str(item.get("fragmentId") or item.get("blockId") or fragment.fragmentId)
        if quote and _quote_in_sources(quote, source_texts):
            evidence.append(MatchEvidence(fragmentId=block_id, quote=quote[:500]))
    if not evidence:
        evidence = [MatchEvidence.model_validate(item) for item in fallback_evidence]

    dependencies = []
    for item in raw.get("dependencies") or []:
        if isinstance(item, dict):
            dependencies.append(
                FunctionDependency(
                    type=str(item.get("type") or ""),
                    blockId=str(item.get("blockId") or ""),
                    description=str(item.get("description") or "")[:500],
                )
            )

    proof_chain = []
    for item in raw.get("proofChain") or []:
        if isinstance(item, dict):
            proof_chain.append(
                ContextLinkedBlock(
                    blockId=str(item.get("blockId") or ""),
                    relation=str(item.get("relation") or ""),
                    text=str(item.get("text") or "")[:1200],
                    evidence=str(item.get("evidence") or "")[:500],
                    confidence=_clamp(float(item.get("confidence") or 0.0)),
                )
            )
    if not proof_chain and context:
        proof_chain = context.linkedBlocks[:4]

    actor_raw = raw.get("actor") if isinstance(raw.get("actor"), dict) else {}
    actor = FunctionActor(
        text=str(actor_raw.get("text") or profile.canonicalTitle),
        canonicalPosition=str(actor_raw.get("canonicalPosition") or profile.canonicalTitle),
        sourceBlockId=str(actor_raw.get("sourceBlockId") or _actor_source_block(context) or fragment.fragmentId),
    )
    return RoleFunction(
        targetBlockId=fragment.fragmentId,
        isFunction=bool(raw.get("isFunction", True)),
        actor=actor,
        action=str(raw.get("action") or _guess_action(fragment.text)),
        object=str(raw.get("object") or _guess_object(fragment.text)),
        recipient=str(raw.get("recipient") or ""),
        conditions=[str(x)[:500] for x in raw.get("conditions") or []],
        dependencies=dependencies,
        evidence=evidence[:6],
        proofChain=proof_chain[:8],
        explanation=str(raw.get("explanation") or "")[:1000],
        confidence=_clamp(float(raw.get("confidence") or raw.get("modelConfidence") or 0.0)),
        requiresUserConfirmation=bool(raw.get("requiresUserConfirmation", False)),
    )


def _rule_evidence(candidate: Candidate) -> list[MatchEvidence]:
    out: list[MatchEvidence] = []
    for signal in candidate.signals:
        quote = signal.quote or candidate.fragment.text[:220]
        if quote:
            out.append(MatchEvidence(fragmentId=candidate.fragment.fragmentId, quote=quote))
    return out[:3]


def _match_types(values: list) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value)
        if text in _MATCH_TYPES and text not in out:
            out.append(text)
    return out


def _fallback_function(
    candidate: Candidate,
    profile: RoleProfile,
    context: ContextPackage | None,
    *,
    fallback_evidence: list[dict] | None = None,
) -> RoleFunction:
    fragment = candidate.fragment
    evidence = (
        [MatchEvidence.model_validate(item) for item in fallback_evidence]
        if fallback_evidence
        else _rule_evidence(candidate)
    )
    proof_chain = context.linkedBlocks[:4] if context else []
    source_block = _actor_source_block(context) or fragment.fragmentId
    return RoleFunction(
        targetBlockId=fragment.fragmentId,
        isFunction=_has_action(fragment.text, fragment.cells),
        actor=FunctionActor(
            text=profile.canonicalTitle,
            canonicalPosition=profile.canonicalTitle,
            sourceBlockId=source_block,
        ),
        action=_guess_action(fragment.text),
        object=_guess_object(fragment.text),
        recipient=_guess_recipient(fragment.text),
        conditions=_conditions(context),
        dependencies=_dependencies(context),
        evidence=evidence[:6],
        proofChain=proof_chain,
        explanation="Функция извлечена по правилам и связям графа",
        confidence=0.0,
        requiresUserConfirmation=True,
    )


def _default_relation(candidate: Candidate) -> str:
    types = {signal.matchType for signal in candidate.signals}
    if "assigned_action" in types or "inherited_from_section" in types:
        return "executor"
    if "interaction" in types:
        return "mentioned"
    if "direct_role_mention" in types:
        return "mentioned"
    return "none"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _source_texts(text: str, cells: dict[str, str], context: ContextPackage | None) -> dict[str, str]:
    sources = {"target": " ".join([text, *cells.values()])}
    if context:
        sources[context.targetBlockId] = context.targetText
        if context.previousBlockId:
            sources[context.previousBlockId] = context.previousText
        if context.nextBlockId:
            sources[context.nextBlockId] = context.nextText
        for block in context.linkedBlocks:
            sources[block.blockId] = block.text
    return sources


def _quote_in_sources(quote: str, sources: dict[str, str]) -> bool:
    needle = quote.strip()
    return any(needle and needle in value for value in sources.values())


def _actor_source_block(context: ContextPackage | None) -> str:
    if not context:
        return ""
    for block in context.linkedBlocks:
        if block.relation in {"actor_inheritance", "definition_of", "parent_section"}:
            return block.blockId
    return ""


def _has_action(text: str, cells: dict[str, str]) -> bool:
    combined = " ".join([text, *cells.values()]).lower()
    return bool(_ACTION_PATTERN.search(combined))


def _guess_action(text: str) -> str:
    match = _ACTION_PATTERN.search(text or "")
    return match.group(1).lower() if match else ""


def _guess_object(text: str) -> str:
    action = _guess_action(text)
    if not action:
        return ""
    match = re.search(re.escape(action) + r"\s+(?P<object>[^.;,\n]{2,80})", text or "", flags=re.I)
    return match.group("object").strip() if match else ""


def _guess_recipient(text: str) -> str:
    match = re.search(r"(?:руководителю|клиенту|заказчику|исполнителю|сотруднику)[^.;,\n]*", text or "", re.I)
    return match.group(0).strip() if match else ""


def _conditions(context: ContextPackage | None) -> list[str]:
    if not context:
        return []
    return [
        block.text
        for block in context.linkedBlocks
        if block.relation in {"condition_for", "exception_for"}
    ][:4]


def _dependencies(context: ContextPackage | None) -> list[FunctionDependency]:
    if not context:
        return []
    out: list[FunctionDependency] = []
    if context.previousBlockId and context.previousText:
        out.append(
            FunctionDependency(
                type="after",
                blockId=context.previousBlockId,
                description=context.previousText[:500],
            )
        )
    for block in context.linkedBlocks:
        if block.relation in {"input_for", "previous_block", "same_process"}:
            out.append(
                FunctionDependency(
                    type=str(block.relation),
                    blockId=block.blockId,
                    description=block.text[:500],
                )
            )
    return out[:5]

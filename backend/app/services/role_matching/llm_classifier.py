from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas.regulation import MatchEvidence, RoleProfile
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
}


def classify_candidate(candidate: Candidate, profile: RoleProfile) -> dict[str, Any]:
    payload = _payload(candidate, profile)
    try:
        raw = _post(payload)
        data = _load_json(raw)
        return _validated(data, candidate)
    except Exception as exc:  # noqa: BLE001 - keep role matching usable if LLM is offline.
        return {
            "isRelevant": True,
            "relation": _default_relation(candidate),
            "matchTypes": [signal.matchType for signal in candidate.signals],
            "evidence": _rule_evidence(candidate),
            "explanation": f"Классификация выполнена по правилам; LM Studio недоступен: {exc}",
            "modelConfidence": 0.0,
            "contradictions": [],
            "requiresUserConfirmation": True,
        }


def _payload(candidate: Candidate, profile: RoleProfile) -> dict[str, Any]:
    fragment = candidate.fragment
    context = fragment.context
    prompt = {
        "instruction": (
            "Определи, связан ли фрагмент с должностью и подразделением пользователя "
            "(roleProfile.canonicalTitle и roleProfile.department). "
            "Учитывай оба признака: должность и подразделение. "
            "Не считай фрагмент относящимся к должности только из-за упоминания "
            "подразделения, CRM или общего документа без связи с ролью. "
            "Используй только предоставленный текст. Верни только JSON без markdown."
        ),
        "roleProfile": profile.model_dump(mode="json"),
        "fragment": {
            "fragmentId": fragment.fragmentId,
            "sectionPath": fragment.sectionPath,
            "blockType": fragment.blockType,
            "text": fragment.text,
            "cells": fragment.cells,
            "previousText": context.previousText if context else "",
            "nextText": context.nextText if context else "",
        },
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


def _validated(data: dict[str, Any], candidate: Candidate) -> dict[str, Any]:
    fragment = candidate.fragment
    evidence = []
    source_text = " ".join([fragment.text, *fragment.cells.values()])
    for item in data.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        if quote and quote in source_text:
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
    }


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

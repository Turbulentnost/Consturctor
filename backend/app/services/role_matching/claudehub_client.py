from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas.regulation import (
    DocumentDefinition,
    DocumentMap,
    DocumentProcess,
    DocumentReference,
    DocumentRole,
    MatchEvidence,
    RegulationParseResult,
    RoleFunction,
)

logger = logging.getLogger(__name__)


class ClaudeHubError(RuntimeError):
    pass


def build_document_map(result: RegulationParseResult) -> DocumentMap:
    """Build the global document map with ClaudeHub, falling back to local heuristics."""
    try:
        chunks = _chunks(result)
        logger.info(
            "ClaudeHub global map start model=%s chunks=%s blocks=%s",
            settings.claudehub_model,
            len(chunks),
            len(result.fragments),
        )
        maps = [_map_chunk(chunk) for chunk in chunks]
        merged = _merge_maps(maps)
        merged.source = "claudehub"
        verified = _verify_map(merged, result)
        logger.info(
            "ClaudeHub global map complete roles=%s definitions=%s references=%s",
            len(verified.roles),
            len(verified.definitions),
            len(verified.references),
        )
        return verified
    except Exception as exc:  # noqa: BLE001 - global map should not stop role analysis.
        fallback = heuristic_document_map(result)
        fallback.source = "heuristic"
        fallback.warnings.append(f"ClaudeHub global map unavailable: {_safe_error(exc)}")
        logger.warning("ClaudeHub global map fallback: %s", _safe_error(exc))
        return fallback


def final_audit(functions: list[RoleFunction], result: RegulationParseResult) -> dict[str, Any]:
    """Use ClaudeHub for a compact final audit of extracted functions."""
    if not functions:
        return {"source": "heuristic", "warnings": ["Нет функций для финальной сверки"]}
    try:
        payload = {
            "instruction": (
                "Проверь набор извлечённых функций по доказательствам. "
                "Не добавляй новые функции. Верни JSON: "
                "{warnings:[], duplicateFunctionIds:[], unresolvedFunctionIds:[], confidenceAdjustments:{}}."
            ),
            "functions": [item.model_dump(mode="json") for item in functions],
            "availableBlocks": [
                {"blockId": fragment.fragmentId, "text": fragment.text[:800]}
                for fragment in result.fragments[:80]
            ],
        }
        raw = _post_json(payload, timeout=120.0)
        data = _load_json(raw)
        if not isinstance(data, dict):
            raise ClaudeHubError("Final audit is not an object")
        data["source"] = "claudehub"
        return data
    except Exception as exc:  # noqa: BLE001
        return {
            "source": "heuristic",
            "warnings": [f"ClaudeHub final audit unavailable: {_safe_error(exc)}"],
            "duplicateFunctionIds": [],
            "unresolvedFunctionIds": [
                item.functionId for item in functions if item.requiresUserConfirmation
            ],
            "confidenceAdjustments": {},
        }


def heuristic_document_map(result: RegulationParseResult) -> DocumentMap:
    roles: list[DocumentRole] = []
    definitions: list[DocumentDefinition] = []
    processes: list[DocumentProcess] = []
    references: list[DocumentReference] = []

    for fragment in result.fragments:
        text = (fragment.text or "").strip()
        if not text:
            continue
        role = _responsible_role(text)
        if role:
            roles.append(
                DocumentRole(
                    canonicalTitle=role,
                    aliases=[role],
                    sourceBlockIds=[fragment.fragmentId],
                    status="candidate",
                )
            )
        definition = _definition(text)
        if definition:
            term, meaning = definition
            definitions.append(
                DocumentDefinition(
                    term=term,
                    meaning=meaning,
                    scope=fragment.section,
                    sourceBlockId=fragment.fragmentId,
                    status="candidate",
                )
            )
        if fragment.blockType == "heading" and any(
            marker in text.lower()
            for marker in ("порядок", "процесс", "обработка", "согласование", "регистрация")
        ):
            processes.append(
                DocumentProcess(
                    name=text,
                    sections=[fragment.section or text],
                    sourceBlockIds=[fragment.fragmentId],
                    status="candidate",
                )
            )
        for ref in _reference_texts(text):
            references.append(
                DocumentReference(
                    fromBlockId=fragment.fragmentId,
                    referenceText=ref,
                    relation="explicit_reference",
                    status="candidate",
                )
            )

    return DocumentMap(
        roles=_dedupe_roles(roles),
        processes=_dedupe_processes(processes),
        definitions=_dedupe_definitions(definitions),
        references=references,
        source="heuristic",
    )


def _map_chunk(fragments: list[dict[str, Any]]) -> DocumentMap:
    prompt = {
        "instruction": (
            "Построй предварительную карту регламента. Не извлекай окончательные функции. "
            "Верни только JSON с полями roles, processes, definitions, references, systems, documents. "
            "Каждый вывод обязан содержать sourceBlockIds/sourceBlockId и статус candidate. "
            "Не придумывай блоки и цитаты."
        ),
        "blocks": fragments,
        "responseSchema": {
            "roles": [
                {
                    "canonicalTitle": "Менеджер по продажам",
                    "aliases": ["менеджер"],
                    "sourceBlockIds": ["reg-B-0001"],
                    "status": "candidate",
                }
            ],
            "processes": [{"name": "Обработка заявки", "sections": ["SEC-03"]}],
            "definitions": [
                {
                    "term": "Ответственный",
                    "meaning": "Менеджер по продажам",
                    "scope": "SEC-03",
                    "sourceBlockId": "reg-B-0001",
                    "status": "candidate",
                }
            ],
            "references": [
                {
                    "fromBlockId": "reg-B-0002",
                    "toBlockId": "reg-B-0001",
                    "referenceText": "указанный сотрудник",
                    "relation": "actor_inheritance",
                    "status": "candidate",
                }
            ],
            "systems": [],
            "documents": [],
        },
    }
    raw = _post_json(prompt, timeout=180.0)
    data = _load_json(raw)
    data = _coerce_document_map_data(data)
    return DocumentMap.model_validate(data)


def _post_json(prompt: dict[str, Any], *, timeout: float, model: str | None = None) -> str:
    if not settings.claude_api_key.strip():
        raise ClaudeHubError("CLAUDE_API_KEY is not configured")
    url = f"{settings.claudehub_base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model or settings.claudehub_model,
        "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {settings.claude_api_key}", "Accept": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"])


def _chunks(result: RegulationParseResult) -> list[list[dict[str, Any]]]:
    blocks = [
        {
            "blockId": fragment.fragmentId,
            "page": fragment.page,
            "section": fragment.section,
            "sectionPath": fragment.sectionPath,
            "blockType": fragment.blockType,
            "text": fragment.text,
            "cells": fragment.cells,
        }
        for fragment in result.fragments
        if (fragment.text or fragment.cells)
    ]
    size = max(20, int(settings.claudehub_max_blocks_per_chunk or 120))
    return [blocks[idx : idx + size] for idx in range(0, len(blocks), size)] or [[]]


def _merge_maps(maps: list[DocumentMap]) -> DocumentMap:
    roles: list[DocumentRole] = []
    processes: list[DocumentProcess] = []
    definitions: list[DocumentDefinition] = []
    references: list[DocumentReference] = []
    warnings: list[str] = []
    for item in maps:
        roles.extend(item.roles)
        processes.extend(item.processes)
        definitions.extend(item.definitions)
        references.extend(item.references)
        warnings.extend(item.warnings)
    return DocumentMap(
        roles=_dedupe_roles(roles),
        processes=_dedupe_processes(processes),
        definitions=_dedupe_definitions(definitions),
        references=_dedupe_references(references),
        warnings=warnings,
        source="mixed" if any(item.source == "heuristic" for item in maps) else "claudehub",
    )


def _verify_map(document_map: DocumentMap, result: RegulationParseResult) -> DocumentMap:
    known = {fragment.fragmentId: fragment for fragment in result.fragments}
    document_map.roles = [
        role for role in document_map.roles if any(block_id in known for block_id in role.sourceBlockIds)
    ]
    document_map.definitions = [
        definition
        for definition in document_map.definitions
        if not definition.sourceBlockId or definition.sourceBlockId in known
    ]
    document_map.references = [
        ref
        for ref in document_map.references
        if ref.fromBlockId in known and (not ref.toBlockId or ref.toBlockId in known)
    ]
    return document_map


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


def _coerce_document_map_data(data: dict[str, Any]) -> dict[str, Any]:
    """Keep ClaudeHub output useful even when it uses richer relation/status names."""
    if not isinstance(data, dict):
        return {}
    allowed_relations = {
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
    }
    allowed_statuses = {"verified", "candidate", "unverified"}
    for collection_name in ("roles", "processes", "definitions", "references"):
        items = data.get(collection_name)
        if not isinstance(items, list):
            data[collection_name] = []
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") not in allowed_statuses:
                item["status"] = "candidate"
            relation = item.get("relation")
            if relation and relation not in allowed_relations:
                item["relation"] = _relation_from_text(str(relation))
            if collection_name == "references":
                for key in ("fromBlockId", "toBlockId", "referenceText"):
                    if item.get(key) is None:
                        item[key] = ""
    for collection_name in ("systems", "documents"):
        items = data.get(collection_name)
        if not isinstance(items, list):
            data[collection_name] = []
            continue
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                value = item.strip()
                if value:
                    normalized.append({"value": value, "status": "candidate"})
                continue
            if not isinstance(item, dict):
                continue
            value = str(
                item.get("value") or item.get("name") or item.get("title") or item.get("text") or ""
            ).strip()
            if not value:
                continue
            item["value"] = value
            if item.get("status") not in allowed_statuses:
                item["status"] = "candidate"
            normalized.append(item)
        data[collection_name] = normalized
    return data


def _relation_from_text(value: str) -> str:
    text = value.casefold()
    if "actor" in text or "исполн" in text or "role" in text:
        return "actor_inheritance"
    if "condition" in text or "услов" in text:
        return "condition_for"
    if "exception" in text or "исключ" in text:
        return "exception_for"
    if "definition" in text or "term" in text or "определ" in text:
        return "definition_of"
    if "process" in text or "процесс" in text:
        return "same_process"
    return "explicit_reference"


def _responsible_role(text: str) -> str:
    match = re.search(
        r"(ответственн(?:ым|ой|ый|ого)?|исполнител(?:ем|ь)|владельц(?:ем|а))"
        r"[^.\n]{0,80}?(?:является|назначается|выступает)\s+(?P<role>[^.\n;]{3,90})",
        text,
        flags=re.I,
    )
    return match.group("role").strip(" ,;:-") if match else ""


def _definition(text: str) -> tuple[str, str] | None:
    match = re.search(
        r"(?P<term>[А-Яа-яЁёA-Za-z ]{2,60})(?:\s*\([^)]{2,12}\))?\s*[-—]\s*(?P<meaning>[^.\n]{3,160})",
        text,
    )
    if not match:
        return None
    return match.group("term").strip(), match.group("meaning").strip()


def _reference_texts(text: str) -> list[str]:
    refs = []
    for match in re.finditer(
        r"(?:см\.?|согласно|в соответствии с|указанн(?:ый|ая|ое)|вышеуказанн(?:ый|ая|ое))"
        r"[^.\n]{0,80}",
        text,
        flags=re.I,
    ):
        refs.append(match.group(0).strip())
    return refs


def _dedupe_roles(items: list[DocumentRole]) -> list[DocumentRole]:
    by_key: dict[str, DocumentRole] = {}
    for item in items:
        key = item.canonicalTitle.strip().casefold()
        if not key:
            continue
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            continue
        current.aliases.extend(alias for alias in item.aliases if alias not in current.aliases)
        current.sourceBlockIds.extend(
            block_id for block_id in item.sourceBlockIds if block_id not in current.sourceBlockIds
        )
    return list(by_key.values())


def _dedupe_processes(items: list[DocumentProcess]) -> list[DocumentProcess]:
    by_key: dict[str, DocumentProcess] = {}
    for item in items:
        key = item.name.strip().casefold()
        if not key:
            continue
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            continue
        current.sections.extend(section for section in item.sections if section not in current.sections)
        current.sourceBlockIds.extend(
            block_id for block_id in item.sourceBlockIds if block_id not in current.sourceBlockIds
        )
    return list(by_key.values())


def _dedupe_definitions(items: list[DocumentDefinition]) -> list[DocumentDefinition]:
    by_key: dict[tuple[str, str], DocumentDefinition] = {}
    for item in items:
        key = (item.term.strip().casefold(), item.meaning.strip().casefold())
        if key[0] and key[1]:
            by_key.setdefault(key, item)
    return list(by_key.values())


def _dedupe_references(items: list[DocumentReference]) -> list[DocumentReference]:
    by_key: dict[tuple[str, str, str, str], DocumentReference] = {}
    for item in items:
        key = (item.fromBlockId, item.toBlockId, item.referenceText.casefold(), item.relation)
        if item.fromBlockId:
            by_key.setdefault(key, item)
    return list(by_key.values())


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    if settings.claude_api_key and settings.claude_api_key in text:
        text = text.replace(settings.claude_api_key, "***")
    return text[:300]

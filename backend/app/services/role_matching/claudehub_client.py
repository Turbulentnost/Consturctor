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
    data = _coerce_document_map_data(data, fragments)
    return DocumentMap.model_validate(data)


def _post_json(prompt: dict[str, Any], *, timeout: float, model: str | None = None) -> str:
    raw, _model = _post_json_with_model(prompt, timeout=timeout, model=model)
    return raw


def _post_json_with_model(prompt: dict[str, Any], *, timeout: float, model: str | None = None) -> tuple[str, str]:
    if not settings.claude_api_key.strip():
        raise ClaudeHubError("CLAUDE_API_KEY is not configured")
    errors: list[str] = []
    for candidate in _model_chain(model):
        try:
            return _post_json_once(prompt, timeout=timeout, model=candidate), candidate
        except Exception as exc:  # noqa: BLE001 - try the next configured provider fallback.
            errors.append(f"{candidate}: {_safe_error(exc)}")
            logger.warning("ClaudeHub model fallback failed model=%s error=%s", candidate, _safe_error(exc))
    if model is None:
        try:
            return _post_chad_json(prompt, timeout=timeout), f"chad:{settings.chad_model}"
        except Exception as exc:  # noqa: BLE001 - expose Chad fallback errors with ClaudeHub errors.
            errors.append(f"chad:{settings.chad_model}: {_safe_error(exc)}")
            logger.warning("Chad API fallback failed model=%s error=%s", settings.chad_model, _safe_error(exc))
    raise ClaudeHubError("All ClaudeHub models failed: " + " | ".join(errors))


def _post_json_once(prompt: dict[str, Any], *, timeout: float, model: str) -> str:
    url = f"{settings.claudehub_base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {settings.claude_api_key}", "Accept": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise ClaudeHubError(f"HTTP {response.status_code} for model {model}: {body}") from exc
    data = response.json()
    return str(data["choices"][0]["message"]["content"])


def _post_chad_json(prompt: dict[str, Any], *, timeout: float) -> str:
    if not settings.chad_api_key.strip():
        raise ClaudeHubError("CHAD_AI is not configured")
    errors: list[str] = []
    for url in _chad_openai_urls():
        try:
            return _post_chad_openai_json(url, prompt, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - try next known Chad API shape.
            errors.append(f"{url}: {_safe_error(exc)}")
    try:
        return _post_chad_public_json(prompt, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"public: {_safe_error(exc)}")
    raise ClaudeHubError("All Chad API endpoints failed: " + " | ".join(errors))


def _post_chad_openai_json(url: str, prompt: dict[str, Any], *, timeout: float) -> str:
    payload = {
        "model": settings.chad_model,
        "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.chad_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise ClaudeHubError(f"HTTP {response.status_code} for Chad OpenAI endpoint: {response.text[:1000]}")
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise ClaudeHubError(f"Chad OpenAI endpoint returned non-JSON response: {response.text[:300]}")
    data = response.json()
    content = _openai_content(data)
    if not content:
        raise ClaudeHubError(f"Chad OpenAI endpoint returned no assistant content: {response.text[:1000]}")
    return content


def _post_chad_public_json(prompt: dict[str, Any], *, timeout: float) -> str:
    url = f"{settings.chad_base_url.rstrip('/')}/public/{settings.chad_model}"
    payload = {
        "message": json.dumps(prompt, ensure_ascii=False),
        "api_key": settings.chad_api_key,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
    if response.status_code != 200:
        raise ClaudeHubError(f"HTTP {response.status_code} for Chad model {settings.chad_model}: {response.text[:1000]}")
    data = response.json()
    if not data.get("is_success"):
        raise ClaudeHubError(
            f"Chad model {settings.chad_model} error "
            f"{data.get('error_code') or ''}: {data.get('error_message') or data}"
        )
    return str(data.get("response") or "")


def _chad_openai_urls() -> list[str]:
    base = settings.chad_base_url.rstrip("/")
    urls = []
    if "ask.chadgpt.ru" in base:
        urls.append("https://api.chadgpt.ru/v1/chat/completions")
    urls.append(f"{base}/v1/chat/completions")
    if base.endswith("/api"):
        urls.append(f"{base[:-4]}/v1/chat/completions")
    out: list[str] = []
    for item in urls:
        if item not in out:
            out.append(item)
    return out


def _openai_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text
    for key in ("response", "answer", "content", "message"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _model_chain(model: str | None) -> list[str]:
    if model:
        return [model]
    models = [
        settings.claudehub_model,
        settings.claudehub_fallback_model,
        settings.claudehub_external_fallback_model,
    ]
    out: list[str] = []
    for item in models:
        value = (item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


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


def _coerce_document_map_data(data: dict[str, Any], fragments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                value = item.strip()
                if not value:
                    continue
                if collection_name == "references":
                    ids = _infer_source_blocks([value], fragments or [])
                    normalized_items.append(
                        {
                            "fromBlockId": ids[0] if ids else "",
                            "referenceText": value,
                            "relation": "explicit_reference",
                            "status": "candidate",
                        }
                    )
                elif collection_name == "roles":
                    ids = _infer_source_blocks([value], fragments or [])
                    normalized_items.append(
                        {
                            "canonicalTitle": value,
                            "aliases": [value],
                            "sourceBlockIds": ids,
                            "status": "candidate",
                        }
                    )
                elif collection_name == "processes":
                    ids = _infer_source_blocks([value], fragments or [])
                    normalized_items.append(
                        {
                            "name": value,
                            "sections": [],
                            "sourceBlockIds": ids,
                            "status": "candidate",
                        }
                    )
                continue
            if isinstance(item, dict):
                normalized_items.append(item)
        data[collection_name] = normalized_items
        for item in normalized_items:
            if item.get("status") not in allowed_statuses:
                item["status"] = "candidate"
            if collection_name == "roles":
                title = str(
                    item.get("canonicalTitle") or item.get("role") or item.get("title") or item.get("name") or ""
                ).strip()
                item["canonicalTitle"] = title
                aliases = item.get("aliases")
                if not isinstance(aliases, list):
                    item["aliases"] = [title] if title else []
                item["sourceBlockIds"] = _coerce_source_block_ids(item, fragments, title)
            elif collection_name == "processes":
                name = str(item.get("name") or item.get("process") or item.get("title") or "").strip()
                item["name"] = name
                sections = item.get("sections")
                if not isinstance(sections, list):
                    item["sections"] = []
                item["sourceBlockIds"] = _coerce_source_block_ids(item, fragments, name)
            elif collection_name == "definitions":
                item["term"] = str(item.get("term") or item.get("name") or item.get("title") or "").strip()
                item["meaning"] = str(
                    item.get("meaning") or item.get("definition") or item.get("description") or ""
                ).strip()
                if not item.get("sourceBlockId"):
                    ids = _coerce_source_block_ids(item, fragments, item["term"])
                    item["sourceBlockId"] = ids[0] if ids else ""
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


def _coerce_source_block_ids(
    item: dict[str, Any],
    fragments: list[dict[str, Any]] | None,
    needle: str,
) -> list[str]:
    raw = item.get("sourceBlockIds") or item.get("sourceBlocks") or item.get("blockIds")
    if isinstance(raw, list):
        values = [str(value) for value in raw if str(value).strip()]
        if values:
            return values
    raw_one = item.get("sourceBlockId") or item.get("blockId")
    if isinstance(raw_one, str) and raw_one.strip():
        return [raw_one.strip()]
    if not fragments:
        return []
    search_values = [needle, str(item.get("responsibilities") or ""), str(item.get("description") or "")]
    return _infer_source_blocks(search_values, fragments)


def _infer_source_blocks(values: list[str], fragments: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        terms.append(text.casefold())
        for part in re.split(r"[/,;()]+", text):
            part = part.strip()
            if len(part) >= 4:
                terms.append(part.casefold())
    out: list[str] = []
    for fragment in fragments:
        block_id = str(fragment.get("blockId") or "")
        text = str(fragment.get("text") or "").casefold()
        if not block_id or not text:
            continue
        if any(term and term in text for term in terms):
            out.append(block_id)
        if len(out) >= 8:
            break
    return out


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

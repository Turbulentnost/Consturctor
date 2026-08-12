from __future__ import annotations

import re

from app.schemas.regulation import FragmentRoleMatch, RoleFunction


def dedupe_matches(matches: list[FragmentRoleMatch]) -> list[FragmentRoleMatch]:
    grouped: dict[str, FragmentRoleMatch] = {}
    order: list[str] = []
    for match in matches:
        key = _key(match.function)
        if not key:
            key = f"fragment:{match.fragmentId}"
        existing = grouped.get(key)
        if existing is None:
            if match.function is not None:
                match.function.duplicateGroup = key
            grouped[key] = match
            order.append(key)
            continue
        _merge_match(existing, match, key)
    return [grouped[key] for key in order]


def functions_from_matches(matches: list[FragmentRoleMatch]) -> list[RoleFunction]:
    return [match.function for match in matches if match.function is not None and match.function.isFunction]


def _merge_match(target: FragmentRoleMatch, source: FragmentRoleMatch, key: str) -> None:
    target.confidence = max(target.confidence, source.confidence)
    target.modelConfidence = max(target.modelConfidence, source.modelConfidence)
    target.requiresUserConfirmation = target.requiresUserConfirmation or source.requiresUserConfirmation
    if source.status == "pending" or target.status == "pending":
        target.status = "pending"
    elif source.status == "probable" and target.status != "accepted":
        target.status = "probable"
    for match_type in source.matchTypes:
        if match_type not in target.matchTypes:
            target.matchTypes.append(match_type)
    existing_quotes = {(item.fragmentId, item.quote) for item in target.evidence}
    for evidence in source.evidence:
        key_quote = (evidence.fragmentId, evidence.quote)
        if key_quote not in existing_quotes:
            target.evidence.append(evidence)
            existing_quotes.add(key_quote)
    if target.function is None or source.function is None:
        return
    target.function.confidence = max(target.function.confidence, source.function.confidence)
    target.function.duplicateGroup = key
    existing_function_quotes = {
        (item.fragmentId, item.quote) for item in target.function.evidence
    }
    for evidence in source.function.evidence:
        quote_key = (evidence.fragmentId, evidence.quote)
        if quote_key not in existing_function_quotes:
            target.function.evidence.append(evidence)
            existing_function_quotes.add(quote_key)
    existing_chain = {item.blockId for item in target.function.proofChain}
    for block in source.function.proofChain:
        if block.blockId not in existing_chain:
            target.function.proofChain.append(block)
            existing_chain.add(block.blockId)
    for condition in source.function.conditions:
        if condition not in target.function.conditions:
            target.function.conditions.append(condition)
    for dependency in source.function.dependencies:
        if dependency.blockId and all(
            item.blockId != dependency.blockId or item.type != dependency.type
            for item in target.function.dependencies
        ):
            target.function.dependencies.append(dependency)


def _key(function: RoleFunction | None) -> str:
    if function is None or not function.isFunction:
        return ""
    parts = [
        function.targetBlockId,
        function.actor.canonicalPosition,
        function.action,
        function.object,
        function.recipient,
    ]
    normalized = [_norm(part) for part in parts if _norm(part)]
    if len(normalized) < 2:
        return ""
    return "|".join(normalized)


def _norm(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", " ", value or "").strip().casefold()
    return re.sub(r"\s+", " ", text)

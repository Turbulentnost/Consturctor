from __future__ import annotations

import re

from app.schemas.regulation import FragmentRoleMatch, RoleFunction


def dedupe_matches(matches: list[FragmentRoleMatch]) -> list[FragmentRoleMatch]:
    grouped: dict[str, FragmentRoleMatch] = {}
    order: list[str] = []
    for match in matches:
        key = _key(match)
        if not key:
            key = f"fragment:{match.fragmentId}"
        existing = grouped.get(key)
        if existing is None:
            if match.function is not None:
                match.function.duplicateGroup = key
            grouped[key] = match
            order.append(key)
            continue
        preferred, other = _ordered_by_specificity(existing, match)
        if preferred is not existing:
            grouped[key] = preferred
        _merge_match(grouped[key], other, key)
    return [grouped[key] for key in order]


def functions_from_matches(matches: list[FragmentRoleMatch]) -> list[RoleFunction]:
    return [match.function for match in matches if match.function is not None and match.function.isFunction]


def sibling_match_ids(matches: list[FragmentRoleMatch], match_id: str) -> list[str]:
    """Match ids that share the same semantic duplicate group (including the seed)."""
    seed = next((item for item in matches if item.matchId == match_id), None)
    if seed is None:
        return []
    group = ""
    if seed.function is not None and seed.function.duplicateGroup:
        group = seed.function.duplicateGroup
    else:
        group = _key(seed)
    if not group:
        return [match_id]
    out = [match_id]
    for item in matches:
        if item.matchId == match_id:
            continue
        item_group = ""
        if item.function is not None and item.function.duplicateGroup:
            item_group = item.function.duplicateGroup
        else:
            item_group = _key(item)
        if item_group == group:
            out.append(item.matchId)
    return out


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


def _ordered_by_specificity(
    left: FragmentRoleMatch, right: FragmentRoleMatch
) -> tuple[FragmentRoleMatch, FragmentRoleMatch]:
    if _specificity(right) > _specificity(left):
        return right, left
    return left, right


def _specificity(match: FragmentRoleMatch) -> tuple:
    function = match.function
    object_len = len((function.object or "").strip()) if function else 0
    has_cells = 1 if match.fragment.cells else 0
    # Row fragments (...-R-003) are more specific than parent table blocks.
    is_row = 1 if "-R-" in match.fragmentId else 0
    text_len = len((match.fragment.text or "").strip())
    return (object_len, has_cells, is_row, match.confidence, text_len)


def _key(match: FragmentRoleMatch) -> str:
    function = match.function
    if function is None or not function.isFunction:
        return ""
    action = _norm(function.action)
    if not action:
        return ""
    object_key = _object_key(function.object)
    actor = _norm(function.actor.canonicalPosition)
    recipient = _norm(function.recipient)
    # Без blockId: одна и та же обязанность из шапки таблицы и строки матрицы
    # не должна требовать двух подтверждений.
    parts = [actor, action, object_key or "noobj", recipient]
    normalized = [part for part in parts if part]
    if len(normalized) < 2:
        return ""
    if not object_key:
        # Пустой объект — дополнительно привязываем к фрагменту, чтобы не склеить
        # разные «фиксирует» из разных разделов в одну кучу.
        normalized.append(_norm(match.fragmentId))
    return "|".join(normalized)


def _object_key(value: str) -> str:
    tokens = _norm(value).split()
    if not tokens:
        return ""
    # Берём смысловое ядро объекта. Слишком короткий ключ («документов»)
    # склеивал поиск / анализ / проверку в одну карточку.
    if len(tokens) == 1:
        return tokens[0]
    # 2–4 токена: комплектование пакета / поиск закупок / предварительный анализ
    return " ".join(tokens[:4])


def _norm(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", " ", value or "").strip().casefold()
    return re.sub(r"\s+", " ", text)

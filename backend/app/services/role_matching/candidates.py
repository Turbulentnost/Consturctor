from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.regulation import (
    BlockRelation,
    MatchSignal,
    RegulationFragment,
    RegulationParseResult,
    RoleProfile,
)
from app.services.role_matching.normalize import contains_phrase, contains_role_phrase, token_similarity
from app.services.role_matching.profile import all_candidate_terms, context_unit_terms, verified_aliases

_RESPONSIBLE_COLUMNS = ("ответственный", "исполнитель", "роль", "raci", "ответств")
_ACTION_COLUMNS = ("действие", "операция", "задача", "работа", "функция")
_SYSTEM_COLUMNS = ("система", "ис", "информационная система")
_ROLE_SIGNAL_TYPES = {
    "direct_role_mention",
    "inherited_from_section",
    "assigned_action",
    "process_role_alias",
    "interaction",
    "graph_relation",
    "definition_link",
    "actor_inheritance",
    "role_context",
    "unit_process",
}
_WORK_VERBS = (
    "разрабатывает",
    "оптимизирует",
    "тестирует",
    "документирует",
    "обучает",
    "внедряет",
    "подготавливает",
    "готовит",
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
    "контролирует",
    "ведет",
    "ведёт",
    "выполняет",
    "оформляет",
    "проводит",
    "фиксирует",
    "составляет",
    "настраивает",
    "обеспечивает",
    "организует",
    "анализирует",
    "отвечает",
    "осуществляет",
    "курирует",
    "координирует",
    "сопровождает",
    "мониторит",
    "участвует",
    "взаимодействует",
    "эскалирует",
    "комплектует",
    "поддерживает",
)
_INTERACTION_WORDS = {
    "передает": "recipient",
    "передаёт": "recipient",
    "направляет": "recipient",
    "получает": "recipient",
    "согласует": "approver",
    "утверждает": "approver",
    "инициирует": "initiator",
    "уведомляет": "informed",
    "информирует": "informed",
}


@dataclass(slots=True)
class Candidate:
    fragment: RegulationFragment
    signals: list[MatchSignal]
    semantic_score: float = 0.0


def collect_candidates(
    result: RegulationParseResult,
    profile: RoleProfile,
    relations: list[BlockRelation] | None = None,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    terms = all_candidate_terms(profile)
    verified = verified_aliases(profile)
    candidate_terms = [term for term in terms if term not in verified]
    unit_terms = context_unit_terms(profile)
    query = " ".join([*terms, *unit_terms])
    by_id = {fragment.fragmentId: fragment for fragment in result.fragments}
    relations_by_from = _relations_by_from(relations or [])
    for fragment in result.fragments:
        signals: list[MatchSignal] = []
        text = _fragment_search_text(fragment)
        for term in verified:
            if contains_role_phrase(text, term):
                signals.append(
                    _signal(
                        "direct_role_mention",
                        0.99,
                        fragment,
                        _quote(text, term),
                        f"Найдено прямое упоминание: {term}",
                    )
                )
                break
        for term in candidate_terms:
            if contains_role_phrase(text, term):
                signals.append(
                    _signal(
                        "direct_role_mention",
                        0.72,
                        fragment,
                        _quote(text, term),
                        f"Найден кандидатный алиас должности: {term}",
                    )
                )
                break
        section_text = " / ".join(fragment.sectionPath or ([fragment.section] if fragment.section else []))
        for term in verified:
            if contains_role_phrase(section_text, term):
                signals.append(
                    _signal(
                        "inherited_from_section",
                        0.95,
                        fragment,
                        section_text,
                        "Фрагмент находится внутри раздела, связанного с должностью",
                    )
                )
                break
        for term in candidate_terms:
            if contains_role_phrase(section_text, term):
                signals.append(
                    _signal(
                        "inherited_from_section",
                        0.70,
                        fragment,
                        section_text,
                        f"Раздел содержит кандидатный алиас должности: {term}",
                    )
                )
                break
        table_signal = _table_assignment_signal(fragment, verified, candidate_terms)
        if table_signal is not None:
            signals.append(table_signal)
        for alias in profile.processRoles:
            if alias.status == "verified" and contains_phrase(text, alias.value):
                signals.append(
                    _signal(
                        "process_role_alias",
                        0.91,
                        fragment,
                        _quote(text, alias.value),
                        f"Подтверждённая процессная роль: {alias.value}",
                    )
                )
        if profile.department and contains_phrase(text, profile.department):
            signals.append(
                _signal(
                    "department_relation",
                    0.63,
                    fragment,
                    _quote(text, profile.department),
                    "Фрагмент связан с подразделением, но не обязательно с должностью",
                )
            )
        relation_word = _interaction_word(text)
        if relation_word and any(contains_role_phrase(text, term) for term in verified):
            signals.append(
                _signal(
                    "interaction",
                    0.84,
                    fragment,
                    relation_word,
                    "Есть взаимодействие с должностью, требуется различать роль в процессе",
                )
            )
        if _artifact_hit(fragment, profile):
            signals.append(
                _signal(
                    "related_artifact_or_system",
                    0.48,
                    fragment,
                    "",
                    "Совпал документ или информационная система; это слабый сигнал",
                )
            )
        semantic_score = token_similarity(text + " " + section_text, query)
        if semantic_score >= 0.18:
            signals.append(
                _signal(
                    "semantic_candidate",
                    min(0.75, semantic_score),
                    fragment,
                    "",
                    "Токенная семантическая близость к профилю должности",
                )
            )
        signals.extend(
            _graph_signals(
                fragment,
                relations_by_from.get(fragment.fragmentId, []),
                by_id,
                verified,
                candidate_terms,
            )
        )
        context_signal = _role_context_signal(fragment, verified, candidate_terms, relations_by_from, by_id)
        if context_signal is not None:
            signals.append(context_signal)
        unit_signal = _unit_process_signal(fragment, unit_terms)
        if unit_signal is not None:
            signals.append(unit_signal)
        if signals and _has_role_signal(signals):
            candidates.append(Candidate(fragment=fragment, signals=signals, semantic_score=semantic_score))
    return candidates


def _unit_process_signal(
    fragment: RegulationFragment,
    unit_terms: list[str],
) -> MatchSignal | None:
    """Процессные обязанности подразделения (поиск, анализ…), без чужой именной роли."""
    if not unit_terms or not _looks_like_work(fragment):
        return None
    text = _fragment_search_text(fragment)
    # Отсекаем «руководствуется / утверждает структуру» и прочий орг-хром.
    if not _is_process_duty_text(text):
        return None
    section_text = " / ".join(fragment.sectionPath or ([fragment.section] if fragment.section else []))
    haystack = f"{text} {section_text}"
    hit = next((term for term in unit_terms if contains_phrase(haystack, term)), None)
    if hit is None:
        cells = " ".join((fragment.cells or {}).values())
        hit = next((term for term in unit_terms if contains_phrase(cells, term)), None)
    if hit is None:
        cell_keys = " ".join((fragment.cells or {}).keys()).casefold()
        if "тендерн" in cell_keys or "офис" in cell_keys:
            office_cell = next(
                (
                    value
                    for key, value in (fragment.cells or {}).items()
                    if "тендерн" in key.casefold() or "офис" in key.casefold()
                ),
                "",
            )
            if office_cell.strip() and _is_process_duty_text(office_cell):
                hit = unit_terms[0]
    if hit is None:
        return None
    if explicit_other_named_role(text):
        return None
    return _signal(
        "unit_process",
        0.74,
        fragment,
        _quote(haystack, hit) or hit,
        f"Процессная функция подразделения: {hit}",
    )


def _is_process_duty_text(text: str) -> bool:
    lowered = (text or "").casefold()
    if not lowered.strip():
        return False
    chrome = (
        "руководствуется",
        "утверждает",
        "подчиняется",
        "штатное расписание",
        "положение о",
        "версия 01",
        "лист ",
        "далее —",
        "далее -",
    )
    if any(item in lowered for item in chrome) and not any(
        verb in lowered
        for verb in (
            "осуществляет",
            "выполняет",
            "регистрирует",
            "формирует",
            "проводит",
            "анализирует",
            "проверяет",
            "организует",
            "контролирует",
            "комплектует",
            "отвечает",
        )
    ):
        return False
    process_verbs = (
        "осуществляет",
        "выполняет",
        "регистрирует",
        "формирует",
        "проводит",
        "анализирует",
        "проверяет",
        "организует",
        "контролирует",
        "комплектует",
        "отвечает",
        "фиксирует",
        "присваивает",
        "обеспечивает",
        "ведёт",
        "ведет",
        "подготавливает",
        "готовит",
        "сопровождает",
        "мониторит",
        "участвует",
    )
    return any(verb in lowered for verb in process_verbs)


def explicit_other_named_role(text: str) -> bool:
    """Фрагмент явно про другую должность (начальник, ведущий, аналитик…)."""
    lowered = (text or "").casefold()
    patterns = (
        r"руководитель\s+тендерного\s+офиса",
        r"начальник\s+тендерного\s+офиса",
        r"ведущий\s+менеджер",
        r"тендерный\s+аналитик",
        r"должность:\s*руководитель",
        r"должность:\s*начальник",
        r"должность:\s*ведущий",
        r"должность:\s*тендерный\s+аналитик",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _has_role_signal(signals: list[MatchSignal]) -> bool:
    return any(signal.matchType in _ROLE_SIGNAL_TYPES for signal in signals)


def _role_context_signal(
    fragment: RegulationFragment,
    verified_terms: list[str],
    candidate_terms: list[str],
    relations_by_from: dict[str, list[BlockRelation]],
    by_id: dict[str, RegulationFragment],
) -> MatchSignal | None:
    if not _looks_like_work(fragment):
        return None
    terms = [*verified_terms, *candidate_terms]
    fragment_context = fragment.context
    neighbor_text = " ".join(
        value
        for value in [
            fragment_context.previousText if fragment_context else "",
            fragment_context.nextText if fragment_context else "",
        ]
        if value
    )
    if any(contains_phrase(neighbor_text, term) for term in terms):
        return _signal(
            "role_context",
            0.68,
            fragment,
            neighbor_text[:220],
            "Рабочий фрагмент связан с должностью через соседний контекст",
        )
    for relation in relations_by_from.get(fragment.fragmentId, []):
        target = by_id.get(relation.toBlockId)
        if target is not None and any(contains_phrase(_fragment_search_text(target), term) for term in terms):
            return _signal(
                "role_context",
                max(0.60, relation.confidence * 0.9),
                fragment,
                relation.evidence or target.text[:220],
                f"Рабочий фрагмент связан с ролью через граф: {relation.relation}",
            )
    return None


def _looks_like_work(fragment: RegulationFragment) -> bool:
    text = _fragment_search_text(fragment).casefold()
    if fragment.blockType in {"list_item", "table_row"}:
        return any(verb in text for verb in _WORK_VERBS) or bool(fragment.cells)
    return any(verb in text for verb in _WORK_VERBS)


def _table_assignment_signal(
    fragment: RegulationFragment,
    verified_terms: list[str],
    candidate_terms: list[str],
) -> MatchSignal | None:
    if fragment.blockType != "table_row" or not fragment.cells:
        return None
    responsible_text = ""
    for header, value in fragment.cells.items():
        lower = header.lower()
        if any(key in lower for key in _RESPONSIBLE_COLUMNS):
            responsible_text += " " + value
        if lower.strip() in {"r", "a", "c", "i"}:
            responsible_text += " " + value
    if not responsible_text:
        return None
    if any(contains_role_phrase(responsible_text, term) for term in verified_terms):
        action = _action_from_cells(fragment.cells)
        return _signal(
            "assigned_action",
            0.98,
            fragment,
            responsible_text.strip(),
            f"Действие в строке таблицы назначено роли. {action}".strip(),
        )
    if any(contains_role_phrase(responsible_text, term) for term in candidate_terms):
        action = _action_from_cells(fragment.cells)
        return _signal(
            "assigned_action",
            0.74,
            fragment,
            responsible_text.strip(),
            f"Действие назначено кандидатному алиасу роли. {action}".strip(),
        )
    return None


def _artifact_hit(fragment: RegulationFragment, profile: RoleProfile) -> bool:
    text = _fragment_search_text(fragment)
    artifacts = [item.value for item in profile.systems + profile.documents]
    return any(contains_phrase(text, value) for value in artifacts)


def _graph_signals(
    fragment: RegulationFragment,
    relations: list[BlockRelation],
    by_id: dict[str, RegulationFragment],
    verified_terms: list[str],
    candidate_terms: list[str],
) -> list[MatchSignal]:
    out: list[MatchSignal] = []
    for relation in relations:
        target = by_id.get(relation.toBlockId)
        if target is None:
            continue
        target_text = _fragment_search_text(target)
        if any(contains_role_phrase(target_text, term) for term in verified_terms):
            out.append(
                _signal(
                    "actor_inheritance" if relation.relation == "actor_inheritance" else "graph_relation",
                    max(0.55, relation.confidence),
                    fragment,
                    relation.evidence or target.text[:180],
                    f"Связь с блоком {target.fragmentId}: {relation.relation}",
                )
            )
            continue
        if any(contains_role_phrase(target_text, term) for term in candidate_terms):
            out.append(
                _signal(
                    "definition_link" if relation.relation == "definition_of" else "graph_relation",
                    max(0.45, relation.confidence * 0.85),
                    fragment,
                    relation.evidence or target.text[:180],
                    f"Кандидатная связь с блоком {target.fragmentId}: {relation.relation}",
                )
            )
    return out[:4]


def _relations_by_from(relations: list[BlockRelation]) -> dict[str, list[BlockRelation]]:
    out: dict[str, list[BlockRelation]] = {}
    for relation in relations:
        out.setdefault(relation.fromBlockId, []).append(relation)
    return out


def _action_from_cells(cells: dict[str, str]) -> str:
    for header, value in cells.items():
        if any(key in header.lower() for key in _ACTION_COLUMNS) and value:
            return f"Действие: {value}"
    for header, value in cells.items():
        if any(key in header.lower() for key in _SYSTEM_COLUMNS) and value:
            return f"Система: {value}"
    return ""


def _interaction_word(text: str) -> str:
    lower = text.lower()
    for word in _INTERACTION_WORDS:
        if word in lower:
            return word
    return ""


def _fragment_search_text(fragment: RegulationFragment) -> str:
    values = [fragment.text]
    values.extend(fragment.cells.values())
    values.extend(fragment.tableHeaders)
    return " ".join(value for value in values if value)


def _signal(
    match_type: str,
    confidence: float,
    fragment: RegulationFragment,
    quote: str,
    explanation: str,
) -> MatchSignal:
    return MatchSignal(
        matchType=match_type,
        confidence=confidence,
        fragmentId=fragment.fragmentId,
        quote=quote[:500],
        explanation=explanation,
    )


def _quote(text: str, needle: str) -> str:
    if not needle:
        return ""
    lower = text.lower()
    idx = lower.find(needle.lower())
    if idx < 0:
        return needle
    start = max(0, idx - 60)
    end = min(len(text), idx + len(needle) + 60)
    return text[start:end].strip()

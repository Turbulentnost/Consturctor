from __future__ import annotations

from dataclasses import dataclass

from app.schemas.regulation import (
    MatchSignal,
    RegulationFragment,
    RegulationParseResult,
    RoleProfile,
)
from app.services.role_matching.normalize import contains_phrase, token_similarity
from app.services.role_matching.profile import all_candidate_terms, verified_aliases

_RESPONSIBLE_COLUMNS = ("ответственный", "исполнитель", "роль", "raci", "ответств")
_ACTION_COLUMNS = ("действие", "операция", "задача", "работа", "функция")
_SYSTEM_COLUMNS = ("система", "ис", "информационная система")
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


def collect_candidates(result: RegulationParseResult, profile: RoleProfile) -> list[Candidate]:
    candidates: list[Candidate] = []
    terms = all_candidate_terms(profile)
    verified = verified_aliases(profile)
    candidate_terms = [term for term in terms if term not in verified]
    query = " ".join(terms)
    for fragment in result.fragments:
        signals: list[MatchSignal] = []
        text = _fragment_search_text(fragment)
        for term in verified:
            if contains_phrase(text, term):
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
            if contains_phrase(text, term):
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
            if contains_phrase(section_text, term):
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
            if contains_phrase(section_text, term):
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
        if relation_word and any(contains_phrase(text, term) for term in verified):
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
        if signals:
            candidates.append(Candidate(fragment=fragment, signals=signals, semantic_score=semantic_score))
    return candidates


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
    if any(contains_phrase(responsible_text, term) for term in verified_terms):
        action = _action_from_cells(fragment.cells)
        return _signal(
            "assigned_action",
            0.98,
            fragment,
            responsible_text.strip(),
            f"Действие в строке таблицы назначено роли. {action}".strip(),
        )
    if any(contains_phrase(responsible_text, term) for term in candidate_terms):
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

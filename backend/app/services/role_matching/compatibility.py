"""Fast pre-check: role vs regulation text (no LLM / Cursor)."""

from __future__ import annotations

import re

from app.config import settings
from app.schemas.regulation import RegulationParseResult, RoleCompatibilityResult
from app.services.role_matching.candidates import collect_candidates
from app.services.role_matching.claudehub_client import heuristic_document_map
from app.services.role_matching.graph import build_block_graph
from app.services.role_matching.normalize import contains_role_phrase
from app.services.role_matching.profile import (
    all_candidate_terms,
    build_role_profile,
    enrich_role_profile,
    verified_aliases,
)
from app.services.role_matching.role_aliases import aliases_for_position

_RESPONSIBLE_HEADERS = ("ответствен", "исполнит", "роль", "raci", "owner", "участник")
_ROLE_LINE_RE = re.compile(
    r"(?P<role>[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z0-9\s\-/]{2,60})"
    r"\s*\|\s*",
)


def check_role_compatibility(
    result: RegulationParseResult,
    *,
    position: str,
    department: str,
) -> RoleCompatibilityResult:
    position = position.strip()
    department = department.strip()
    suggested = _suggested_roles_from_document(result)
    if settings.dev_mode:
        preview = ", ".join(suggested[:6]) if suggested else "любая роль из документа"
        return RoleCompatibilityResult(
            compatible=True,
            position=position,
            department=department,
            fragmentsTotal=len(result.fragments),
            candidatesTotal=len(result.fragments),
            matchedTerms=[position] if position else [],
            suggestedRoles=suggested[:12],
            hint=(
                f"Режим разработчика: проверка роли пропущена. "
                f"Будут извлечены все автоматизируемые функции документа. "
                f"Роли в документе: {preview}."
            ),
        )
    document_map = heuristic_document_map(result)
    relations = build_block_graph(result, document_map)
    profile = enrich_role_profile(
        build_role_profile(position=position, department=department, result=result),
        document_map,
    )
    candidates = collect_candidates(result, profile, relations)
    matched_terms = _matched_terms(result, profile)
    compatible = len(candidates) > 0 or bool(matched_terms)
    if not compatible and _mapped_role_matches_document(position, department, suggested):
        compatible = True
        matched_terms = matched_terms or aliases_for_position(position, department)[:4]
    hint = _hint(
        compatible=compatible,
        position=position,
        candidates_total=len(candidates),
        matched_terms=matched_terms,
        suggested=suggested,
    )
    return RoleCompatibilityResult(
        compatible=compatible,
        position=position,
        department=department,
        fragmentsTotal=len(result.fragments),
        candidatesTotal=len(candidates),
        matchedTerms=matched_terms,
        suggestedRoles=suggested[:12],
        hint=hint,
    )


def _mapped_role_matches_document(
    position: str,
    department: str,
    suggested: list[str],
) -> bool:
    mapped = aliases_for_position(position, department)
    if not mapped:
        return False
    if not suggested:
        return True
    for alias in mapped:
        alias_cf = alias.casefold()
        for role in suggested:
            role_cf = role.casefold()
            if alias_cf in role_cf or role_cf in alias_cf:
                return True
    return False


def _matched_terms(result: RegulationParseResult, profile) -> list[str]:
    terms = all_candidate_terms(profile)
    verified = verified_aliases(profile)
    found: list[str] = []
    seen: set[str] = set()
    for fragment in result.fragments:
        text = _fragment_text(fragment)
        section = " / ".join(fragment.sectionPath or ([fragment.section] if fragment.section else []))
        haystack = f"{text} {section}"
        for term in [*verified, *terms]:
            key = term.casefold()
            if key in seen or len(term) < 3:
                continue
            if contains_role_phrase(haystack, term):
                seen.add(key)
                found.append(term)
    return found


def _fragment_text(fragment) -> str:
    parts = [fragment.text or ""]
    parts.extend((fragment.cells or {}).values())
    parts.extend(fragment.tableHeaders or [])
    return " ".join(part for part in parts if part)


def _suggested_roles_from_document(result: RegulationParseResult) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for fragment in result.fragments:
        cells = fragment.cells or {}
        responsible = ""
        for header, value in cells.items():
            lower = header.casefold()
            if any(key in lower for key in _RESPONSIBLE_HEADERS) and value.strip():
                responsible = value.strip()
                break
        if responsible:
            for part in re.split(r"[;,/|]", responsible):
                role = part.strip()
                if len(role) < 3 or len(role) > 80:
                    continue
                key = role.casefold()
                if key in seen:
                    continue
                seen.add(key)
                out.append(role)
        for line in (fragment.text or "").splitlines():
            match = _ROLE_LINE_RE.match(line.strip())
            if not match:
                continue
            role = match.group("role").strip()
            if len(role) < 3:
                continue
            key = role.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(role)
    return out


def _hint(
    *,
    compatible: bool,
    position: str,
    candidates_total: int,
    matched_terms: list[str],
    suggested: list[str],
) -> str:
    if compatible:
        terms = ", ".join(matched_terms[:4])
        extra = f" Совпадения: {terms}." if terms else ""
        return (
            f"В документе найдено {candidates_total} фрагмент(ов) для роли «{position}»."
            f"{extra} Можно запускать выделение функций."
        )
    suggested_text = ""
    if suggested:
        preview = ", ".join(suggested[:6])
        suggested_text = f" В документе встречаются роли: {preview}."
    return (
        f"Роль «{position}» не найдена в тексте регламента — длинный анализ, "
        f"скорее всего, вернёт 0 функций.{suggested_text} "
        "Укажите роль как в таблице RACI или загрузите другой документ."
    )

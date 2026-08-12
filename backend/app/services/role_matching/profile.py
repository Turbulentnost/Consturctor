from __future__ import annotations

import re

from app.schemas.regulation import DocumentMap, RegulationParseResult, RoleAlias, RoleProfile
from app.services.role_matching.normalize import contains_phrase

_ABBR_RE = re.compile(r"(?P<full>[А-Яа-яЁёA-Za-z][^()\n]{3,80})\((?P<abbr>[А-ЯA-ZЁ]{2,8})\)")
_DALEE_RE = re.compile(
    r"(?P<full>[А-Яа-яЁёA-Za-z][^.\n]{3,100}?)(?:,?\s*)далее\s*[—-]\s*(?P<alias>[А-Яа-яЁёA-Za-z ]{2,60})",
    re.I,
)
_RESPONSIBLE_RE = re.compile(
    r"(ответственн(?:ым|ой|ые|ый|ого)?|владельц(?:ем|а)|исполнител(?:ем|ь))"
    r"[^.\n]{0,80}?(является|назначается|выступает)\s+(?P<role>[^.\n]{3,90})",
    re.I,
)


def build_role_profile(
    *,
    position: str,
    department: str,
    result: RegulationParseResult,
) -> RoleProfile:
    profile = RoleProfile(canonicalTitle=position.strip(), department=department.strip())
    _add_alias(profile.aliases, position, "verified", "Должность пользователя", [])
    if department:
        _add_alias(profile.aliases, department, "verified", "Подразделение пользователя", [])
        _add_alias(
            profile.aliases,
            f"сотрудник {department}",
            "candidate",
            "Кандидат от подразделения пользователя",
            [],
        )
    for alias in _generic_position_aliases(position):
        _add_alias(profile.aliases, alias, "candidate", "Вариант названия должности", [])

    for fragment in result.fragments:
        text = fragment.text or ""
        fragment_ids = [fragment.fragmentId]
        for match in _ABBR_RE.finditer(text):
            full = match.group("full").strip(" ,;:-")
            abbr = match.group("abbr").strip()
            if _role_like(full, position, department):
                _add_alias(profile.aliases, abbr, "verified", f"Определено в документе: {full} ({abbr})", fragment_ids)
        for match in _DALEE_RE.finditer(text):
            full = match.group("full").strip(" ,;:-")
            alias = match.group("alias").strip(" ,;:-")
            if _role_like(full, position, department):
                _add_alias(profile.aliases, alias, "verified", f"Определено в документе: {full}, далее {alias}", fragment_ids)
        for match in _RESPONSIBLE_RE.finditer(text):
            role = match.group("role").strip(" ,;:-")
            if _role_like(role, position, department):
                lead = match.group(1).strip()
                _add_alias(
                    profile.processRoles,
                    lead,
                    "verified",
                    f"Процессная роль связана с должностью во фрагменте {fragment.fragmentId}",
                    fragment_ids,
                )
    return profile


def enrich_role_profile(profile: RoleProfile, document_map: DocumentMap) -> RoleProfile:
    terms = [profile.canonicalTitle, profile.department, *[item.value for item in profile.aliases]]
    for role in document_map.roles:
        role_values = [role.canonicalTitle, *role.aliases]
        if not any(_any_role_like(value, terms) for value in role_values):
            continue
        for value in role_values:
            _add_alias(
                profile.aliases,
                value,
                role.status,
                "Алиас из глобальной карты документа ClaudeHub",
                role.sourceBlockIds,
            )
    return profile


def verified_aliases(profile: RoleProfile) -> list[str]:
    values = [profile.canonicalTitle]
    values.extend(alias.value for alias in profile.aliases if alias.status == "verified")
    values.extend(alias.value for alias in profile.processRoles if alias.status == "verified")
    return _unique(values)


def all_candidate_terms(profile: RoleProfile) -> list[str]:
    values = [profile.canonicalTitle, profile.department]
    values.extend(alias.value for alias in profile.aliases)
    values.extend(alias.value for alias in profile.processRoles)
    return [value for value in _unique(values) if value]


def _generic_position_aliases(position: str) -> list[str]:
    aliases: list[str] = []
    without_qualifier = _strip_position_qualifier(position)
    if without_qualifier and without_qualifier.casefold() != position.casefold():
        aliases.append(without_qualifier)
    normalized_hyphen = without_qualifier.replace("-", " ") if without_qualifier else ""
    if normalized_hyphen and normalized_hyphen.casefold() != without_qualifier.casefold():
        aliases.append(normalized_hyphen)
    return aliases


def _strip_position_qualifier(position: str) -> str:
    value = position.strip()
    value = re.sub(
        r"\s+\d+\s*(?:-?й|-?я|-?ой)?\s+категори[ия]\b.*$",
        "",
        value,
        flags=re.I,
    ).strip()
    value = re.sub(
        r"\s+\d+\s*(?:-?го|-?его|-?й|-?ой)?\s+разряд[а-я]*\b.*$",
        "",
        value,
        flags=re.I,
    ).strip()
    return value


def _role_like(value: str, position: str, department: str) -> bool:
    return contains_phrase(value, position) or bool(department and contains_phrase(value, department))


def _any_role_like(value: str, terms: list[str]) -> bool:
    return any(contains_phrase(value, term) or contains_phrase(term, value) for term in terms if term)


def _add_alias(items: list[RoleAlias], value: str, status: str, reason: str, source: list[str]) -> None:
    clean = (value or "").strip()
    if not clean:
        return
    for item in items:
        if item.value.lower() == clean.lower():
            item.sourceFragments.extend(fid for fid in source if fid not in item.sourceFragments)
            if item.status != "verified" and status == "verified":
                item.status = "verified"
                item.reason = reason
            return
    items.append(RoleAlias(value=clean, status=status, reason=reason, sourceFragments=list(source)))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out

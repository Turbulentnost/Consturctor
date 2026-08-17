"""Heuristic function extraction when Cursor/LLM unavailable (dev_mode)."""

from __future__ import annotations

import re
from uuid import uuid4

from app.schemas.regulation import (
    FragmentRoleMatch,
    FunctionActor,
    FunctionDependency,
    MatchEvidence,
    RegulationFragment,
    RegulationParseResult,
    RoleFunction,
    RoleMatchResult,
    RoleProfile,
)
from app.services.role_matching.profile import build_role_profile
from app.services.role_matching.role_aliases import aliases_for_position

_ROLE_HEADERS = ("роль", "участник", "ответствен", "исполнит", "owner", "raci")
_DUTY_HEADERS = ("обязан", "функц", "действ", "описан", "задач")
_WORK_RE = re.compile(
    r"\b("
    r"вед[её]т|ведёт|ведет|формирует|контролирует|регистрирует|направляет|"
    r"обеспечивает|сопровождает|фиксирует|мониторит|эскалирует|проводит|"
    r"подготавливает|согласовывает|обновляет|созда[её]т|создает"
    r")\b",
    re.I,
)


def build_heuristic_role_match(
    result: RegulationParseResult,
    *,
    regulation_id: str,
    position: str,
    department: str,
) -> RoleMatchResult:
    profile = build_role_profile(position=position, department=department, result=result)
    terms = _search_terms(position, department, profile.canonicalTitle)
    matches: list[FragmentRoleMatch] = []
    seen: set[str] = set()

    for fragment in result.fragments:
        for fn in _functions_from_fragment(fragment, position, terms):
            key = f"{fn.action}:{fn.object}:{fragment.fragmentId}"
            if key in seen:
                continue
            seen.add(key)
            idx = len(matches) + 1
            fn.functionId = f"F-{idx:04d}"
            matches.append(
                FragmentRoleMatch(
                    matchId=f"M-{idx:04d}",
                    fragmentId=fragment.fragmentId,
                    isRelevant=True,
                    relation="executor",
                    matchTypes=["semantic_candidate", "assigned_action"],
                    evidence=fn.evidence,
                    explanation=fn.explanation or "Эвристика Action Tracker / RACI",
                    modelConfidence=0.72,
                    confidence=0.72,
                    requiresUserConfirmation=True,
                    status="probable",
                    fragment=fragment,
                    function=fn,
                )
            )

    functions = [match.function for match in matches if match.function is not None]
    return RoleMatchResult(
        runId=f"role-run-{uuid4().hex[:12]}",
        regulationId=regulation_id,
        profile=profile,
        matches=matches,
        documentMap=None,
        relations=[],
        functions=functions,
        audit={
            "source": "heuristic_action_tracker",
            "diagnostics": {
                "fragmentsTotal": len(result.fragments),
                "functionsHeuristic": len(functions),
                "searchTerms": terms[:12],
            },
        },
    )


def _search_terms(position: str, department: str, canonical: str) -> list[str]:
    terms = [position.strip(), canonical.strip()]
    terms.extend(aliases_for_position(position, department))
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _functions_from_fragment(
    fragment: RegulationFragment,
    position: str,
    terms: list[str],
) -> list[RoleFunction]:
    out: list[RoleFunction] = []
    if fragment.blockType == "table_row" and fragment.cells:
        out.extend(_from_table_row(fragment, position, terms))
    text = (fragment.text or "").strip()
    if text and _text_matches_terms(text, terms) and _WORK_RE.search(text):
        out.append(_from_text(fragment, position, text))
    return out


def _from_table_row(
    fragment: RegulationFragment,
    position: str,
    terms: list[str],
) -> list[RoleFunction]:
    cells = fragment.cells or {}
    role_text = ""
    duty_text = ""
    for header, value in cells.items():
        lower = header.casefold()
        val = (value or "").strip()
        if not val:
            continue
        if any(key in lower for key in _ROLE_HEADERS):
            role_text = val
        if any(key in lower for key in _DUTY_HEADERS):
            duty_text = val
    combined = f"{role_text} {duty_text} {' '.join(cells.values())}".strip()
    if not combined or not _text_matches_terms(combined, terms):
        return []
    action, obj = _split_action_object(duty_text or combined)
    if not action:
        action = "выполняет"
    if not obj:
        obj = role_text or "обязанность по регламенту"
    quote = duty_text or role_text or combined[:200]
    return [
        RoleFunction(
            targetBlockId=fragment.fragmentId,
            isFunction=True,
            title=_title(action, obj),
            actor=FunctionActor(
                text=role_text or position,
                canonicalPosition=role_text or position,
                sourceBlockId=fragment.fragmentId,
            ),
            action=action,
            object=obj,
            recipient="",
            conditions=[],
            dependencies=[
                FunctionDependency(type="input", blockId=fragment.fragmentId, description=quote[:180])
            ],
            evidence=[
                MatchEvidence(
                    fragmentId=fragment.fragmentId,
                    sectionPath=fragment.sectionPath or ([fragment.section] if fragment.section else []),
                    quote=quote[:400],
                )
            ],
            explanation=f"Строка RACI/таблицы: {role_text}. {duty_text}".strip(),
            confidence=0.72,
            requiresUserConfirmation=True,
        )
    ]


def _from_text(fragment: RegulationFragment, position: str, text: str) -> RoleFunction:
    action, obj = _split_action_object(text)
    if not action:
        action = "выполняет"
    if not obj:
        obj = "процесс по регламенту"
    return RoleFunction(
        targetBlockId=fragment.fragmentId,
        isFunction=True,
        title=_title(action, obj),
        actor=FunctionActor(
            text=position,
            canonicalPosition=position,
            sourceBlockId=fragment.fragmentId,
        ),
        action=action,
        object=obj,
        recipient="",
        conditions=[],
        dependencies=[],
        evidence=[
            MatchEvidence(
                fragmentId=fragment.fragmentId,
                sectionPath=fragment.sectionPath or ([fragment.section] if fragment.section else []),
                quote=text[:400],
            )
        ],
        explanation=text[:240],
        confidence=0.68,
        requiresUserConfirmation=True,
    )


def _text_matches_terms(text: str, terms: list[str]) -> bool:
    hay = text.casefold()
    for term in terms:
        t = term.casefold().strip()
        if len(t) < 3:
            continue
        if t in hay:
            return True
        # «секретар» matches «секретарь ревизионной комиссии»
        if len(t) >= 5 and any(t in part for part in re.split(r"[\s/|,;]+", hay)):
            return True
    return False


def _split_action_object(text: str) -> tuple[str, str]:
    source = (text or "").strip()
    match = _WORK_RE.search(source)
    if not match:
        return "", source[:120]
    action = match.group(1).lower()
    tail = source[match.end() :].strip(" .,;:-")
    obj_match = re.match(r"(?P<object>[^.;,\n]{2,120})", tail)
    obj = obj_match.group("object").strip() if obj_match else tail[:120]
    return action, obj


def _title(action: str, obj: str) -> str:
    return f"{action.capitalize()} {obj}"[:180]

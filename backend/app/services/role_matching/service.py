from __future__ import annotations

import logging
import re
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import RoleMatchRun
from app.schemas.regulation import FragmentRoleMatch, RegulationParseResult, RoleMatchResult
from app.services.regulation.storage import get_document
from app.services.role_matching.candidates import collect_candidates
from app.services.role_matching.claudehub_client import build_document_map, final_audit
from app.services.role_matching.context import build_context_package
from app.services.role_matching.dedupe import dedupe_matches, functions_from_matches
from app.services.role_matching.graph import build_block_graph
from app.services.role_matching.llm_classifier import classify_candidate
from app.services.role_matching.profile import build_role_profile, enrich_role_profile
from app.services.role_matching.scoring import final_confidence, status_for_confidence

logger = logging.getLogger(__name__)


class RoleMatchError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_role_match_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    position: str,
    department: str,
) -> RoleMatchResult:
    position = position.strip()
    department = department.strip()
    if not position:
        raise RoleMatchError("Укажите должность")
    if not department:
        raise RoleMatchError("Укажите подразделение")
    doc = get_document(db, regulation_id=regulation_id, user_id=user_id)
    if doc is None:
        raise RoleMatchError("Регламент не найден", status_code=404)

    result = RegulationParseResult.model_validate(doc.result_json)
    document_map = build_document_map(result)
    logger.info(
        "Role match document map source=%s warnings=%s",
        document_map.source,
        len(document_map.warnings),
    )
    relations = build_block_graph(result, document_map)
    profile = enrich_role_profile(
        build_role_profile(position=position, department=department, result=result),
        document_map,
    )
    candidates = collect_candidates(result, profile, relations)
    matches: list[FragmentRoleMatch] = []
    for candidate in candidates:
        context = build_context_package(
            candidate,
            result=result,
            profile=profile,
            relations=relations,
            document_map=document_map,
        )
        classifier = classify_candidate(candidate, profile, context)
        confidence = final_confidence(candidate, classifier)
        role_functions = classifier.get("functions") or [classifier.get("function")]
        for role_function in role_functions:
            if role_function is not None:
                role_function.functionId = f"F-{len(matches) + 1:04d}"
                role_function.confidence = max(role_function.confidence, confidence)
            if not _is_real_function(role_function):
                continue
            requires_confirmation = bool(classifier.get("requiresUserConfirmation")) or confidence < 0.85
            if role_function is not None:
                requires_confirmation = requires_confirmation or role_function.requiresUserConfirmation
                role_function.requiresUserConfirmation = requires_confirmation
            status = status_for_confidence(confidence, requires_confirmation)
            if status == "rejected" and confidence < 0.40:
                # Keep the search strict for UI; low confidence can be logged later if needed.
                continue
            match = FragmentRoleMatch(
                matchId=f"M-{len(matches) + 1:04d}",
                fragmentId=candidate.fragment.fragmentId,
                isRelevant=bool(classifier.get("isRelevant", True)),
                relation=classifier.get("relation") or "none",
                matchTypes=list(dict.fromkeys(classifier.get("matchTypes") or [])),
                signals=candidate.signals,
                evidence=classifier.get("evidence") or [],
                explanation=str(classifier.get("explanation") or ""),
                modelConfidence=float(classifier.get("modelConfidence") or 0.0),
                confidence=confidence,
                contradictions=[str(x) for x in classifier.get("contradictions") or []],
                requiresUserConfirmation=requires_confirmation,
                status=status,
                fragment=candidate.fragment,
                function=role_function,
            )
            matches.append(match)

    matches_before_dedupe = list(matches)
    matches = dedupe_matches(matches)
    for idx, match in enumerate(matches, start=1):
        match.matchId = f"M-{idx:04d}"
        if match.function is not None:
            match.function.functionId = f"F-{idx:04d}"
    functions = functions_from_matches(matches)
    audit = final_audit(functions, result)
    audit["diagnostics"] = _diagnostics(result, candidates, matches_before_dedupe, matches)

    role_result = RoleMatchResult(
        runId=f"role-run-{uuid4().hex[:12]}",
        regulationId=regulation_id,
        profile=profile,
        matches=matches,
        documentMap=document_map,
        relations=relations,
        functions=functions,
        audit=audit,
    )
    run = RoleMatchRun(
        id=role_result.runId,
        regulation_id=regulation_id,
        user_id=user_id,
        position=position,
        department=department,
        result_json=role_result.model_dump(mode="json"),
    )
    run = db.merge(run)
    db.commit()
    db.refresh(run)
    return RoleMatchResult.model_validate(run.result_json)


def _is_real_function(role_function) -> bool:
    if role_function is None or not role_function.isFunction:
        return False
    action = (role_function.action or "").strip()
    if not action:
        return False
    combined = f"{role_function.action} {role_function.object}".strip().casefold()
    return re.match(r"^этап\s+\d+(?:\D|$)", combined) is None


def _diagnostics(
    result: RegulationParseResult,
    candidates,
    matches_before: list[FragmentRoleMatch],
    matches_after: list[FragmentRoleMatch],
) -> dict:
    by_section: dict[str, int] = {}
    for candidate in candidates:
        section = candidate.fragment.section or "Без раздела"
        by_section[section] = by_section.get(section, 0) + 1
    return {
        "fragmentsTotal": len(result.fragments),
        "candidatesTotal": len(candidates),
        "functionsBeforeDedupe": len([item for item in matches_before if item.function is not None]),
        "functionsAfterDedupe": len([item for item in matches_after if item.function is not None]),
        "candidateSections": by_section,
    }


def get_role_match_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    run_id: str,
) -> RoleMatchResult:
    run = _get_run(db, user_id=user_id, regulation_id=regulation_id, run_id=run_id)
    return RoleMatchResult.model_validate(run.result_json)


def update_match_status(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    run_id: str,
    match_id: str,
    status: str,
) -> RoleMatchResult:
    if status not in {"accepted", "rejected"}:
        raise RoleMatchError("Статус должен быть accepted или rejected")
    run = _get_run(db, user_id=user_id, regulation_id=regulation_id, run_id=run_id)
    data = dict(run.result_json or {})
    found = False
    for item in data.get("matches") or []:
        if item.get("matchId") == match_id:
            item["status"] = status
            item["requiresUserConfirmation"] = False
            function = item.get("function")
            function_id = ""
            if isinstance(function, dict):
                function["requiresUserConfirmation"] = False
                function_id = str(function.get("functionId") or "")
            found = True
            break
    if not found:
        raise RoleMatchError("Соответствие не найдено", status_code=404)
    for function in data.get("functions") or []:
        if isinstance(function, dict) and function_id and function.get("functionId") == function_id:
            function["requiresUserConfirmation"] = False
            break
    run.result_json = data
    db.add(run)
    db.commit()
    db.refresh(run)
    return RoleMatchResult.model_validate(run.result_json)


def _get_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    run_id: str,
) -> RoleMatchRun:
    run = (
        db.query(RoleMatchRun)
        .filter(
            RoleMatchRun.id == run_id,
            RoleMatchRun.user_id == user_id,
            RoleMatchRun.regulation_id == regulation_id,
        )
        .first()
    )
    if run is None:
        raise RoleMatchError("Запуск поиска не найден", status_code=404)
    return run

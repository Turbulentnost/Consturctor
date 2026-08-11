from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import RoleMatchRun
from app.schemas.regulation import FragmentRoleMatch, RegulationParseResult, RoleMatchResult
from app.services.regulation.storage import get_document
from app.services.role_matching.candidates import collect_candidates
from app.services.role_matching.llm_classifier import classify_candidate
from app.services.role_matching.profile import build_role_profile
from app.services.role_matching.scoring import final_confidence, status_for_confidence


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
    if not position.strip():
        raise RoleMatchError("Укажите должность")
    doc = get_document(db, regulation_id=regulation_id, user_id=user_id)
    if doc is None:
        raise RoleMatchError("Регламент не найден", status_code=404)

    result = RegulationParseResult.model_validate(doc.result_json)
    profile = build_role_profile(position=position, department=department, result=result)
    matches: list[FragmentRoleMatch] = []
    for idx, candidate in enumerate(collect_candidates(result, profile), start=1):
        classifier = classify_candidate(candidate, profile)
        confidence = final_confidence(candidate, classifier)
        requires_confirmation = bool(classifier.get("requiresUserConfirmation")) or confidence < 0.85
        status = status_for_confidence(confidence, requires_confirmation)
        if status == "rejected" and confidence < 0.40:
            # Keep the search strict for UI; low confidence can be logged later if needed.
            continue
        match = FragmentRoleMatch(
            matchId=f"M-{idx:04d}",
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
        )
        matches.append(match)

    role_result = RoleMatchResult(
        runId=f"role-run-{uuid4().hex[:12]}",
        regulationId=regulation_id,
        profile=profile,
        matches=matches,
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
            found = True
            break
    if not found:
        raise RoleMatchError("Соответствие не найдено", status_code=404)
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

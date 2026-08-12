from __future__ import annotations

import re

from app.schemas.regulation import (
    AgentReadinessResult,
    FunctionReadiness,
    MatchEvidence,
    ReadinessField,
    ReadinessFieldStatus,
    RegulationParseResult,
    RoleFunction,
)
from app.services.readiness.question_builder import build_questions
from app.services.readiness.rules import ALL_FIELDS, requirement_for


def analyze_readiness(
    *,
    readiness_run_id: str,
    regulation_id: str,
    role_match_run_id: str,
    functions: list[RoleFunction],
    result: RegulationParseResult,
) -> AgentReadinessResult:
    fragments = {fragment.fragmentId: fragment for fragment in result.fragments}
    function_results = [
        analyze_function(function, fragments.get(function.targetBlockId))
        for function in functions
        if function.isFunction
    ]
    questions = build_questions(function_results)
    blocking = _reasons(function_results, "blocking")
    important = _reasons(function_results, "important")
    optional = _reasons(function_results, "optional")
    score = _agent_score(function_results)
    return AgentReadinessResult(
        readinessRunId=readiness_run_id,
        regulationId=regulation_id,
        roleMatchRunId=role_match_run_id,
        score=score,
        blocking=blocking,
        important=important,
        optional=optional,
        functions=function_results,
        questions=questions,
        status="needs_answers" if questions else "ready",
    )


def analyze_function(function: RoleFunction, fragment) -> FunctionReadiness:
    source_text = _source_text(function, fragment)
    fields = [_field_status(field, function, source_text, fragment) for field in ALL_FIELDS]
    blocking = [field.reason for field in fields if field.required and field.severity == "blocking" and field.status in {"missing", "ambiguous", "conflict", "inferred"}]
    return FunctionReadiness(
        functionId=function.functionId,
        targetBlockId=function.targetBlockId,
        title=_title(function),
        fields=fields,
        blockingReasons=blocking,
        score=_function_score(fields),
    )


def _field_status(
    field: ReadinessField,
    function: RoleFunction,
    source_text: str,
    fragment,
) -> ReadinessFieldStatus:
    requirement = requirement_for(field, function, source_text)
    evidence = _evidence_for(field, function, source_text, fragment)
    if not requirement.required and not evidence:
        status = "not_applicable" if field in {"recipient", "system", "permissions", "approval"} else "missing"
    elif evidence:
        status = "inherited" if field == "actor" and function.actor.sourceBlockId != function.targetBlockId else "confirmed"
    elif _inferred(field, function, source_text):
        status = "inferred"
    else:
        status = "missing"
    if not requirement.required and status == "missing":
        severity = "optional"
    else:
        severity = requirement.severity
    return ReadinessFieldStatus(
        field=field,
        status=status,
        required=requirement.required,
        severity=severity,
        reason=requirement.reason,
        evidence=evidence,
    )


def _evidence_for(field: ReadinessField, function: RoleFunction, source_text: str, fragment) -> list[MatchEvidence]:
    block_id = function.targetBlockId
    quote = (fragment.text if fragment is not None else source_text).strip()[:500]
    if field == "actor" and function.actor.canonicalPosition:
        return [MatchEvidence(fragmentId=function.actor.sourceBlockId or block_id, quote=function.actor.text or function.actor.canonicalPosition)]
    if field == "action" and function.action:
        return [MatchEvidence(fragmentId=block_id, quote=function.action)]
    if field == "result" and function.object:
        return [MatchEvidence(fragmentId=block_id, quote=function.object)]
    if field == "recipient" and function.recipient:
        return [MatchEvidence(fragmentId=block_id, quote=function.recipient)]
    if field == "conditions" and function.conditions:
        return [MatchEvidence(fragmentId=block_id, quote=function.conditions[0][:500])]
    patterns = {
        "trigger": r"\b(при|после|когда|с момента|по факту|при поступлении)\b",
        "inputs": r"\b(вход|исходн|документ|данн|заявк|карточк|параметр)\b",
        "system": r"\b(CRM|ERP|1C|1С|систем|реестр|портал|почт)\b",
        "branches": r"\b(если|иначе|в случае|при отсутствии|при наличии)\b",
        "deadline": r"\b(срок|день|час|не позднее|в течение|до конца)\b",
        "errors": r"\b(ошибк|невозможн|недоступн|отказ|исключени|сбой)\b",
        "escalation": r"\b(эскалац|руководител|переда[её]т проблему|сообщает)\b",
        "approval": r"\b(соглас|утвержд|подтвержд|одобр)\b",
        "permissions": r"\b(прав|доступ|уч[её]тн|роль в системе|полномоч)\b",
        "restrictions": r"\b(запрещ|не допускается|не вправе|огранич)\b",
        "control": r"\b(критери|провер|контрол|подтвержд|протокол|результат)\b",
        "kpi": r"\b(KPI|метрик|показател|качество|срок)\b",
    }
    pattern = patterns.get(field)
    if pattern and re.search(pattern, source_text, re.I):
        return [MatchEvidence(fragmentId=block_id, quote=quote)]
    return []


def _inferred(field: ReadinessField, function: RoleFunction, source_text: str) -> bool:
    if field == "inputs" and function.object:
        return True
    if field == "control" and function.object:
        return True
    return False


def _source_text(function: RoleFunction, fragment) -> str:
    parts = [
        fragment.text if fragment is not None else "",
        function.action,
        function.object,
        function.recipient,
        " ".join(function.conditions),
        " ".join(item.description for item in function.dependencies),
        " ".join(item.text for item in function.proofChain),
    ]
    return " ".join(part for part in parts if part)


def _title(function: RoleFunction) -> str:
    return " ".join(part for part in [function.action, function.object] if part).strip() or function.functionId


def _function_score(fields: list[ReadinessFieldStatus]) -> int:
    relevant = [field for field in fields if field.status != "not_applicable"]
    if not relevant:
        return 100
    good = sum(1 for field in relevant if field.status in {"confirmed", "inherited"})
    partial = sum(1 for field in relevant if field.status == "inferred")
    return round(((good + partial * 0.5) / len(relevant)) * 100)


def _agent_score(functions: list[FunctionReadiness]) -> int:
    if not functions:
        return 0
    return round(sum(item.score for item in functions) / len(functions))


def _reasons(functions: list[FunctionReadiness], severity: str) -> list[str]:
    out: list[str] = []
    for function in functions:
        for field in function.fields:
            if field.severity == severity and field.status in {"missing", "ambiguous", "conflict", "inferred"}:
                text = f"{function.title}: {field.reason}"
                if text not in out:
                    out.append(text)
    return out

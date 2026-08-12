from __future__ import annotations

from app.services.role_matching.candidates import Candidate

_WEIGHTS = {
    "direct_role_mention": 0.45,
    "process_role_alias": 0.35,
    "assigned_action": 0.40,
    "inherited_from_section": 0.35,
    "department_relation": 0.10,
    "related_artifact_or_system": 0.05,
    "interaction": 0.25,
    "semantic_candidate": 0.15,
    "graph_relation": 0.30,
    "definition_link": 0.32,
    "actor_inheritance": 0.38,
}


def final_confidence(candidate: Candidate, classifier: dict) -> float:
    signal_score = 0.0
    types = {signal.matchType for signal in candidate.signals}
    for signal in candidate.signals:
        weight = _WEIGHTS.get(signal.matchType, 0.0)
        signal_score += weight * max(0.1, signal.confidence)
    max_by_type = {
        match_type: max(signal.confidence for signal in candidate.signals if signal.matchType == match_type)
        for match_type in types
    }
    if "assigned_action" in types and max_by_type.get("assigned_action", 0.0) >= 0.9:
        signal_score = max(signal_score, 0.90)
    if "direct_role_mention" in types and max_by_type.get("direct_role_mention", 0.0) >= 0.9:
        signal_score = max(signal_score, 0.88)
    if "inherited_from_section" in types and max_by_type.get("inherited_from_section", 0.0) >= 0.9:
        signal_score = max(signal_score, 0.82)
    if "actor_inheritance" in types and max_by_type.get("actor_inheritance", 0.0) >= 0.8:
        signal_score = max(signal_score, 0.78)
    if "definition_link" in types and max_by_type.get("definition_link", 0.0) >= 0.8:
        signal_score = max(signal_score, 0.74)
    if types == {"department_relation"}:
        signal_score = max(signal_score, 0.55)
    if types == {"related_artifact_or_system"}:
        signal_score = max(signal_score, 0.35)
    if classifier.get("relation") == "none" or not classifier.get("isRelevant", True):
        signal_score -= 0.45
    if classifier.get("contradictions"):
        signal_score -= 0.35
    model_confidence = float(classifier.get("modelConfidence") or 0.0)
    semantic_score = max(0.0, min(1.0, candidate.semantic_score))
    combined = signal_score + (0.10 * model_confidence) + (0.08 * semantic_score)
    return max(0.0, min(1.0, combined))


def status_for_confidence(confidence: float, requires_confirmation: bool) -> str:
    if confidence >= 0.85 and not requires_confirmation:
        return "accepted"
    if confidence >= 0.65:
        return "probable"
    if confidence >= 0.40:
        return "pending"
    return "rejected"

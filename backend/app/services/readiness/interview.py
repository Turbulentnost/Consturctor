from __future__ import annotations

from app.schemas.regulation import AgentReadinessResult, ReadinessQuestion


def unanswered_questions(readiness: AgentReadinessResult) -> list[ReadinessQuestion]:
    return [question for question in readiness.questions if not question.answered]


def next_question(readiness: AgentReadinessResult) -> ReadinessQuestion | None:
    questions = unanswered_questions(readiness)
    if not questions:
        return None
    return sorted(questions, key=lambda item: _severity_rank(item.severity))[0]


def _severity_rank(severity: str) -> int:
    return {"blocking": 0, "important": 1, "optional": 2}.get(severity, 3)

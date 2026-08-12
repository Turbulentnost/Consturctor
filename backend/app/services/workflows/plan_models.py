from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlanStep:
    id: str
    title: str
    action: str
    done_when: str = ""
    depends_on: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanStep:
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            action=str(data.get("action") or ""),
            done_when=str(data.get("done_when") or data.get("doneWhen") or ""),
            depends_on=[str(x) for x in (data.get("depends_on") or data.get("dependsOn") or [])],
        )


@dataclass
class OpenQuestion:
    id: str
    question: str
    why: str = ""
    answer: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenQuestion:
        return cls(
            id=str(data.get("id") or ""),
            question=str(data.get("question") or ""),
            why=str(data.get("why") or ""),
            answer=str(data.get("answer") or ""),
        )


@dataclass
class WorkflowPlan:
    title: str = ""
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    test_criteria: list[str] = field(default_factory=list)
    open_questions: list[OpenQuestion] = field(default_factory=list)
    raw_text: str = ""

    def unanswered(self) -> list[OpenQuestion]:
        return [q for q in self.open_questions if not (q.answer or "").strip()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "out_of_scope": list(self.out_of_scope),
            "steps": [asdict(s) for s in self.steps],
            "test_criteria": list(self.test_criteria),
            "open_questions": [asdict(q) for q in self.open_questions],
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowPlan:
        return cls(
            title=str(data.get("title") or ""),
            goal=str(data.get("goal") or ""),
            constraints=[str(x) for x in (data.get("constraints") or [])],
            out_of_scope=[
                str(x) for x in (data.get("out_of_scope") or data.get("outOfScope") or [])
            ],
            steps=[PlanStep.from_dict(x) for x in (data.get("steps") or []) if isinstance(x, dict)],
            test_criteria=[
                str(x) for x in (data.get("test_criteria") or data.get("testCriteria") or [])
            ],
            open_questions=[
                OpenQuestion.from_dict(x)
                for x in (data.get("open_questions") or data.get("openQuestions") or [])
                if isinstance(x, dict)
            ],
            raw_text=str(data.get("raw_text") or data.get("rawText") or ""),
        )

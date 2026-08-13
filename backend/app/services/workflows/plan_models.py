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
    options: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenQuestion:
        return cls(
            id=str(data.get("id") or ""),
            question=str(data.get("question") or ""),
            why=str(data.get("why") or ""),
            answer=str(data.get("answer") or ""),
            options=[str(x) for x in (data.get("options") or [])],
        )


@dataclass
class PlanRuntime:
    """Machine-readable run rules taken from user answers (not global hardcode)."""

    kind: str = ""  # e.g. site_search_excel; empty = no special runtime
    site_url: str = ""
    keywords: list[str] = field(default_factory=list)
    keyword_text: str = ""
    export_format: str = ""  # xlsx
    export_destination: str = ""  # desktop
    columns: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlanRuntime:
        if not isinstance(data, dict):
            return cls()
        export = data.get("export") if isinstance(data.get("export"), dict) else {}
        keywords = data.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        columns = data.get("columns") or export.get("columns") or []
        if isinstance(columns, str):
            columns = [columns]
        return cls(
            kind=str(data.get("kind") or ""),
            site_url=str(data.get("site_url") or data.get("siteUrl") or ""),
            keywords=[str(x).strip() for x in keywords if str(x).strip()],
            keyword_text=str(data.get("keyword_text") or data.get("keywordText") or ""),
            export_format=str(
                data.get("export_format")
                or export.get("format")
                or data.get("exportFormat")
                or ""
            ),
            export_destination=str(
                data.get("export_destination")
                or export.get("destination")
                or data.get("exportDestination")
                or ""
            ),
            columns=[str(x).strip() for x in columns if str(x).strip()],
        )

    def to_dict(self) -> dict[str, Any]:
        if not self.kind and not self.keywords and not self.keyword_text:
            return {}
        payload: dict[str, Any] = {"kind": self.kind}
        if self.site_url:
            payload["site_url"] = self.site_url
        if self.keywords:
            payload["keywords"] = list(self.keywords)
        if self.keyword_text:
            payload["keyword_text"] = self.keyword_text
        export: dict[str, Any] = {}
        if self.export_format:
            export["format"] = self.export_format
        if self.export_destination:
            export["destination"] = self.export_destination
        if self.columns:
            export["columns"] = list(self.columns)
        if export:
            payload["export"] = export
        return payload


@dataclass
class WorkflowPlan:
    title: str = ""
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    test_criteria: list[str] = field(default_factory=list)
    open_questions: list[OpenQuestion] = field(default_factory=list)
    runtime: PlanRuntime = field(default_factory=PlanRuntime)
    raw_text: str = ""

    def unanswered(self) -> list[OpenQuestion]:
        return [q for q in self.open_questions if not (q.answer or "").strip()]

    def to_dict(self) -> dict[str, Any]:
        data = {
            "title": self.title,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "out_of_scope": list(self.out_of_scope),
            "steps": [asdict(s) for s in self.steps],
            "test_criteria": list(self.test_criteria),
            "open_questions": [asdict(q) for q in self.open_questions],
            "raw_text": self.raw_text,
        }
        runtime = self.runtime.to_dict()
        if runtime:
            data["runtime"] = runtime
        return data

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
            runtime=PlanRuntime.from_dict(
                data.get("runtime") if isinstance(data.get("runtime"), dict) else None
            ),
            raw_text=str(data.get("raw_text") or data.get("rawText") or ""),
        )

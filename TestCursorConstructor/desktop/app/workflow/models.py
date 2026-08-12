from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            out_of_scope=[str(x) for x in (data.get("out_of_scope") or data.get("outOfScope") or [])],
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


@dataclass
class AttachedFile:
    """Loaded attachment: text document or image (base64 for vision prompt)."""

    name: str
    text: str
    path: str = ""
    kind: str = "text"  # text | image
    mime_type: str = ""
    data_b64: str = ""  # images only; may be large

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "text": self.text,
            "path": self.path,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "data_b64": self.data_b64,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttachedFile:
        return cls(
            name=str(data.get("name") or "file"),
            text=str(data.get("text") or ""),
            path=str(data.get("path") or ""),
            kind=str(data.get("kind") or "text"),
            mime_type=str(data.get("mime_type") or data.get("mimeType") or ""),
            data_b64=str(data.get("data_b64") or data.get("dataB64") or ""),
        )


@dataclass
class WorkflowRecord:
    id: str
    name: str
    phase: str  # document | plan | clarify | ready | executing | done
    document_text: str
    document_name: str = ""
    notes: str = ""
    attachments: list[AttachedFile] = field(default_factory=list)
    plan: WorkflowPlan | None = None
    plan_agent_id: str = ""
    plan_run_id: str = ""
    exec_agent_id: str = ""
    exec_run_id: str = ""
    repo_url: str = ""
    starting_ref: str = "main"
    auto_create_pr: bool = False
    last_result: str = ""
    branch: str = ""
    pr_url: str = ""
    # Описание локального запуска готового инструмента (без облака).
    # Ключи: cwd (папка), bat (лаунчер Windows), module (python -m ...), output (файл-результат).
    local_run: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def create(cls, *, name: str, document_text: str, document_name: str = "") -> WorkflowRecord:
        return cls(
            id=str(uuid4()),
            name=name or "Без названия",
            phase="document",
            document_text=document_text,
            document_name=document_name,
        )

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "phase": self.phase,
            "document_text": self.document_text,
            "document_name": self.document_name,
            "notes": self.notes,
            "attachments": [a.to_dict() for a in self.attachments],
            "plan": self.plan.to_dict() if self.plan else None,
            "plan_agent_id": self.plan_agent_id,
            "plan_run_id": self.plan_run_id,
            "exec_agent_id": self.exec_agent_id,
            "exec_run_id": self.exec_run_id,
            "repo_url": self.repo_url,
            "starting_ref": self.starting_ref,
            "auto_create_pr": self.auto_create_pr,
            "last_result": self.last_result,
            "branch": self.branch,
            "pr_url": self.pr_url,
            "local_run": dict(self.local_run),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowRecord:
        plan_data = data.get("plan")
        raw_attachments = data.get("attachments") or []
        attachments = [
            AttachedFile.from_dict(x) for x in raw_attachments if isinstance(x, dict)
        ]
        notes = str(data.get("notes") or "")
        document_text = str(data.get("document_text") or "")
        document_name = str(data.get("document_name") or "")
        # Backward compat: old saves had only document_text/name.
        if not attachments and document_text and document_name:
            attachments = [AttachedFile(name=document_name, text=document_text)]
        elif not attachments and document_text and not notes:
            notes = document_text
        return cls(
            id=str(data.get("id") or uuid4()),
            name=str(data.get("name") or "Без названия"),
            phase=str(data.get("phase") or "document"),
            document_text=document_text,
            document_name=document_name,
            notes=notes,
            attachments=attachments,
            plan=WorkflowPlan.from_dict(plan_data) if isinstance(plan_data, dict) else None,
            plan_agent_id=str(data.get("plan_agent_id") or ""),
            plan_run_id=str(data.get("plan_run_id") or ""),
            exec_agent_id=str(data.get("exec_agent_id") or ""),
            exec_run_id=str(data.get("exec_run_id") or ""),
            repo_url=str(data.get("repo_url") or ""),
            starting_ref=str(data.get("starting_ref") or "main"),
            auto_create_pr=bool(data.get("auto_create_pr", False)),
            last_result=str(data.get("last_result") or ""),
            branch=str(data.get("branch") or ""),
            pr_url=str(data.get("pr_url") or ""),
            local_run=dict(data.get("local_run") or {}),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
        )

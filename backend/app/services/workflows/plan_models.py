from __future__ import annotations

import re
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
    autonomy_level: int = 1
    autonomy_policy: str = ""

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
            autonomy_level=int(data.get("autonomy_level") or 1) or 1,
            autonomy_policy=str(data.get("autonomy_policy") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "autonomy_level": int(self.autonomy_level or 1),
        }
        if self.autonomy_policy:
            payload["autonomy_policy"] = self.autonomy_policy
        if not self.kind and not self.keywords and not self.keyword_text:
            return payload
        payload["kind"] = self.kind
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
    # Durable Q&A — survives when planner clears open_questions to [].
    answered_questions: list[OpenQuestion] = field(default_factory=list)
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
            "answered_questions": [asdict(q) for q in self.answered_questions],
            "raw_text": self.raw_text,
        }
        runtime = self.runtime.to_dict()
        if runtime:
            data["runtime"] = runtime
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowPlan:
        answered_raw = (
            data.get("answered_questions")
            or data.get("answeredQuestions")
            or data.get("answers")
            or []
        )
        answered: list[OpenQuestion] = []
        if isinstance(answered_raw, dict):
            # Legacy / phantom map {id: answer} or {id: {question, answer}}
            for key, value in answered_raw.items():
                if isinstance(value, dict):
                    item = OpenQuestion.from_dict({**value, "id": value.get("id") or key})
                else:
                    item = OpenQuestion(id=str(key), question=str(key), answer=str(value))
                if (item.answer or "").strip():
                    answered.append(item)
        elif isinstance(answered_raw, list):
            answered = [
                OpenQuestion.from_dict(x)
                for x in answered_raw
                if isinstance(x, dict) and str(x.get("answer") or "").strip()
            ]
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
            answered_questions=answered,
            runtime=PlanRuntime.from_dict(
                data.get("runtime") if isinstance(data.get("runtime"), dict) else None
            ),
            raw_text=str(data.get("raw_text") or data.get("rawText") or ""),
        )

    def record_answers(self, answers: dict[str, str]) -> None:
        """Persist user answers so they survive open_questions being cleared."""
        by_id = {q.id: i for i, q in enumerate(self.answered_questions)}
        open_by_id = {q.id: q for q in self.open_questions}

        for qid, raw in (answers or {}).items():
            ans = str(raw or "").strip()
            if not ans:
                continue
            meta = open_by_id.get(qid)
            if meta is not None:
                meta.answer = ans
                item = OpenQuestion(
                    id=meta.id,
                    question=meta.question,
                    why=meta.why,
                    answer=ans,
                    options=list(meta.options),
                )
            else:
                prev = (
                    self.answered_questions[by_id[qid]]
                    if qid in by_id
                    else OpenQuestion(id=qid, question=qid)
                )
                item = OpenQuestion(
                    id=qid,
                    question=prev.question or qid,
                    why=prev.why,
                    answer=ans,
                    options=list(prev.options),
                )
            if qid in by_id:
                self.answered_questions[by_id[qid]] = item
            else:
                by_id[qid] = len(self.answered_questions)
                self.answered_questions.append(item)

        # Also promote any open_questions that already have answers.
        for q in self.open_questions:
            ans = (q.answer or "").strip()
            if not ans:
                continue
            item = OpenQuestion(
                id=q.id,
                question=q.question,
                why=q.why,
                answer=ans,
                options=list(q.options),
            )
            if q.id in by_id:
                self.answered_questions[by_id[q.id]] = item
            else:
                by_id[q.id] = len(self.answered_questions)
                self.answered_questions.append(item)

        self._mirror_answers_into_constraints()
        self.sanitize_open_questions()

    def drop_resolved_open_questions(self) -> None:
        """Не держать в open_questions то, на что пользователь уже ответил."""
        answered_ids = {
            q.id for q in self.answered_questions if (q.answer or "").strip()
        }
        answered_texts = [
            _norm_question(q.question)
            for q in self.answered_questions
            if (q.answer or "").strip()
        ]
        kept: list[OpenQuestion] = []
        for q in self.open_questions:
            if (q.answer or "").strip():
                continue
            if q.id in answered_ids:
                continue
            if any(_same_question(q.question, prev) for prev in answered_texts if prev):
                continue
            kept.append(q)
        self.open_questions = kept

    def sanitize_open_questions(self) -> None:
        """Keep only human-facing blockers; drop tool/impl loops after prior answers."""
        self.drop_resolved_open_questions()
        delegated = [
            q for q in self.answered_questions if _is_delegate_answer(q.answer)
        ]
        answered = [q for q in self.answered_questions if (q.answer or "").strip()]
        kept: list[OpenQuestion] = []
        for q in self.open_questions:
            if (q.answer or "").strip():
                continue
            if _is_implementation_question(q):
                continue
            if any(_same_topic(q.question, prev.question) for prev in answered):
                continue
            if any(_same_topic(q.question, prev.question) for prev in delegated):
                continue
            q.options = [opt for opt in q.options if not _looks_like_tool_option(opt)]
            kept.append(q)
        if len(answered) >= _MAX_ANSWERED_BEFORE_STOP:
            kept = [q for q in kept if _is_business_question(q.question)]
        self.open_questions = kept[:_MAX_OPEN_QUESTIONS]

    def _mirror_answers_into_constraints(self) -> None:
        """Keep a plain-text copy in constraints for older prompt/runtime paths."""
        existing = "\n".join(self.constraints).casefold()
        for q in self.answered_questions:
            ans = (q.answer or "").strip()
            if not ans:
                continue
            marker = f"уточнение ({q.id.casefold()})"
            if marker in existing or ans.casefold() in existing:
                continue
            line = f"Уточнение ({q.id}): {q.question} → {ans}"
            self.constraints.append(line)
            existing += "\n" + line.casefold()

    def answered_block_text(self) -> str:
        if not self.answered_questions:
            return ""
        lines = ["===== ОТВЕТЫ ПОЛЬЗОВАТЕЛЯ (обязательны к учёту) ====="]
        for q in self.answered_questions:
            ans = (q.answer or "").strip()
            if not ans:
                continue
            lines.append(f"- {q.id}: {q.question}")
            lines.append(f"  answer: {ans}")
        lines.append("===== КОНЕЦ ОТВЕТОВ =====")
        return "\n".join(lines) if len(lines) > 2 else ""

    def ensure_followups_for_unclear_answers(
        self,
        *,
        recent_answers: dict[str, str] | None = None,
        prior_questions: list[OpenQuestion] | None = None,
    ) -> list[OpenQuestion]:
        """Safety net only for empty/placeholder answers. Meaningfulness is the LLM's job."""
        if self.unanswered():
            return []
        recent = recent_answers or {}
        priors = {q.id: q for q in (prior_questions or [])}
        created: list[OpenQuestion] = []
        for qid, raw in recent.items():
            ans = str(raw or "").strip()
            meta = priors.get(qid) or next(
                (q for q in self.answered_questions if q.id == qid),
                None,
            )
            question = (meta.question if meta else "") or qid
            if _is_delegate_answer(ans):
                continue
            follow = _followup_for_placeholder_answer(qid, question, ans)
            if follow is None:
                continue
            if any(q.id == follow.id for q in self.open_questions):
                continue
            self.open_questions.append(follow)
            created.append(follow)
            if len(created) >= 2:
                break
        return created


def _norm_question(text: str) -> str:
    folded = " ".join(str(text or "").casefold().replace("ё", "е").split())
    return re.sub(r"[«»\"'?:！!.,;()]+", "", folded).strip()


def _same_question(left: str, right: str) -> bool:
    na = _norm_question(left)
    nb = _norm_question(right)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) >= 24 and shorter in longer


# Only non-answers / UI placeholders — NOT short but informative replies like «COM», «1С».
_MAX_OPEN_QUESTIONS = 3
_MAX_ANSWERED_BEFORE_STOP = 5

_DELEGATE_HINTS = (
    "выясни сам",
    "определи сам",
    "посмотри сам",
    "найди сам",
    "узнай сам",
    "разберись",
    "сам как",
    "сами найд",
    "точные не знаю",
    "точно не знаю",
    "не знаю точн",
    "не знаю, выясни",
    "не знаю выясни",
)

_IMPL_HINTS = (
    "constructor_tool",
    "odata",
    "imap.",
    "onec.",
    "turboproject",
    "fixtures",
    "backend_url",
    "invoker",
    "constructor_api",
    "guid",
    "entity",
    "resheniya",
    "значение n",
    "значение n ",
    "live или только",
    "способ доступа",
)

_TOOL_OPTION_HINTS = (
    "odata",
    "imap",
    "constructor",
    "onec.",
    "turboproject",
    "fixtures",
    "com ",
    "graph api",
    "notify_tools",
    "constructor_tool",
)

_BUSINESS_HINTS = (
    "уведом",
    "отчёт",
    "отчет",
    "как часто",
    "кому",
    "куда",
    "срок",
    "расписан",
    "результат",
)

_STOP_WORDS = frozenset(
    {
        "какой",
        "какое",
        "какие",
        "какая",
        "значение",
        "для",
        "чтобы",
        "этот",
        "этого",
        "нужно",
        "агент",
        "агенту",
        "правила",
        "правило",
        "если",
        "или",
        "как",
        "что",
        "чем",
        "при",
        "без",
        "есть",
        "было",
        "будет",
        "вопрос",
        "ответе",
        "выбран",
    }
)

_PLACEHOLDER_ANSWERS = frozenset(
    {
        "ок",
        "окей",
        "хорошо",
        "ладно",
        "другое",
        "свой вариант",
        "как обычно",
        "стандартно",
        "по умолчанию",
        "...",
        "…",
        "—",
        "-",
        "n/a",
        "na",
        "тbd",
        "tbd",
    }
)


def _is_delegate_answer(answer: str) -> bool:
    folded = (answer or "").casefold().replace("ё", "е")
    if not folded.strip():
        return False
    if folded.strip() in {"не знаю", "пока неизвестно"}:
        return True
    return any(hint in folded for hint in _DELEGATE_HINTS)


def _looks_like_tool_option(option: str) -> bool:
    folded = (option or "").casefold()
    return any(hint in folded for hint in _TOOL_OPTION_HINTS)


def _is_implementation_question(question: OpenQuestion | str) -> bool:
    text = question.question if isinstance(question, OpenQuestion) else str(question or "")
    folded = text.casefold().replace("ё", "е")
    if any(hint in folded for hint in _IMPL_HINTS):
        return True
    if re.search(r"\bq\d+\b", folded):
        return True
    options = question.options if isinstance(question, OpenQuestion) else []
    if options and all(_looks_like_tool_option(opt) for opt in options):
        return True
    return False


def _is_business_question(text: str) -> bool:
    folded = (text or "").casefold().replace("ё", "е")
    return any(hint in folded for hint in _BUSINESS_HINTS)


def _topic_words(text: str) -> set[str]:
    words = re.findall(r"[a-zа-я0-9]{4,}", _norm_question(text))
    return {w for w in words if w not in _STOP_WORDS}


def _same_topic(left: str, right: str) -> bool:
    if _same_question(left, right):
        return True
    a, b = _topic_words(left), _topic_words(right)
    return len(a & b) >= 2


def _followup_for_placeholder_answer(
    qid: str,
    question: str,
    answer: str,
) -> OpenQuestion | None:
    ans = (answer or "").strip()
    q = (question or "").strip()
    if not ans:
        return OpenQuestion(
            id=f"{qid}_more",
            question=f"Уточните ответ: {q or 'что именно выбрать?'}",
            why="Пустой ответ нельзя использовать в реализации.",
            options=["Опишу подробно своим текстом", "Пока данных нет — отложить шаг"],
        )
    if ans.casefold() not in _PLACEHOLDER_ANSWERS:
        return None
    return OpenQuestion(
        id=f"{qid}_more",
        question=(
            f"Ответ «{ans}» не даёт рабочей детали. "
            f"Сформулируйте конкретнее: {q or 'что именно имеется в виду?'}"
        ),
        why="Заглушка вместо факта — нельзя перенести в steps/runtime.",
        options=[
            "Опишу конкретно своим текстом",
            "Пока неизвестно — предложите варианты",
            "Этот шаг не нужен",
        ],
    )

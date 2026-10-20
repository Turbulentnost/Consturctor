"""Вопросы агента человеку во время хода — и при составлении плана, и при выполнении.

Встроенный askQuestion локальный Cursor SDK сразу отклоняет, поэтому агент спрашивает
MCP-инструментом ask_user конфигурации: MCP-сервер ставит вопрос сюда, экран сессии
показывает его вместо поля ввода, ответ уходит агенту результатом инструмента.

HTTP-запрос ожидания висит не дольше WAIT_SECONDS: MCP-сервер конфигурации повторяет его внутри
одного вызова ask_user, пока человек не ответит. Срока у вопроса нет — его снимает только ответ,
пропуск или остановка сессии.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

WAIT_SECONDS = 50.0
MAX_QUESTIONS = 4
MAX_OPTIONS = 8
MAX_CHOICE_OPTIONS = 1000
MAX_COLUMNS = 8
CONFIRM_YES = "yes"

Outcome = Literal["waiting", "answered", "skipped", "cancelled"]
# Пусто — вопрос ask_user: варианты кнопками и свой ответ текстом.
# radio / checkbox — выбор из списка (ask_choice): один или несколько вариантов, без своего ответа.
Choice = Literal["", "radio", "checkbox"]


class QuestionOption(BaseModel):
    id: str = ""
    label: str = ""
    # Ячейки строки под заголовками columns вопроса; label тогда — они же через « | ».
    cells: list[str] = Field(default_factory=list)


class QuestionItem(BaseModel):
    id: str = ""
    prompt: str
    options: list[QuestionOption] = Field(default_factory=list)
    allow_multiple: bool = False
    choice: Choice = ""
    columns: list[str] = Field(default_factory=list)
    # Выбор из одного варианта — не выбор: человек отвечает «да / нет», агент получает этот вариант или пусто.
    single: QuestionOption | None = None


class PendingQuestion(BaseModel):
    id: str
    title: str = ""
    questions: list[QuestionItem]
    asked_at: str


class QuestionAnswer(BaseModel):
    question_id: str
    selected: list[str] = Field(default_factory=list)
    text: str = ""


class QuestionError(ValueError):
    pass


@dataclass
class _Entry:
    session_id: str
    question: PendingQuestion
    outcome: Outcome = "waiting"
    answers: list[dict[str, Any]] = field(default_factory=list)


def _normalized(items: list[QuestionItem]) -> list[QuestionItem]:
    result: list[QuestionItem] = []
    for index, item in enumerate(items[:MAX_QUESTIONS], start=1):
        prompt = item.prompt.strip()
        if not prompt:
            continue
        limit = MAX_CHOICE_OPTIONS if item.choice else MAX_OPTIONS
        columns = [column.strip() for column in item.columns[:MAX_COLUMNS]] if item.choice else []
        options: list[QuestionOption] = []
        for number, option in enumerate(item.options[:limit], start=1):
            cells = [cell.strip() for cell in option.cells[: len(columns)]] if columns else []
            label = option.label.strip() or " | ".join(cell for cell in cells if cell)
            if label:
                options.append(QuestionOption(id=option.id.strip() or f"o{number}", label=label, cells=cells))
        if item.choice and not options:
            raise QuestionError(f"Нет вариантов для выбора: «{prompt}»")
        if item.choice and len(options) == 1:
            only = options[0]
            result.append(
                QuestionItem(
                    id=item.id.strip() or f"q{index}",
                    prompt=prompt,
                    options=[QuestionOption(id=CONFIRM_YES, label=f"Да — {only.label}"), QuestionOption(id="no", label="Нет")],
                    choice="radio",
                    single=only,
                )
            )
            continue
        multiple = item.choice == "checkbox" if item.choice else item.allow_multiple
        result.append(
            QuestionItem(
                id=item.id.strip() or f"q{index}",
                prompt=prompt,
                options=options,
                allow_multiple=multiple,
                choice=item.choice,
                columns=columns,
            )
        )
    return result


class QuestionBoard:
    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._entries: dict[str, _Entry] = {}

    def ask(self, session_id: str, title: str, items: list[QuestionItem]) -> PendingQuestion:
        questions = _normalized(items)
        if not questions:
            raise QuestionError("Нет ни одного вопроса с текстом")
        question = PendingQuestion(
            id=uuid4().hex,
            title=title.strip(),
            questions=questions,
            asked_at=datetime.now(UTC).isoformat(),
        )
        with self._changed:
            for entry in self._entries.values():
                if entry.session_id == session_id and entry.outcome == "waiting":
                    entry.outcome = "cancelled"
            self._entries[question.id] = _Entry(session_id, question)
            self._changed.notify_all()
        return question

    def pending(self, session_id: str) -> PendingQuestion | None:
        with self._changed:
            for entry in reversed(self._entries.values()):
                if entry.session_id == session_id and entry.outcome == "waiting":
                    return entry.question
        return None

    def wait(self, session_id: str, question_id: str, timeout: float) -> dict[str, Any]:
        """Ждать ответа до timeout секунд; результат инструмента для агента."""
        deadline = time.monotonic() + max(0.0, min(timeout, WAIT_SECONDS))
        with self._changed:
            entry = self._entries.get(question_id)
            if entry is None or entry.session_id != session_id:
                raise KeyError(question_id)
            while entry.outcome == "waiting":
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._changed.wait(left)
            return _tool_result(entry)

    def answer(
        self, session_id: str, question_id: str, answers: list[QuestionAnswer], *, skipped: bool = False
    ) -> str:
        """Принять ответ с экрана. Возвращает текст ответа для чата."""
        with self._changed:
            entry = self._entries.get(question_id)
            if entry is None or entry.session_id != session_id:
                raise KeyError(question_id)
            if entry.outcome != "waiting":
                raise QuestionError("На этот вопрос уже ответили или агент перестал ждать")
            given = {item.question_id: item for item in answers}
            resolved: list[dict[str, Any]] = []
            for question in entry.question.questions:
                reply = given.get(question.id)
                labels = {option.id: option.label for option in question.options}
                ids = [key for key in dict.fromkeys(reply.selected if reply else []) if key in labels]
                if not question.allow_multiple:
                    ids = ids[:1]
                selected = [labels[key] for key in ids]
                text = "" if question.choice or not reply else reply.text.strip()
                if question.choice and not skipped and not ids:
                    raise QuestionError(f"Выберите ответ: «{question.prompt}»")
                if question.single and ids:
                    chosen = [question.single] if ids == [CONFIRM_YES] else []
                    resolved.append(
                        {
                            "question": question.prompt,
                            "selected": [option.label for option in chosen],
                            "selected_ids": [option.id for option in chosen],
                            "text": "",
                        }
                    )
                elif selected or text:
                    item: dict[str, Any] = {"question": question.prompt, "selected": selected, "text": text}
                    if question.choice:
                        item["selected_ids"] = ids
                    resolved.append(item)
            if not skipped and not resolved:
                raise QuestionError("Выберите вариант или напишите ответ")
            entry.outcome = "skipped" if skipped else "answered"
            entry.answers = resolved
            self._changed.notify_all()
            return _chat_text(entry)

    def cancel(self, session_id: str) -> None:
        with self._changed:
            for entry in self._entries.values():
                if entry.session_id == session_id and entry.outcome == "waiting":
                    entry.outcome = "cancelled"
            for key in [key for key, entry in self._entries.items() if entry.session_id == session_id]:
                if self._entries[key].outcome != "waiting":
                    del self._entries[key]
            self._changed.notify_all()


def _chat_text(entry: _Entry) -> str:
    if entry.outcome == "skipped":
        return "Пропущено — агент решит сам."
    several = len(entry.question.questions) > 1
    lines = []
    for item in entry.answers:
        reply = "; ".join([*item["selected"], *([item["text"]] if item["text"] else [])]) or "ничего не выбрано"
        lines.append(f"{item['question']} — {reply}" if several else reply)
    return "\n".join(lines)


def _tool_result(entry: _Entry) -> dict[str, Any]:
    question_id = entry.question.id
    if entry.outcome == "answered":
        return {
            "status": "answered",
            "answers": entry.answers,
            "next_step": "Продолжай работу с учётом ответа человека.",
        }
    if entry.outcome == "skipped":
        return {
            "status": "skipped",
            "next_step": "Человек не стал отвечать: прими разумное допущение, явно назови его и продолжай.",
        }
    if entry.outcome == "cancelled":
        return {"status": "cancelled", "next_step": "Вопрос снят: запуск останавливают. Заверши работу."}
    return {
        "status": "waiting",
        "question_id": question_id,
        "next_step": (
            "Человек ещё не ответил. Сразу вызови wait_answer с этим question_id — "
            "больше ничего не делай и ничего не пиши."
        ),
    }


questions = QuestionBoard()

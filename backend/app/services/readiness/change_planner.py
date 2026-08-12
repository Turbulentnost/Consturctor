from __future__ import annotations

import re
from typing import Any

from app.schemas.regulation import (
    ReadinessAnswer,
    ReadinessQuestion,
    RegulationChangeDraft,
    RegulationParseResult,
)
from app.services.role_matching.claudehub_client import _load_json, _post_json


def change_from_answer(
    *,
    change_id: str,
    question: ReadinessQuestion,
    answer: ReadinessAnswer,
    result: RegulationParseResult,
    related_field_answers: dict[str, str] | None = None,
    clarifying_prompt: str = "",
) -> RegulationChangeDraft:
    fragment = _fragment(result, question.affectedBlocks[0] if question.affectedBlocks else "")
    before = fragment.text if fragment is not None else ""
    addition = _addition(
        question,
        answer.answer,
        related_field_answers=related_field_answers or {},
        clarifying_prompt=clarifying_prompt,
        source_text=before,
    )
    after = _merge_text(before, addition)
    return RegulationChangeDraft(
        changeId=change_id,
        source={
            "type": "user_answer",
            "questionId": question.questionId,
            "answerId": answer.answerId,
            "answer": answer.answer,
            "formalized": addition,
        },
        operation="append_to_paragraph" if before else "insert_paragraph_after",
        targetBlockId=fragment.fragmentId if fragment is not None else (question.affectedBlocks[0] if question.affectedBlocks else ""),
        before=before,
        after=after,
        reason=f"Уточнение поля «{question.targetField}»: {question.reason}",
        affectedFunctions=[question.functionId] if question.functionId else [],
        affectedBlocks=question.affectedBlocks,
        requiresApproval=True,
    )


def _addition(
    question: ReadinessQuestion,
    answer: str,
    *,
    related_field_answers: dict[str, str],
    clarifying_prompt: str = "",
    source_text: str = "",
) -> str:
    text = answer.strip().rstrip(".")
    field = question.targetField
    if not text:
        return ""
    if text.casefold() in {"не требуется", "срок не устанавливается"}:
        return f"Для данной функции параметр «{field}» не требуется."
    llm_addition = _llm_addition(
        question=question,
        answer=text,
        source_text=source_text,
        related_field_answers=related_field_answers,
        clarifying_prompt=clarifying_prompt,
    )
    if llm_addition:
        return llm_addition

    builders = {
        "trigger": lambda: f"Выполнение начинается, когда { _strip_leading_when(text)}.",
        "inputs": lambda: f"Для выполнения используются следующие входные данные: {text}.",
        "system": lambda: f"Действие выполняется в системе: {text}.",
        "result": lambda: f"Результат выполнения: {text}.",
        "recipient": lambda: f"Результат передаётся {_role_phrase(text)}.",
        "conditions": lambda: f"Условие выполнения: {text}.",
        "branches": lambda: f"Вариант обработки результата: {text}.",
        "deadline": lambda: f"Срок выполнения: {text}.",
        "errors": lambda: (
            f"Если выполнить действие невозможно, то {_ensure_verb_clause(text)}."
        ),
        "escalation": lambda: _escalation_clause(
            text,
            question=question,
            related_field_answers=related_field_answers,
            clarifying_prompt=clarifying_prompt,
        ),
        "approval": lambda: f"Порядок подтверждения: {text}.",
        "permissions": lambda: f"Используемые права и учётная запись: {text}.",
        "restrictions": lambda: f"Ограничение для агента: {text}.",
        "control": lambda: _control_clause(text),
        "kpi": lambda: f"KPI функции: {text}.",
        "actor": lambda: f"Исполнитель функции: {_role_phrase(text)}.",
        "action": lambda: f"Действие агента: {text}.",
    }
    builder = builders.get(field)
    if builder is None:
        return text if text.endswith(".") else f"{text}."
    return builder()


def _llm_addition(
    *,
    question: ReadinessQuestion,
    answer: str,
    source_text: str,
    related_field_answers: dict[str, str],
    clarifying_prompt: str,
) -> str:
    payload: dict[str, Any] = {
        "instruction": (
            "Сформулируй одну логичную фразу для внесения в регламент. "
            "Фраза должна быть написана деловым языком, без разговорных сокращений, "
            "и должна объединять контекст исходного блока, уточняющий вопрос и ответ пользователя. "
            "Не придумывай новых правил, которых нет в ответе пользователя. "
            "Если ответ описывает условие и адресата эскалации, сформулируй правило вида "
            "«Если ..., то ...». Верни только JSON: {regulationText}."
        ),
        "targetField": question.targetField,
        "question": question.question,
        "reason": question.reason,
        "sourceBlockText": source_text,
        "userAnswer": answer,
        "relatedFieldAnswers": related_field_answers,
        "clarifyingPrompt": clarifying_prompt,
    }
    try:
        data = _load_json(_post_json(payload, timeout=90.0))
    except Exception:
        return ""
    text = str(data.get("regulationText") or "").strip() if isinstance(data, dict) else ""
    if not text:
        return ""
    return text if text.endswith(".") else f"{text}."


def _escalation_clause(
    answer: str,
    *,
    question: ReadinessQuestion,
    related_field_answers: dict[str, str],
    clarifying_prompt: str,
) -> str:
    role = _role_phrase(answer)
    condition = _condition_from_clarifying(clarifying_prompt) or _condition_from_control(
        related_field_answers.get("control", "")
    )
    if not condition:
        # Fallback from the readiness question text itself.
        condition = _condition_from_clarifying(question.question) or (
            "действие не удаётся завершить самостоятельно"
        )
    condition = _normalize_condition(condition, clarifying_prompt or question.question)
    return f"Если {condition}, то проблема передаётся {role}."


def _control_clause(answer: str) -> str:
    text = answer.strip().rstrip(".")
    lowered = text.casefold()
    if lowered.startswith("если "):
        return f"Контроль выполнения: {text}."
    if any(token in lowered for token in ("выполнен", "зафиксир", "эскал", "подтвержд", "проверен")):
        return f"Контроль выполнения считается успешным, если { _lowercase_first(text)}."
    return f"Контроль выполнения: {text}."


def _condition_from_clarifying(prompt: str) -> str | None:
    text = " ".join((prompt or "").split())
    if not text:
        return None
    match = re.search(r"если\s+(.+?)(?:\?|$)", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    condition = match.group(1).strip(" .;:")
    # Drop trailing explanatory tails after the condition.
    condition = re.split(r"\?\s*|Например:", condition, maxsplit=1)[0].strip(" .;:")
    return condition or None


def _condition_from_control(control_answer: str) -> str | None:
    text = " ".join((control_answer or "").split()).strip(" .")
    if not text:
        return None
    lowered = text.casefold()
    if "вех" in lowered:
        return (
            "срок вехи нарушен и руководитель сам не может устранить отклонение"
        )
    if "отклонен" in lowered or "эскал" in lowered:
        return "отклонение не устраняется исполнителем самостоятельно"
    return None


def _normalize_condition(condition: str, prompt: str) -> str:
    text = condition.strip()
    # «он сам» in clarifying questions usually refers to the sector/process manager.
    if re.search(r"\bон сам\b", text, flags=re.IGNORECASE):
        manager = "руководитель"
        if "руководитель сектора" in prompt.casefold():
            manager = "руководитель сектора"
        text = re.sub(r"\bон сам\b", f"{manager} сам", text, flags=re.IGNORECASE)
    # Prefer «устранить» over colloquial mistypes if present in nearby prompt.
    text = text.replace("устраить", "устранить")
    return _lowercase_first(text)


def _role_phrase(answer: str) -> str:
    text = answer.strip().rstrip(".")
    # Already in dative / prepositional style: «куратору проекта», «руководителю»
    if re.search(r"(у|ю|е)$", text.split()[0].casefold()) and " " in text:
        return _lowercase_first(text)
    # Nominative role titles → keep as-is but lowercase for mid-sentence use.
    lowered = _lowercase_first(text)
    # Common short answers like «Куратору проекта» already dative — handled above.
    # «Куратор проекта» → «куратору проекта»
    mapping = {
        "куратор проекта": "куратору проекта",
        "руководитель проекта": "руководителю проекта",
        "руководитель сектора": "руководителю сектора",
        "заказчик": "заказчику",
        "вышестоящий руководитель": "вышестоящему руководителю",
    }
    return mapping.get(lowered.casefold(), lowered)


def _strip_leading_when(text: str) -> str:
    return re.sub(r"^(когда|при|после)\s+", "", text.strip(), flags=re.IGNORECASE)


def _ensure_verb_clause(text: str) -> str:
    lowered = text.casefold()
    if lowered.startswith(("останов", "создать", "повтор", "эскал", "уведом", "переда")):
        return _lowercase_first(text)
    return _lowercase_first(text)


def _lowercase_first(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].casefold() + text[1:]


def _merge_text(before: str, addition: str) -> str:
    before = before.strip()
    addition = addition.strip()
    if not before:
        return addition
    if not addition:
        return before
    sep = "" if before.endswith((".", ";", ":")) else "."
    return f"{before}{sep} {addition}"


def _fragment(result: RegulationParseResult, fragment_id: str):
    for fragment in result.fragments:
        if fragment.fragmentId == fragment_id:
            return fragment
    return None

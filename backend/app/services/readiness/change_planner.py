from __future__ import annotations

from app.schemas.regulation import (
    ReadinessAnswer,
    ReadinessQuestion,
    RegulationChangeDraft,
    RegulationParseResult,
)


def change_from_answer(
    *,
    change_id: str,
    question: ReadinessQuestion,
    answer: ReadinessAnswer,
    result: RegulationParseResult,
) -> RegulationChangeDraft:
    fragment = _fragment(result, question.affectedBlocks[0] if question.affectedBlocks else "")
    before = fragment.text if fragment is not None else ""
    addition = _addition(question, answer.answer)
    after = _merge_text(before, addition)
    return RegulationChangeDraft(
        changeId=change_id,
        source={
            "type": "user_answer",
            "questionId": question.questionId,
            "answerId": answer.answerId,
            "answer": answer.answer,
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


def _addition(question: ReadinessQuestion, answer: str) -> str:
    text = answer.strip().rstrip(".")
    field = question.targetField
    if not text:
        return ""
    if text.casefold() in {"не требуется", "срок не устанавливается"}:
        return f"Для данной функции параметр «{field}» не требуется."
    return {
        "trigger": f"Выполнение начинается: {text}.",
        "inputs": f"Для выполнения используются следующие входные данные: {text}.",
        "system": f"Действие выполняется в системе: {text}.",
        "result": f"Результат выполнения: {text}.",
        "recipient": f"Результат передаётся: {text}.",
        "conditions": f"Условие выполнения: {text}.",
        "branches": f"Вариант обработки результата: {text}.",
        "deadline": f"Срок выполнения: {text}.",
        "errors": f"При невозможности выполнения: {text}.",
        "escalation": f"Проблема передаётся: {text}.",
        "approval": f"Порядок подтверждения: {text}.",
        "permissions": f"Используемые права и учётная запись: {text}.",
        "restrictions": f"Ограничение для агента: {text}.",
        "control": f"Контроль выполнения: {text}.",
        "kpi": f"KPI функции: {text}.",
        "actor": f"Исполнитель функции: {text}.",
        "action": f"Действие агента: {text}.",
    }.get(field, text + ".")


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

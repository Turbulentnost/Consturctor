from __future__ import annotations

from app.schemas.regulation import (
    FunctionReadiness,
    ReadinessField,
    ReadinessQuestion,
    ReadinessSourceEvidence,
)


def build_questions(functions: list[FunctionReadiness]) -> list[ReadinessQuestion]:
    questions: list[ReadinessQuestion] = []
    seen: set[tuple[str, str]] = set()
    for function in functions:
        for field in function.fields:
            if field.status not in {"missing", "ambiguous", "conflict", "inferred"}:
                continue
            if not field.required and field.severity == "optional":
                continue
            key = (field.field, field.reason)
            if key in seen and field.field in {"actor", "system", "permissions", "approval"}:
                continue
            seen.add(key)
            evidence = field.evidence[0] if field.evidence else None
            idx = len(questions) + 1
            questions.append(
                ReadinessQuestion(
                    questionId=f"Q-{idx:03d}",
                    functionId=function.functionId,
                    targetField=field.field,
                    severity=field.severity,
                    question=_question_text(field.field, function.title),
                    reason=field.reason,
                    sourceEvidence=ReadinessSourceEvidence(
                        quote=evidence.quote if evidence else "",
                        blockId=evidence.fragmentId if evidence else function.targetBlockId,
                    ),
                    answerType=_answer_type(field.field),
                    options=_options(field.field),
                    affectedBlocks=[function.targetBlockId] if function.targetBlockId else [],
                )
            )
    return sorted(questions, key=lambda item: _severity_rank(item.severity))


def _question_text(field: ReadinessField, title: str) -> str:
    base = {
        "actor": "Кто должен выполнять эту функцию?",
        "trigger": "Когда и при каком событии начинается выполнение этой функции?",
        "inputs": "Какие документы, записи или параметры нужны на входе?",
        "action": "Что именно должен сделать агент?",
        "system": "В какой системе и какой операцией выполняется действие?",
        "result": "Какой проверяемый результат должен появиться после выполнения?",
        "recipient": "Кому передаётся результат выполнения?",
        "conditions": "При каких условиях выполняется действие?",
        "branches": "Что делать при разных вариантах результата?",
        "deadline": "За какое время должна быть выполнена функция?",
        "errors": "Что делать, если выполнить функцию невозможно?",
        "escalation": "Кому передавать проблему, если агент не может завершить действие?",
        "approval": "Требуется ли подтверждение человека перед выполнением?",
        "permissions": "Какая учётная запись и какие права используются?",
        "restrictions": "Что агенту запрещено делать при выполнении функции?",
        "control": "Как определить, что функция выполнена правильно?",
        "kpi": "Как измеряется качество, срок или результат функции?",
    }[field]
    return f"Для функции «{title}» нужно уточнить: {base}"


def _answer_type(field: ReadinessField) -> str:
    if field == "deadline":
        return "duration"
    if field in {"actor", "recipient", "escalation", "approval"}:
        return "role"
    if field in {"system", "permissions"}:
        return "system"
    return "text"


def _options(field: ReadinessField) -> list[str]:
    if field == "deadline":
        return [
            "в течение 1 рабочего дня",
            "в течение 4 рабочих часов",
            "до конца текущего рабочего дня",
            "срок не устанавливается",
            "указать другой вариант",
            "пока неизвестно",
        ]
    if field == "approval":
        return [
            "подтверждает руководитель",
            "подтверждает владелец процесса",
            "агент выполняет автономно",
            "требуется ручное согласование",
            "пока неизвестно",
        ]
    if field == "errors":
        return [
            "остановить выполнение и уведомить ответственного",
            "создать задачу на ручную обработку",
            "повторить попытку позже",
            "эскалировать руководителю",
            "указать другой вариант",
        ]
    return ["указать ответ", "не требуется", "пока неизвестно"]


def _severity_rank(severity: str) -> int:
    return {"blocking": 0, "important": 1, "optional": 2}.get(severity, 3)

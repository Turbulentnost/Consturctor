from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.regulation import ReadinessField, ReadinessSeverity, RoleFunction


ALL_FIELDS: tuple[ReadinessField, ...] = (
    "actor",
    "trigger",
    "inputs",
    "action",
    "system",
    "result",
    "recipient",
    "conditions",
    "branches",
    "deadline",
    "errors",
    "escalation",
    "approval",
    "permissions",
    "restrictions",
    "control",
    "kpi",
)


@dataclass(frozen=True, slots=True)
class FieldRequirement:
    required: bool
    severity: ReadinessSeverity
    reason: str


def requirement_for(field: ReadinessField, function: RoleFunction, source_text: str) -> FieldRequirement:
    operation_type = classify_operation(function, source_text)
    risky = operation_type in {"data_change", "external_message", "decision"}
    recipient_action = operation_type == "external_message" or bool(function.recipient.strip())

    if field in {"actor", "action", "result", "control"}:
        return FieldRequirement(True, "blocking", _reason(field))
    if field == "trigger":
        return FieldRequirement(True, "blocking", "Без события запуска агент не знает, когда начинать работу")
    if field == "inputs":
        return FieldRequirement(True, "blocking", "Без входных данных агент не сможет выполнить действие проверяемо")
    if field == "system":
        required = operation_type in {"data_change", "lookup", "external_message"}
        return FieldRequirement(required, "blocking" if required else "optional", _reason(field))
    if field == "recipient":
        return FieldRequirement(recipient_action, "blocking" if recipient_action else "optional", _reason(field))
    if field == "errors":
        required = operation_type in {"data_change", "lookup", "external_message"}
        return FieldRequirement(required, "blocking" if required else "important", _reason(field))
    if field == "escalation":
        return FieldRequirement(risky, "important", _reason(field))
    if field == "permissions":
        required = operation_type == "data_change"
        return FieldRequirement(required, "blocking" if required else "optional", _reason(field))
    if field == "approval":
        return FieldRequirement(risky, "blocking" if risky else "optional", _reason(field))
    if field == "deadline":
        required = _has_deadline_signal(source_text)
        return FieldRequirement(required, "important", _reason(field))
    if field in {"branches", "conditions", "restrictions", "kpi"}:
        return FieldRequirement(False, "optional", _reason(field))
    return FieldRequirement(False, "optional", _reason(field))


def classify_operation(function: RoleFunction, source_text: str) -> str:
    text = f"{function.action} {function.object} {source_text}".casefold()
    if re.search(r"\b(вносит|изменяет|обновляет|записывает|созда[её]т|оформляет)\b", text):
        return "data_change"
    if re.search(r"\b(направляет|отправляет|уведомляет|переда[её]т|сообщает)\b", text):
        return "external_message"
    if re.search(r"\b(проверяет|анализирует|сверяет|получает|ищет)\b", text):
        return "lookup"
    if re.search(r"\b(утверждает|согласовывает|принимает решение|подтверждает)\b", text):
        return "decision"
    return "work"


def _has_deadline_signal(text: str) -> bool:
    return bool(re.search(r"\b(срок|день|час|до конца|просроч|не позднее|в течение)\b", text, re.I))


def _reason(field: ReadinessField) -> str:
    return {
        "actor": "Нужно однозначно определить исполнителя функции",
        "trigger": "Нужно определить момент запуска функции",
        "inputs": "Нужно определить документы, записи или параметры на входе",
        "action": "Нужно определить действие агента",
        "system": "Нужно определить систему и операцию",
        "result": "Нужно определить проверяемый результат",
        "recipient": "Нужно определить получателя результата",
        "conditions": "Условия помогают не запускать функцию вне нужного случая",
        "branches": "Ветвления нужны для разных вариантов результата",
        "deadline": "Срок нужен для контроля просрочки",
        "errors": "Нужно определить действие при невозможности выполнения",
        "escalation": "Нужно определить, кому передавать проблему",
        "approval": "Нужно определить, требуется ли подтверждение человека",
        "permissions": "Нужно определить учётную запись и права агента",
        "restrictions": "Нужно явно определить запреты для агента",
        "control": "Нужно определить критерий правильного выполнения",
        "kpi": "KPI помогает измерять качество, срок или результат",
    }[field]

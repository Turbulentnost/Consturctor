"""Тип задачи 1С:Документооборот по шагу процесса и допустимые по нему действия.

Зеркало фронтенда: orchestrator/desktop-electron/src/renderer/src/workplace/docflowTaskKind.ts.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

EXECUTED_POSITIVE = "ExecutedPositive"
EXECUTED_ALMOST_POSITIVE = "ExecutedAlmostPositive"
EXECUTED_NEGATIVE = "ExecutedNegative"

KIND_EXECUTE = "execute"
KIND_CHECK = "check"
KIND_ACQUAINT = "acquaint"
KIND_ACQUAINT_RESULT = "acquaint_result"
KIND_APPROVE = "approve"
KIND_CONFIRM = "confirm"
KIND_CONSIDER = "consider"
KIND_QUESTION = "question"
KIND_RESOLUTION = "resolution"
KIND_OTHER = "other"


@dataclass(frozen=True)
class DocflowAction:
    mark: str
    summary: str
    needs_comment: bool = False


ACTIONS: dict[str, DocflowAction] = {
    "execute": DocflowAction(EXECUTED_POSITIVE, "Задача исполнена"),
    "accept": DocflowAction(EXECUTED_POSITIVE, "Исполнение принято"),
    "return": DocflowAction(EXECUTED_NEGATIVE, "Задача возвращена на доработку", needs_comment=True),
    "acquaint": DocflowAction(EXECUTED_POSITIVE, "Отмечено: ознакомлен"),
    "approve": DocflowAction(EXECUTED_POSITIVE, "Согласовано"),
    "approve_remarks": DocflowAction(
        EXECUTED_ALMOST_POSITIVE, "Согласовано с замечаниями", needs_comment=True
    ),
    "decline": DocflowAction(EXECUTED_NEGATIVE, "Отклонено", needs_comment=True),
    "confirm": DocflowAction(EXECUTED_POSITIVE, "Утверждено"),
    "consider": DocflowAction(EXECUTED_POSITIVE, "Рассмотрено"),
    "close_question": DocflowAction(EXECUTED_POSITIVE, "Вопрос закрыт"),
    "process": DocflowAction(EXECUTED_POSITIVE, "Резолюция обработана"),
    "done": DocflowAction(EXECUTED_POSITIVE, "Задача выполнена"),
}

KIND_ACTIONS: dict[str, tuple[str, ...]] = {
    KIND_EXECUTE: ("execute",),
    KIND_CHECK: ("accept", "return"),
    KIND_ACQUAINT: ("acquaint",),
    KIND_ACQUAINT_RESULT: ("acquaint",),
    KIND_APPROVE: ("approve", "approve_remarks", "decline"),
    KIND_CONFIRM: ("confirm", "decline"),
    KIND_CONSIDER: ("consider",),
    KIND_QUESTION: ("close_question",),
    KIND_RESOLUTION: ("process",),
    KIND_OTHER: ("done",),
}

# Старые имена действий из прежних версий Оркестратора.
LEGACY_ACTIONS = {"reject": "decline"}


def docflow_task_kind(step: str, name: str = "") -> str:
    """Шаг бизнес-процесса (businessProcessStep); имя задачи — запасной вариант."""
    for raw in (step, name):
        text = " ".join(str(raw or "").lower().replace("ё", "е").split())
        if not text:
            continue
        if text.startswith("ознакомиться с результатом") or text.startswith("ознакомиться:"):
            return KIND_ACQUAINT_RESULT
        if "ознаком" in text:
            return KIND_ACQUAINT
        if "проверить" in text or "контрол" in text:
            return KIND_CHECK
        if "согласова" in text:
            return KIND_APPROVE
        if "утверд" in text or "подписа" in text:
            return KIND_CONFIRM
        if "резолюц" in text:
            return KIND_RESOLUTION
        if "вопрос" in text:
            return KIND_QUESTION
        if "рассмотр" in text:
            return KIND_CONSIDER
        if "исполн" in text:
            return KIND_EXECUTE
    return KIND_OTHER


def primary_action(kind: str) -> str:
    return KIND_ACTIONS.get(kind, KIND_ACTIONS[KIND_OTHER])[0]


def resolve_action(action: str, kind: str) -> str:
    """Проверяет, что действие подходит к типу задачи. `close` — основное действие типа."""
    key = LEGACY_ACTIONS.get(action, action)
    if key == "close":
        return primary_action(kind)
    allowed = KIND_ACTIONS.get(kind, KIND_ACTIONS[KIND_OTHER])
    if key in allowed:
        return key
    # Шаг не распознан: разрешаем любое положительное завершение, но не отказ.
    if kind == KIND_OTHER and key in ACTIONS and ACTIONS[key].mark == EXECUTED_POSITIVE:
        return key
    return ""


def web_client_task_url(server: str, port: int, base_path: str, task_id: str) -> str:
    """Навигационная ссылка веб-клиента ДО на карточку задачи исполнителя."""
    parts = str(task_id or "").strip().lower().split("-")
    if len(parts) != 5 or not server:
        return ""
    ref = parts[3] + parts[4] + parts[2] + parts[1] + parts[0]
    base = f"http://{server}:{port}{base_path}".rstrip("/")
    return f"{base}/#e1cib/data/{quote('Задача.ЗадачаИсполнителя')}?ref={ref}"

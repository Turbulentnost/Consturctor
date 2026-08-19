"""Read-only действия 1С для MVP worker-а.

Пока функции возвращают fake/mock данные стабильной структуры. Слой сделан так,
чтобы позже заменить реализацию на HTTP/API 1С без изменения Tool/Runtime.
"""

from __future__ import annotations

from app.tools.ac.workers.onec_errors import (
    OneCDocumentNotFoundError,
    OneCReadOnlyPolicyError,
)

ALLOWED_ONEC_TOOLS = {
    "onec.search_documents",
    "onec.get_document_card",
    "onec.search_tasks",
    "onec.get_task_card",
}

FORBIDDEN_INPUT_KEYS = {
    "write",
    "save",
    "post",
    "delete",
    "conduct",
    "update",
    "create",
    "set_status",
    "execute_code",
    "script",
    "command",
}


def ensure_onec_readonly_tool(tool_name: str) -> None:
    """Проверить, что tool_name разрешён read-only политикой 1С."""
    if tool_name not in ALLOWED_ONEC_TOOLS:
        raise OneCReadOnlyPolicyError(
            f"1С tool {tool_name!r} запрещён read-only политикой"
        )


def ensure_onec_readonly_input(input_data: dict) -> None:
    """Проверить input_data на write-like ключи рекурсивно."""
    forbidden = _find_forbidden_keys(input_data)
    if forbidden:
        raise OneCReadOnlyPolicyError(
            "input_data содержит запрещённые для 1С read-only ключи: "
            + ", ".join(sorted(forbidden))
        )


def search_documents(input_data: dict) -> dict:
    """Найти документы в 1С по read-only критериям."""
    ensure_onec_readonly_input(input_data)
    query = str(input_data.get("query") or "").casefold()
    if any(
        h in query
        for h in (
            "поручен",
            "action tracker",
            "decision log",
            "отслеж",
            "артефакт",
            "статус",
            "smart",
            "формулиров",
            "act00",
            "аст00",
        )
    ):
        raise OneCReadOnlyPolicyError(
            "onec.search_documents — заглушка MVP. Для поручений используйте Action Tracker "
            "(backend → onec.docflow_assignments). Обновите backend и нажмите «Типовая задача»."
        )
    max_results = int(input_data.get("max_results") or 10)
    documents = [
        {
            "ref": "doc-ref-1",
            "type": input_data.get("document_type") or "Служебная записка",
            "number": input_data.get("number") or "123",
            "date": input_data.get("date_from") or "2026-06-26",
            "status": input_data.get("status") or "На согласовании",
            "title": input_data.get("query") or "Заявка на проверку документа",
        }
    ][:max_results]
    return {
        "documents": documents,
        "count": len(documents),
        "source": "onec_readonly",
    }


def get_document_card(input_data: dict) -> dict:
    """Прочитать карточку документа 1С."""
    ensure_onec_readonly_input(input_data)
    document_ref = input_data.get("document_ref")
    if not isinstance(document_ref, str) or not document_ref.strip():
        raise OneCDocumentNotFoundError("document_ref обязателен для чтения документа")

    return {
        "document": {
            "ref": document_ref,
            "type": "Служебная записка",
            "number": "123",
            "date": "2026-06-26",
            "status": "На согласовании",
            "author": "Иванов И.И.",
            "responsible": "Петров П.П.",
            "content_preview": "Документ содержит поручение подготовить аналитическую справку.",
        }
    }


def search_tasks(input_data: dict) -> dict:
    """Найти задачи или поручения в 1С."""
    ensure_onec_readonly_input(input_data)
    max_results = int(input_data.get("max_results") or 10)
    tasks = [
        {
            "ref": "task-ref-1",
            "title": input_data.get("query") or "Подготовить аналитический отчёт",
            "status": input_data.get("status") or "В работе",
            "responsible": input_data.get("responsible") or "Петров П.П.",
            "due_date": input_data.get("date_to") or "2026-06-30",
            "source_document_ref": "doc-ref-1",
        }
    ][:max_results]
    return {
        "tasks": tasks,
        "count": len(tasks),
        "source": "onec_readonly",
    }


def get_task_card(input_data: dict) -> dict:
    """Прочитать карточку задачи или поручения 1С."""
    ensure_onec_readonly_input(input_data)
    task_ref = input_data.get("task_ref")
    if not isinstance(task_ref, str) or not task_ref.strip():
        raise OneCDocumentNotFoundError("task_ref обязателен для чтения задачи")

    return {
        "task": {
            "ref": task_ref,
            "title": "Подготовить аналитический отчёт",
            "description": "Проверить данные из Outlook и 1С, затем подготовить вывод.",
            "status": "В работе",
            "responsible": "Петров П.П.",
            "due_date": "2026-06-30",
            "history": [
                {"date": "2026-06-24", "event": "Создано"},
                {"date": "2026-06-25", "event": "Назначен ответственный"},
            ],
        }
    }


def _find_forbidden_keys(value: object) -> set[str]:
    """Найти запрещённые ключи во вложенной структуре."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).strip().casefold()
            if normalized_key in FORBIDDEN_INPUT_KEYS:
                found.add(normalized_key)
            found.update(_find_forbidden_keys(nested_value))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden_keys(item))
    return found


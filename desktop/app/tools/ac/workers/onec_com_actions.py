"""Защищенный слой для 1C COMConnector."""

from __future__ import annotations

import os
import sys
from typing import Any

from app.tools.ac.workers.models import WorkerResult, WorkerTask
from app.tools.ac.workers.onec_actions import (
    ensure_onec_readonly_input,
    ensure_onec_readonly_tool,
)
from app.tools.ac.workers.onec_errors import OneCConnectionError

FORBIDDEN_COM_METHOD_PARTS = (
    "write",
    "записать",
    "post",
    "провести",
    "delete",
    "удалить",
    "set_status",
)

DEFAULT_COM_PROGID = "V83.COMConnector"
ENV_COM_PROGID = "ONEC_COM_PROGID"
ENV_CONNECTION_STRING = "ONEC_COM_CONNECTION_STRING"
ENV_SERVER = "ONEC_COM_SERVER"
ENV_REF = "ONEC_COM_REF"
ENV_LOGIN = "ERP_LOGIN"
ENV_PASSWORD = "ERP_PASSWORD"
ENV_SEARCH_METHOD = "ONEC_COM_SEARCH_METHOD"
ENV_GET_DOCUMENT_CARD_METHOD = "ONEC_COM_GET_DOCUMENT_CARD_METHOD"
ENV_SEARCH_TASKS_METHOD = "ONEC_COM_SEARCH_TASKS_METHOD"
ENV_GET_TASK_CARD_METHOD = "ONEC_COM_GET_TASK_CARD_METHOD"


def execute_onec_com_readonly(task: WorkerTask) -> WorkerResult:
    """Выполнить read-only задачу 1С через COMConnector."""
    try:
        ensure_onec_readonly_tool(task.tool_name)
        ensure_onec_readonly_input(task.input_data)
    except Exception as exc:
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="ONEC_READONLY_POLICY_ERROR",
            error_message=str(exc),
        )

    if sys.platform != "win32":
        return _com_not_available(task, "1C COMConnector доступен только на Windows")

    try:
        session = _connect_session()
        output_data = _dispatch_tool(session, task)
    except ImportError as exc:
        return _com_not_available(task, f"pywin32 недоступен: {exc}")
    except OneCConnectionError as exc:
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="ONEC_CONNECTION_ERROR",
            error_message=str(exc),
        )
    except Exception as exc:
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="ONEC_WORKER_ERROR",
            error_message=str(exc),
        )

    return WorkerResult(task_id=task.task_id, ok=True, output_data=output_data)


def ensure_no_write_like_method(method_name: str) -> None:
    """Запретить write-like методы COMConnector."""
    normalized = method_name.strip().casefold()
    if any(part in normalized for part in FORBIDDEN_COM_METHOD_PARTS):
        raise ValueError(f"Метод {method_name!r} запрещён read-only политикой 1С")


def _load_pywin32_modules() -> tuple[Any, Any]:
    """Импортировать pythoncom / win32com.client только внутри worker-а."""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    return pythoncom, win32com.client


def _connect_session() -> Any:
    """Подключиться к 1С через COMConnector."""
    _, win32com_client = _load_pywin32_modules()
    progid = os.environ.get(ENV_COM_PROGID, DEFAULT_COM_PROGID).strip() or DEFAULT_COM_PROGID
    connection_string = _connection_string()
    if not connection_string:
        raise OneCConnectionError(
            "Не заданы параметры подключения к 1С COMConnector. "
            f"Укажите {ENV_CONNECTION_STRING} или {ENV_SERVER}/{ENV_REF}."
        )
    try:
        connector = win32com_client.Dispatch(progid)
    except Exception as exc:  # noqa: BLE001
        raise OneCConnectionError(
            f"Не удалось создать COMConnector {progid!r}: {exc}"
        ) from exc
    try:
        return connector.Connect(connection_string)
    except Exception as exc:  # noqa: BLE001
        raise OneCConnectionError(
            f"Не удалось подключиться к 1С через COMConnector: {exc}"
        ) from exc


def _connection_string() -> str:
    """Собрать connection string из env."""
    explicit = os.environ.get(ENV_CONNECTION_STRING, "").strip()
    if explicit:
        return explicit
    server = os.environ.get(ENV_SERVER, "").strip()
    ref = os.environ.get(ENV_REF, "").strip()
    if not server or not ref:
        return ""
    parts = [f"Srvr={server}", f"Ref={ref}"]
    login = os.environ.get(ENV_LOGIN, "").strip()
    password = os.environ.get(ENV_PASSWORD, "").strip()
    if login and password:
        parts.append(f"Usr={login}")
        parts.append(f"Pwd={password}")
    return ";".join(parts) + ";"


def _dispatch_tool(session: Any, task: WorkerTask) -> dict[str, Any]:
    """Маршрутизировать read-only tool_name к COM-методу."""
    if task.tool_name == "onec.search_documents":
        method_name = _method_name(ENV_SEARCH_METHOD, "SearchDocuments")
        raw = _invoke_method(session, method_name, task.input_data)
        documents = _normalize_collection(raw, "documents")
        return {
            "documents": documents,
            "count": len(documents),
            "source": "onec_com",
            "method": method_name,
        }
    if task.tool_name == "onec.get_document_card":
        method_name = _method_name(
            ENV_GET_DOCUMENT_CARD_METHOD,
            "GetDocumentCard",
        )
        raw = _invoke_method(session, method_name, task.input_data)
        document = _normalize_single_record(raw, preferred_key="document")
        return {
            "document": document,
            "source": "onec_com",
            "method": method_name,
        }
    if task.tool_name == "onec.search_tasks":
        method_name = _method_name(ENV_SEARCH_TASKS_METHOD, "SearchTasks")
        raw = _invoke_method(session, method_name, task.input_data)
        tasks = _normalize_collection(raw, "tasks")
        return {
            "tasks": tasks,
            "count": len(tasks),
            "source": "onec_com",
            "method": method_name,
        }
    if task.tool_name == "onec.get_task_card":
        method_name = _method_name(ENV_GET_TASK_CARD_METHOD, "GetTaskCard")
        raw = _invoke_method(session, method_name, task.input_data)
        task_record = _normalize_single_record(raw, preferred_key="task")
        return {
            "task": task_record,
            "source": "onec_com",
            "method": method_name,
        }
    raise OneCConnectionError(f"Неизвестный COM tool_name: {task.tool_name}")


def _method_name(env_key: str, default: str) -> str:
    """Получить имя COM-метода из env с безопасным default."""
    method_name = os.environ.get(env_key, default).strip() or default
    ensure_no_write_like_method(method_name)
    return method_name


def _invoke_method(session: Any, method_name: str, input_data: dict[str, Any]) -> Any:
    """Позвать COM-метод несколькими безопасными способами."""
    method = getattr(session, method_name, None)
    if method is None:
        raise OneCConnectionError(f"В COM-сессии нет метода {method_name!r}")

    payload = dict(input_data or {})
    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    if payload:
        attempts.append(((payload,), {}))
        attempts.append(((), payload))
        ordered = tuple(
            payload[key]
            for key in ("query", "document_ref", "task_ref", "number")
            if key in payload
        )
        if ordered:
            attempts.append((ordered, {}))
    attempts.append(((), {}))

    last_error: Exception | None = None
    for args, kwargs in attempts:
        try:
            return method(*args, **kwargs)
        except TypeError as exc:
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise OneCConnectionError(
        f"Не удалось вызвать COM-метод {method_name!r}: {last_error}"
    ) from last_error


def _normalize_collection(raw: Any, preferred_key: str) -> list[dict[str, Any]]:
    """Привести ответ поиска документов/задач к стабильному виду."""
    items = _extract_collection(raw, preferred_key)
    collection = [_normalize_record(item) for item in items]
    if not collection and raw is not None:
        collection.append(_normalize_record(raw))
    return collection


def _normalize_single_record(raw: Any, *, preferred_key: str) -> dict[str, Any]:
    """Достать одну карточку документа/задачи из COM-ответа."""
    if isinstance(raw, dict):
        nested = raw.get(preferred_key)
        if isinstance(nested, dict):
            return _normalize_record(nested)
        if nested is not None and not isinstance(nested, (list, tuple)):
            return {"value": _normalize_value(nested)}
        if raw:
            return _normalize_record(raw)
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            return _normalize_record(first)
        return {"value": _normalize_value(first)}
    return _normalize_record(raw)


def _extract_collection(raw: Any, preferred_key: str) -> list[Any]:
    """Достать список записей из COM-ответа."""
    if isinstance(raw, dict):
        for key in (preferred_key, "documents", "tasks", "items", "rows", "value", "result"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
        nested = raw.get(preferred_key)
        if nested is not None and not isinstance(nested, (dict, list, tuple)):
            return [nested]
    if isinstance(raw, list):
        return raw
    if isinstance(raw, tuple):
        return list(raw)
    return []


def _normalize_record(value: Any) -> dict[str, Any]:
    """Преобразовать COM-объект в обычный dict."""
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return {"items": [_normalize_value(item) for item in value]}
    if isinstance(value, tuple):
        return {"items": [_normalize_value(item) for item in value]}
    if value is None:
        return {}
    return {"value": _normalize_value(value)}


def _normalize_value(value: Any) -> Any:
    """Рекурсивно привести значение COM к JSON-friendly виду."""
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _com_not_available(task: WorkerTask, message: str) -> WorkerResult:
    """Вернуть COM_NOT_AVAILABLE."""
    return WorkerResult(
        task_id=task.task_id,
        ok=False,
        error_type="COM_NOT_AVAILABLE",
        error_message=message,
    )


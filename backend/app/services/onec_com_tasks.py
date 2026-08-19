"""Поручения через 1C COM (platform-tool-onec-com :7831) — fallback если ERP SQL недоступен."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx


def onec_com_url() -> str:
    urls = _com_base_urls()
    return urls[0] if urls else "http://host.docker.internal:7831"


def _com_base_urls() -> list[str]:
    urls: list[str] = []
    raw = (os.environ.get("TOOL_ONEC_COM_URL") or "").strip()
    if raw:
        urls.append(raw.rstrip("/"))
    in_docker = os.path.isfile("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "1"
    if in_docker:
        for candidate in ("http://host.docker.internal:7831",):
            if candidate not in urls:
                urls.append(candidate)
    else:
        for candidate in ("http://127.0.0.1:7831", "http://host.docker.internal:7831"):
            if candidate not in urls:
                urls.append(candidate)
    return urls


def com_health(*, timeout_s: float = 8.0) -> dict[str, Any]:
    """Проверка доступности platform-tool-onec-com (:7831)."""
    last_error = ""
    for base in _com_base_urls():
        try:
            with httpx.Client(timeout=timeout_s) as client:
                response = client.get(f"{base}/health")
            if response.status_code == 200:
                return {"ok": True, "url": base}
            last_error = f"HTTP {response.status_code} от {base}"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{base}: {exc}"
    return {
        "ok": False,
        "error": last_error or "COM-сервис недоступен",
        "hint": "Запустите scripts\\restart_onec_com_service.cmd (Windows, 32-bit Python :7831)",
    }


def _normalize_due(raw: str) -> str:
    text = (raw or "").strip()
    if not text or text.startswith("0100-"):
        return ""
    return text.replace("T", " ")[:19]


def _map_com_tasks(payload: dict[str, Any], *, fio: str = "") -> dict[str, Any]:
    rows = list(payload.get("tasks") or [])
    tasks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tasks.append(
            {
                "number": str(row.get("number") or ""),
                "title": str(row.get("description") or row.get("title") or "").strip(),
                "performer": str(row.get("executor") or row.get("performer") or ""),
                "status": str(row.get("status") or "Открыта"),
                "due_at": _normalize_due(str(row.get("due_date") or row.get("due_at") or "")),
            }
        )
    actor = str(payload.get("current_user") or fio or "")
    return {
        "summary": str(payload.get("summary") or f"COM: {len(tasks)} поручений"),
        "fio": actor or fio,
        "user_id": "",
        "count": len(tasks),
        "tasks": tasks,
        "source": "onec-com",
    }


def _invoke_com_tool(tool: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    body = {"run_id": str(uuid4()), "payload": payload}
    last_error = ""
    for base in _com_base_urls():
        url = f"{base}/api/v1/tools/{tool}/invoke"
        try:
            with httpx.Client(timeout=180.0) as client:
                response = client.post(url, json=body)
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code} ({base})"
                continue
            envelope = response.json()
            if not envelope.get("ok"):
                last_error = str(envelope.get("error") or f"COM {tool} вернул ok=false")
                continue
            data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
            if str(data.get("source") or "") == "stub":
                last_error = "COM stub (USE_STUBS=true)"
                continue
            return data
        except Exception as exc:  # noqa: BLE001
            last_error = f"{base}: {exc}"
    global _last_com_invoke_error
    _last_com_invoke_error = last_error
    return None


_last_com_invoke_error = ""


def last_com_error() -> str:
    return _last_com_invoke_error


def fetch_docflow_assignments_com(*, fio: str = "", limit: int = 100) -> dict[str, Any] | None:
    data = fetch_work_items_com(fio=fio, scope="docflow", limit=limit, only_open=True)
    if not data:
        data = _invoke_com_tool(
            "onec.com.query_docflow_assignments",
            {"fio": fio, "limit": int(limit), "only_open": True},
        )
    if not data:
        return None
    rows = list(data.get("tasks") or [])
    actor = str(data.get("fio") or data.get("current_user") or fio or "")
    tasks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("description") or "").strip()
        tasks.append(
            {
                "number": str(row.get("number") or ""),
                "title": title,
                "description": title,
                "performer": str(row.get("performer") or row.get("executor") or ""),
                "author": str(row.get("author") or ""),
                "meeting_topic": str(row.get("meeting_topic") or ""),
                "status": str(row.get("status") or "открыта"),
                "due_at": _normalize_due(str(row.get("due_at") or row.get("due_date") or "")),
                "created_at": _normalize_due(str(row.get("date") or "")),
                "source": str(row.get("source") or "td-docflow"),
            }
        )
    return {
        "summary": str(data.get("summary") or f"Поручения (ТД): {len(tasks)}"),
        "fio": actor,
        "user_id": "",
        "count": len(tasks),
        "tasks": tasks,
        "source": "td-docflow",
    }


def fetch_current_tasks_com(*, fio: str = "", limit: int = 100) -> dict[str, Any] | None:
    data = fetch_work_items_com(fio=fio, scope="erp_tasks", limit=limit, only_open=True)
    if data:
        return data
    data = _invoke_com_tool(
        "onec.com.query_tasks",
        {"mine_only": True, "limit": int(limit), "prefer_crm": False},
    )
    if not data:
        return None
    return _map_com_tasks(data, fio=fio)


def fetch_work_items_com(
    *,
    fio: str = "",
    scope: str = "all",
    limit: int = 100,
    only_open: bool = True,
) -> dict[str, Any] | None:
    data = _invoke_com_tool(
        "onec.com.query_work_items",
        {
            "fio": fio,
            "scope": scope,
            "limit": int(limit),
            "only_open": only_open,
        },
    )
    if not data:
        return None
    rows = list(data.get("tasks") or [])
    actor = str(data.get("fio") or data.get("current_user") or fio or "")
    tasks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("description") or "").strip()
        tasks.append(
            {
                "number": str(row.get("number") or ""),
                "title": title,
                "description": title,
                "performer": str(row.get("performer") or row.get("executor") or ""),
                "author": str(row.get("author") or ""),
                "meeting_topic": str(row.get("meeting_topic") or ""),
                "about": str(row.get("about") or ""),
                "priority": str(row.get("priority") or ""),
                "status": str(row.get("status") or "открыта"),
                "due_at": _normalize_due(str(row.get("due_at") or row.get("due_date") or "")),
                "created_at": _normalize_due(str(row.get("date") or "")),
                "source": str(row.get("source") or scope),
            }
        )
    return {
        "summary": str(data.get("summary") or f"COM work items ({scope}): {len(tasks)}"),
        "fio": actor,
        "user_id": "",
        "count": len(tasks),
        "tasks": tasks,
        "sources": list(data.get("sources") or []),
        "available_sources": list(data.get("available_sources") or []),
        "source": "onec-com",
        "scope": str(data.get("scope") or scope),
    }


def execute_com_query(
    *,
    query_text: str,
    parameters: dict[str, Any] | None = None,
    limit: int = 200,
) -> dict[str, Any] | None:
    return _invoke_com_tool(
        "onec.com.execute_query",
        {
            "query_text": query_text,
            "parameters": parameters or {},
            "limit": int(limit),
        },
    )


def search_com_metadata(
    *,
    pattern: str = "",
    kinds: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {"pattern": pattern, "limit": int(limit)}
    if kinds:
        payload["kinds"] = kinds
    return _invoke_com_tool("onec.com.metadata_search", payload)


def list_com_assignment_sources() -> dict[str, Any] | None:
    return _invoke_com_tool("onec.com.list_assignment_sources", {})


def fetch_erp_assignments_with_artifacts_com(*, limit: int = 100) -> dict[str, Any] | None:
    from datetime import date, timedelta

    today = date.today()
    data = _invoke_com_tool(
        "onec.com.query_assignments",
        {
            "date_from": (today - timedelta(days=365)).isoformat(),
            "date_to": (today + timedelta(days=1)).isoformat(),
            "mine_only": True,
            "limit": int(limit),
        },
    )
    if not data:
        return None
    rows = list(data.get("assignments") or [])
    tasks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("description") or row.get("title") or "").strip()
        done = str(row.get("done") or "").strip()
        status = "выполнена" if done.lower() in {"да", "true", "1"} else "открыта"
        tasks.append(
            {
                "number": str(row.get("number") or ""),
                "title": title,
                "description": title,
                "performer": str(row.get("executor") or row.get("performer") or ""),
                "status": status,
                "due_at": _normalize_due(str(row.get("due_date") or row.get("due_at") or "")),
                "result_text": str(row.get("result") or ""),
                "attachments": list(row.get("attachments") or []),
                "source": "erp_задача_исполнителя",
            }
        )
    return {"tasks": tasks}


def enrich_tasks_with_erp_artifacts(
    tasks: list[dict[str, Any]],
    *,
    fio: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    _ = fio
    payload = fetch_erp_assignments_with_artifacts_com(limit=limit)
    erp_tasks = list((payload or {}).get("tasks") or [])
    if not erp_tasks:
        return tasks

    by_number: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    for row in erp_tasks:
        number = str(row.get("number") or "").strip()
        title_key = str(row.get("title") or "").casefold()[:100]
        if number:
            by_number[number] = row
        if title_key:
            by_title[title_key] = row

    enriched: list[dict[str, Any]] = []
    for task in tasks:
        item = dict(task)
        number = str(item.get("number") or "").strip()
        title_key = str(item.get("title") or "").casefold()[:100]
        match = by_number.get(number) or by_title.get(title_key)
        if match:
            if match.get("attachments"):
                item["attachments"] = list(match.get("attachments") or [])
            if match.get("result_text"):
                item["result_text"] = match.get("result_text")
            if not item.get("status") and match.get("status"):
                item["status"] = match.get("status")
        enriched.append(item)
    return enriched

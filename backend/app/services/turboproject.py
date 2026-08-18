"""Проекты TurboProject (MPP + синхронизация с 1С). Только сервер."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.config import settings

TOOL_NAME = "turboproject"

TOOL_DESCRIPTION = (
    "Проекты TurboProject, у которых есть синхронизация с 1С "
    "(`has_1c = true`). Источник: API `/api/projects/files` и карточка файла. "
    "Исполняется на сервере Constructor; учётка уже в backend/.env, "
    "не спрашивай логин и не ходи в API напрямую.\n"
    "Возвращает:\n"
    "- total_projects — сколько файлов вернул список;\n"
    "- projects_with_1c_count — сколько из них с 1С;\n"
    "- generated_at — время сборки;\n"
    "- projects[] — проекты с 1С.\n"
    "Поля проекта: file_id, original_name, uploaded_at, project_name; "
    "dates.start_date / finish_date / actual_finish_date / baseline_start / "
    "baseline_finish / plan_finish_1c; "
    "task_stats.total_tasks / non_summary_tasks / completed_tasks / "
    "overdue_tasks_count / overdue_milestones_count; "
    "overdue_tasks[] (id, uid, name, start_date, finish_date, percent_complete, executors); "
    "overdue_milestones[] (id, uid, name, start_date, finish_date, percent_complete); "
    "resources — уникальные ФИО; "
    "data_1c — блок 1С: one_c_ref_key, nomer_proekta, status_proekta, tip_proekta, "
    "byudzhet_plan, byudzhet_fakt, data_nachala, data_okonchaniya, "
    "planovaya_data_nachala, planovaya_data_okonchaniya, rukovodstvo_proektom, "
    "osnovanie_zapuska, kolichestvo_perenosov, vkhodit_v_portfel, yavlyaetsya_portfelem, "
    "rukovoditel, kurator, zakazchik, investor, zam_rp, istochnik_finansirovaniya, "
    "podrazdelenie, organizatsiya, tseli_proekta, chek_list, resheniya, "
    "perenosy_proekta, synced_at.\n"
    "Фильтры: query (имя), manager (руководитель 1С), file_id, overdue_only, limit."
)

_TOKEN_TTL_SEC = 1500.0
_token = ""
_token_at = 0.0


class TurboProjectError(RuntimeError):
    pass


def turboproject_configured() -> bool:
    return bool(
        settings.turboproject_api_base.strip()
        and settings.turboproject_email.strip()
        and settings.turboproject_password.strip()
    )


def parse_iso_date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def unique_resource_names(names: list[Any]) -> list[str]:
    resources_by_key: dict[str, str] = {}
    for name in names:
        if not isinstance(name, str):
            continue
        normalized = name.strip()
        if not normalized:
            continue
        resources_by_key.setdefault(normalized.lower(), normalized)
    return sorted(resources_by_key.values(), key=str.lower)


def build_project_resources(details: dict[str, Any]) -> list[str]:
    resources = details.get("resources") or []
    if resources:
        return unique_resource_names(resources)
    assignment_resource_names = []
    for task in details.get("tasks") or []:
        for assignment in task.get("assignments") or []:
            assignment_resource_names.append(assignment.get("resource_name"))
    return unique_resource_names(assignment_resource_names)


def _is_complete(value: Any) -> bool:
    try:
        percent = float(value or 0.0)
    except (TypeError, ValueError):
        return False
    return percent >= 1.0


def build_overdue_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = datetime.now().date()
    overdue = []
    for task in tasks:
        if task.get("is_summary"):
            continue
        percent_complete = float(task.get("percent_complete") or 0.0)
        if _is_complete(percent_complete):
            continue
        finish_dt = parse_iso_date(task.get("finish_date"))
        if finish_dt is None or finish_dt.date() >= today:
            continue
        overdue.append(
            {
                "id": task.get("id"),
                "uid": task.get("uid"),
                "name": task.get("name"),
                "start_date": iso_or_none(task.get("start_date")),
                "finish_date": iso_or_none(task.get("finish_date")),
                "percent_complete": percent_complete,
                "executors": [
                    item.get("resource_name")
                    for item in (task.get("assignments") or [])
                    if item.get("resource_name")
                ],
            }
        )
    overdue.sort(key=lambda item: (item.get("finish_date") or "", item.get("name") or ""))
    return overdue


def build_overdue_milestones(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = datetime.now().date()
    overdue = []
    for task in tasks:
        if not task.get("is_milestone"):
            continue
        percent_complete = float(task.get("percent_complete") or 0.0)
        if _is_complete(percent_complete):
            continue
        finish_dt = parse_iso_date(task.get("finish_date"))
        if finish_dt is None or finish_dt.date() >= today:
            continue
        overdue.append(
            {
                "id": task.get("id"),
                "uid": task.get("uid"),
                "name": task.get("name"),
                "start_date": iso_or_none(task.get("start_date")),
                "finish_date": iso_or_none(task.get("finish_date")),
                "percent_complete": percent_complete,
            }
        )
    overdue.sort(key=lambda item: (item.get("finish_date") or "", item.get("name") or ""))
    return overdue


def build_project_payload(summary_item: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    project_meta = details.get("project") or {}
    tasks = details.get("tasks") or []
    overdue_tasks = build_overdue_tasks(tasks)
    overdue_milestones = build_overdue_milestones(tasks)
    non_summary_tasks = [task for task in tasks if not task.get("is_summary")]
    completed_tasks = [task for task in non_summary_tasks if _is_complete(task.get("percent_complete"))]
    return {
        "file_id": summary_item.get("id"),
        "original_name": summary_item.get("original_name"),
        "uploaded_at": iso_or_none(summary_item.get("uploaded_at")),
        "project_name": (project_meta or {}).get("name") or summary_item.get("original_name"),
        "dates": {
            "start_date": iso_or_none(project_meta.get("start_date")),
            "finish_date": iso_or_none(project_meta.get("finish_date")),
            "actual_finish_date": iso_or_none(project_meta.get("actual_finish_date")),
            "baseline_start": iso_or_none(project_meta.get("baseline_start")),
            "baseline_finish": iso_or_none(project_meta.get("baseline_finish")),
            "plan_finish_1c": iso_or_none(project_meta.get("plan_finish_1c")),
        },
        "task_stats": {
            "total_tasks": len(tasks),
            "non_summary_tasks": len(non_summary_tasks),
            "completed_tasks": len(completed_tasks),
            "overdue_tasks_count": len(overdue_tasks),
            "overdue_milestones_count": len(overdue_milestones),
        },
        "overdue_tasks": overdue_tasks,
        "overdue_milestones": overdue_milestones,
        "resources": build_project_resources(details),
        "data_1c": details.get("data_1c"),
    }


def _base_url() -> str:
    return settings.turboproject_api_base.strip().rstrip("/")


def _login(*, force: bool = False) -> str:
    global _token, _token_at
    now = time.monotonic()
    if not force and _token and now - _token_at < _TOKEN_TTL_SEC:
        return _token
    url = f"{_base_url()}/api/auth/login"
    try:
        with httpx.Client(timeout=settings.turboproject_timeout_sec) as client:
            response = client.post(
                url,
                json={
                    "email": settings.turboproject_email.strip(),
                    "password": settings.turboproject_password,
                },
            )
            response.raise_for_status()
            token = str(response.json().get("token") or "").strip()
    except httpx.HTTPError as exc:
        raise TurboProjectError(f"TurboProject: не удалось войти: {exc}") from exc
    if not token:
        raise TurboProjectError("TurboProject: в ответе login нет token")
    _token = token
    _token_at = now
    return token


def _api_get(path: str, token: str, *, retry: bool = True) -> Any:
    url = f"{_base_url()}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=settings.turboproject_timeout_sec) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise TurboProjectError(f"TurboProject GET {path}: {exc}") from exc
    if response.status_code == 401 and retry:
        return _api_get(path, _login(force=True), retry=False)
    if response.status_code >= 400:
        text = response.text[:280].replace("\n", " ")
        raise TurboProjectError(f"TurboProject HTTP {response.status_code} {path}: {text}")
    data = response.json()
    return data


def _matches_query(item: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    needle = query.casefold()
    hay = " ".join(
        str(part or "")
        for part in (
            item.get("project_name"),
            item.get("original_name"),
            ((item.get("data_1c") or {}) if isinstance(item.get("data_1c"), dict) else {}).get(
                "nomer_proekta"
            ),
        )
    ).casefold()
    return needle in hay


def _matches_manager(item: dict[str, Any], manager: str) -> bool:
    if not manager:
        return True
    data = item.get("data_1c") if isinstance(item.get("data_1c"), dict) else {}
    return manager.casefold() in str(data.get("rukovoditel") or "").casefold()


def list_projects(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    query = str(payload.get("query") or payload.get("project_name") or "").strip()
    manager = str(payload.get("manager") or payload.get("rukovoditel") or "").strip()
    file_id = payload.get("file_id") or payload.get("fileId")
    overdue_only = bool(payload.get("overdue_only") or payload.get("overdueOnly"))
    raw_limit = payload.get("limit")
    # Без limit агент на планировании тянет все ~200 карточек по одной — UI «зависает».
    limit = int(raw_limit) if raw_limit not in (None, "") else 20
    if limit <= 0:
        limit = 20
    limit = min(limit, 200)

    token = _login()
    if file_id:
        details = _api_get(f"/api/projects/files/{file_id}", token)
        summary = {
            "id": file_id,
            "original_name": (details.get("file") or {}).get("original_name")
            or (details.get("project") or {}).get("name"),
            "uploaded_at": (details.get("file") or {}).get("uploaded_at"),
            "has_1c": bool(details.get("data_1c")),
        }
        items = [summary]
        projects = [build_project_payload(summary, details)]
        if query and not _matches_query(projects[0], query):
            projects = []
        if manager and not _matches_manager(projects[0] if projects else {}, manager):
            projects = []
        if overdue_only:
            projects = [
                item
                for item in projects
                if item["task_stats"]["overdue_tasks_count"]
                or item["task_stats"]["overdue_milestones_count"]
            ]
        return {
            "summary": f"TurboProject: {len(projects)} проект(ов)",
            "total_projects": 1,
            "projects_with_1c_count": 1 if summary.get("has_1c") else 0,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "projects": projects,
            "source": "turboproject",
        }

    summary = _api_get("/api/projects/files", token)
    items = summary.get("items") or []
    with_1c = [item for item in items if item.get("has_1c")]
    projects: list[dict[str, Any]] = []
    for item in with_1c:
        current_id = item.get("id")
        if not current_id:
            continue
        details = _api_get(f"/api/projects/files/{current_id}", token)
        project = build_project_payload(item, details)
        if query and not _matches_query(project, query):
            continue
        if manager and not _matches_manager(project, manager):
            continue
        if overdue_only and not (
            project["task_stats"]["overdue_tasks_count"]
            or project["task_stats"]["overdue_milestones_count"]
        ):
            continue
        projects.append(project)
        if limit and len(projects) >= limit:
            break
    return {
        "summary": f"TurboProject: {len(projects)} проект(ов) с 1С из {len(items)}",
        "total_projects": len(items),
        "projects_with_1c_count": len(with_1c),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "projects": projects,
        "source": "turboproject",
    }


def stub_projects(args: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = args
    return {
        "summary": "stub: проекты TurboProject",
        "total_projects": 0,
        "projects_with_1c_count": 0,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "projects": [],
        "source": "stub",
    }


def invoke_turboproject(tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if tool not in {TOOL_NAME, "turboproject.projects"}:
        raise TurboProjectError(f"Неизвестный инструмент TurboProject: {tool}")
    args = arguments if isinstance(arguments, dict) else {}
    if not turboproject_configured():
        return stub_projects(args)
    try:
        return list_projects(args)
    except TurboProjectError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TurboProjectError(str(exc)) from exc

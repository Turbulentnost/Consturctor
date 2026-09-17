"""Проекты TurboProject (MPP + синхронизация с 1С). Только сервер."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable

import httpx

from app.config import settings

TOOL_NAME = "turboproject"
LIST_TOOL_NAME = "turboproject.list"
GET_TOOL_NAME = "turboproject.get"
SEARCH_PROJECTS_TOOL_NAME = "turboproject.search_projects"
GET_PROJECT_TOOL_NAME = "turboproject.get_project"
GET_PROJECT_TASKS_TOOL_NAME = "turboproject.get_project_tasks"
GET_PROJECT_METRICS_TOOL_NAME = "turboproject.get_project_metrics"
GET_OVERDUE_PROJECTS_TOOL_NAME = "turboproject.get_overdue_projects"
GET_BLOCKED_TASKS_TOOL_NAME = "turboproject.get_projects_with_blocked_tasks"
GET_WORKLOAD_SUMMARY_TOOL_NAME = "turboproject.get_workload_summary"
GET_PORTFOLIO_SUMMARY_TOOL_NAME = "turboproject.get_project_portfolio_summary"
GET_USER_PORTFOLIO_TOOL_NAME = "turboproject.get_user_portfolio"

TURBOPROJECT_TOOLS = frozenset(
    {
        TOOL_NAME,
        "turboproject.projects",
        LIST_TOOL_NAME,
        GET_TOOL_NAME,
        SEARCH_PROJECTS_TOOL_NAME,
        GET_PROJECT_TOOL_NAME,
        GET_PROJECT_TASKS_TOOL_NAME,
        GET_PROJECT_METRICS_TOOL_NAME,
        GET_OVERDUE_PROJECTS_TOOL_NAME,
        GET_BLOCKED_TASKS_TOOL_NAME,
        GET_WORKLOAD_SUMMARY_TOOL_NAME,
        GET_PORTFOLIO_SUMMARY_TOOL_NAME,
        GET_USER_PORTFOLIO_TOOL_NAME,
    }
)

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
    "Фильтры: query (только название / имя MPP / номер 1С, не фраза), "
    "manager (одно ФИО руководителя 1С), file_id, overdue_only, limit."
)

_PHRASE_QUERY_HINTS = (
    "участник",
    "активн",
    "все проекты",
    "мои проекты",
    "руководител",
    "сотрудник",
)

_TOKEN_TTL_SEC = 1500.0
_DEFAULT_PROJECT_LIMIT = 5
_DEFAULT_SEARCH_LIMIT = 25
_MAX_SEARCH_LIMIT = 50
_MAX_ANALYTICS_SCAN = 200
# Default equals the max: the wall-clock budget below is the real guard, and a
# warm card cache lets a re-run cover the rest of the portfolio cheaply.
_DEFAULT_ANALYTICS_SCAN = _MAX_ANALYTICS_SCAN
# Aggregators are id-scoped by contract: they read only the cards the caller
# selected in search_projects (project_ids) or a narrow filter. Without either
# they refuse instead of scanning the whole portfolio, so no hidden 30s scan.
_DEFAULT_AGG_SCAN = 25
_AGG_NARROW_KEYS = (
    "query",
    "project_name",
    "manager",
    "rukovoditel",
    "owner",
    "owner_id",
    "status",
    "status_proekta",
    "department",
    "department_id",
    "podrazdelenie",
    "date_from",
    "from",
    "date_to",
    "to",
    "employee",
    "fio",
    "user",
)
_ANALYTICS_CONCURRENCY = 12
_ANALYTICS_TIME_BUDGET_SEC = 30.0
_MAX_PROJECT_IDS = 20
_MAX_USER_PORTFOLIO = 500
_MAX_OVERDUE_ITEMS = 8
_MAX_RESOURCES = 20
_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()
_client: httpx.Client | None = None
_client_lock = threading.Lock()
_CARD_TTL_SEC = 300.0
_INDEX_TTL_SEC = 120.0
_card_cache: dict[str, tuple[float, Any]] = {}
_card_cache_lock = threading.Lock()
_index_cache_by_key: dict[str, tuple[float, Any]] = {}
_index_cache_lock = threading.Lock()


class TurboProjectError(RuntimeError):
    pass


_TURBO_DON_DOMAIN = "turbo-don.ru"


def turboproject_configured() -> bool:
    return bool(settings.turboproject_api_base.strip())


def _turbo_email_from_slug(slug: str) -> str:
    raw = (slug or "").strip().lower()
    if not raw:
        return ""
    if "@" in raw:
        return raw
    return f"{raw}@{_TURBO_DON_DOMAIN}"


def _payload_mail_slug(payload: dict[str, Any]) -> str:
    return str(payload.get("name_mail") or payload.get("nameMail") or "").strip()


def _payload_turbo_credentials(payload: dict[str, Any]) -> tuple[str, str] | None:
    email = str(
        payload.get("email") or payload.get("turboproject_email") or payload.get("username") or ""
    ).strip()
    if not email:
        email = _turbo_email_from_slug(_payload_mail_slug(payload))
    password = str(payload.get("password") or payload.get("turboproject_password") or "").strip()
    if email and password:
        return email, password
    return None


def _settings_turbo_credentials() -> tuple[str, str] | None:
    email = settings.turboproject_email.strip()
    password = settings.turboproject_password or settings.my_password
    if not email:
        email = _turbo_email_from_slug(settings.my_name_mail)
    if email and password:
        return email, password
    return None


def _resolve_turbo_credentials(args: dict[str, Any] | None) -> tuple[str, str]:
    payload = args if isinstance(args, dict) else {}
    explicit = _payload_turbo_credentials(payload)
    if explicit:
        return explicit
    fallback = _settings_turbo_credentials()
    if fallback:
        return fallback
    raise TurboProjectError(
        "TurboProject: нет учётных данных "
        "(email/password или name_mail из сессии; иначе TURBOPROJECT_EMAIL/MY_NAME_MAIL и PASSWORD)"
    )


def _turbo_cred_cache_key(email: str) -> str:
    return email.strip().casefold() or "__empty__"


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
    resources = build_project_resources(details)
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
        "overdue_tasks": overdue_tasks[:_MAX_OVERDUE_ITEMS],
        "overdue_milestones": overdue_milestones[:_MAX_OVERDUE_ITEMS],
        "resources": resources[:_MAX_RESOURCES],
        "data_1c": details.get("data_1c"),
    }


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _index_people(item: dict[str, Any]) -> dict[str, Any]:
    """Owner and 1C participants from the cheap /api/projects/files row.

    Live index stores people on the item itself (rukovoditel_1c, project.author),
    not inside data_1c. Cards keep the same names under data_1c.
    """
    project = item.get("project") if isinstance(item.get("project"), dict) else {}
    data_1c = item.get("data_1c") if isinstance(item.get("data_1c"), dict) else {}
    owner = _first_text(
        item.get("rukovoditel_1c"),
        data_1c.get("rukovoditel"),
        project.get("author"),
        project.get("manager"),
        item.get("owner"),
    )
    curator = _first_text(
        item.get("kurator_1c"),
        data_1c.get("kurator"),
        project.get("curator"),
        item.get("curator"),
    )
    customer = _first_text(
        item.get("zakazchik_1c"),
        data_1c.get("zakazchik"),
        project.get("customer"),
        item.get("customer"),
    )
    deputy = _first_text(data_1c.get("zam_rp"), item.get("zam_rp"))
    participants = unique_resource_names([owner, curator, customer, deputy])
    return {
        "owner": owner,
        "curator": curator,
        "customer": customer,
        "deputy": deputy,
        "participants": participants,
    }


def _index_data_1c(item: dict[str, Any], people: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("data_1c") if isinstance(item.get("data_1c"), dict) else {}
    mapped = {
        "nomer_proekta": _first_text(raw.get("nomer_proekta"), item.get("nomer_proekta")),
        "status_proekta": _first_text(raw.get("status_proekta"), item.get("status_1c"), item.get("status")),
        "rukovoditel": people.get("owner") or "",
        "kurator": people.get("curator") or "",
        "zakazchik": people.get("customer") or "",
        "zam_rp": people.get("deputy") or "",
        "podrazdelenie": _first_text(raw.get("podrazdelenie"), item.get("podrazdelenie_1c")),
        "organizatsiya": _first_text(raw.get("organizatsiya"), item.get("organizatsiya_1c")),
        "tip_proekta": _first_text(raw.get("tip_proekta"), item.get("tip_proekta_1c")),
        "data_nachala": raw.get("data_nachala"),
        "data_okonchaniya": raw.get("data_okonchaniya"),
        "planovaya_data_okonchaniya": raw.get("planovaya_data_okonchaniya"),
    }
    return {key: value for key, value in mapped.items() if value not in (None, "")}


def build_project_index_item(item: dict[str, Any]) -> dict[str, Any]:
    """Cheap project index row from /api/projects/files without reading an MPP card."""
    raw_file_id = item.get("id") or item.get("file_id") or item.get("fileId")
    project = item.get("project") if isinstance(item.get("project"), dict) else {}
    people = _index_people(item)
    data_1c = _index_data_1c(item, people)
    return {
        "file_id": raw_file_id,
        "original_name": item.get("original_name") or item.get("name"),
        "uploaded_at": iso_or_none(item.get("uploaded_at")),
        "has_1c": bool(item.get("has_1c") or data_1c),
        "project_name": project.get("name") or item.get("project_name") or item.get("original_name") or item.get("name"),
        "owner": people["owner"],
        "curator": people["curator"],
        "customer": people["customer"],
        "participants": people["participants"],
        "dates": {
            "start_date": iso_or_none(project.get("start_date") or item.get("start_date")),
            "finish_date": iso_or_none(project.get("finish_date") or item.get("finish_date")),
            "actual_finish_date": iso_or_none(project.get("actual_finish_date") or item.get("actual_finish_date")),
            "baseline_start": iso_or_none(project.get("baseline_start") or item.get("baseline_start")),
            "baseline_finish": iso_or_none(project.get("baseline_finish") or item.get("baseline_finish")),
            "plan_finish_1c": iso_or_none(project.get("plan_finish_1c") or item.get("plan_finish_1c")),
        },
        "data_1c": data_1c,
    }


def _base_url() -> str:
    return settings.turboproject_api_base.strip().rstrip("/")


def _http_client() -> httpx.Client:
    """Shared client with a keep-alive pool for concurrent card fetches."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            pool = _ANALYTICS_CONCURRENCY + 4
            _client = httpx.Client(
                timeout=settings.turboproject_timeout_sec,
                limits=httpx.Limits(
                    max_connections=pool,
                    max_keepalive_connections=pool,
                ),
            )
    return _client


def _login_for_args(args: dict[str, Any] | None = None, *, force: bool = False) -> tuple[str, tuple[str, str]]:
    creds = _resolve_turbo_credentials(args)
    email, password = creds
    cache_key = _turbo_cred_cache_key(email)
    now = time.monotonic()
    if not force:
        cached = _token_cache.get(cache_key)
        if cached and now - cached[1] < _TOKEN_TTL_SEC:
            return cached[0], creds
    with _token_lock:
        now = time.monotonic()
        if not force:
            cached = _token_cache.get(cache_key)
            if cached and now - cached[1] < _TOKEN_TTL_SEC:
                return cached[0], creds
        url = f"{_base_url()}/api/auth/login"
        try:
            response = _http_client().post(
                url,
                json={"email": email, "password": password},
            )
            response.raise_for_status()
            token = str(response.json().get("token") or "").strip()
        except httpx.HTTPError as exc:
            raise TurboProjectError(f"TurboProject: не удалось войти: {exc}") from exc
        if not token:
            raise TurboProjectError("TurboProject: в ответе login нет token")
        _token_cache[cache_key] = (token, now)
        return token, creds


def _login(*, args: dict[str, Any] | None = None, force: bool = False) -> str:
    token, _creds = _login_for_args(args, force=force)
    return token


def _api_get(
    path: str,
    token: str,
    *,
    creds: tuple[str, str],
    retry: bool = True,
) -> Any:
    url = f"{_base_url()}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        response = _http_client().get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise TurboProjectError(f"TurboProject GET {path}: {exc}") from exc
    if response.status_code == 401 and retry:
        fresh_token, fresh_creds = _login_for_args(
            {"email": creds[0], "password": creds[1], "turboproject_email": creds[0], "turboproject_password": creds[1]},
            force=True,
        )
        return _api_get(path, fresh_token, creds=fresh_creds, retry=False)
    if response.status_code >= 400:
        text = response.text[:280].replace("\n", " ")
        raise TurboProjectError(f"TurboProject HTTP {response.status_code} {path}: {text}")
    data = response.json()
    return data


def _get_index_files(token: str, *, creds: tuple[str, str]) -> Any:
    """Cached /api/projects/files index per Turbo login."""
    cache_key = _turbo_cred_cache_key(creds[0])
    now = time.monotonic()
    with _index_cache_lock:
        cached = _index_cache_by_key.get(cache_key)
        if cached is not None and now - cached[0] < _INDEX_TTL_SEC:
            return cached[1]
    data = _api_get("/api/projects/files", token, creds=creds)
    with _index_cache_lock:
        _index_cache_by_key[cache_key] = (time.monotonic(), data)
    return data


def _get_card(file_id: Any, token: str, *, creds: tuple[str, str]) -> Any:
    """Cached project card. Cards change slowly, so a short TTL removes the
    biggest cost: re-reading the same portfolio across overdue/blocked/workload
    aggregators (upstream serves each card in ~1.5s)."""
    key = str(file_id)
    now = time.monotonic()
    with _card_cache_lock:
        hit = _card_cache.get(key)
        if hit is not None and now - hit[0] < _CARD_TTL_SEC:
            return hit[1]
    details = _api_get(f"/api/projects/files/{file_id}", token, creds=creds)
    with _card_cache_lock:
        _card_cache[key] = (time.monotonic(), details)
    return details


def _scan_project_cards(
    index_projects: list[dict[str, Any]],
    token: str,
    *,
    creds: tuple[str, str],
    scan_limit: int,
    consume: Callable[[dict[str, Any], dict[str, Any]], None],
    time_budget: float = _ANALYTICS_TIME_BUDGET_SEC,
) -> tuple[int, bool]:
    """Fetch project cards concurrently and feed each to consume().

    Runs upstream card reads through a bounded thread pool over the shared
    keep-alive client, so a portfolio-wide aggregate returns in seconds instead
    of one sequential request per project. Stops early when the wall-clock
    budget is reached and reports (scanned_count, timed_out) so callers can flag
    a partial result. consume() runs in this thread, so its shared state needs
    no extra locking.
    """
    targets = [
        item
        for item in index_projects[:scan_limit]
        if item.get("file_id")
    ]
    if not targets:
        return 0, False
    scanned = 0
    timed_out = False
    deadline = time.monotonic() + max(time_budget, 1.0)
    workers = min(_ANALYTICS_CONCURRENCY, len(targets))
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        future_map = {
            executor.submit(_get_card, item["file_id"], token, creds=creds): item
            for item in targets
        }
        for future in as_completed(future_map):
            index_item = future_map[future]
            scanned += 1
            try:
                details = future.result()
            except TurboProjectError:
                continue
            if isinstance(details, dict):
                consume(index_item, details)
            if time.monotonic() >= deadline:
                timed_out = True
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return scanned, timed_out


def _mark_partial(
    result: dict[str, Any],
    *,
    scanned: int,
    candidates: int,
    timed_out: bool,
) -> None:
    """Flag a portfolio aggregate that did not cover every candidate project."""
    if not timed_out and scanned >= candidates:
        return
    result["partial_result"] = (
        "Time budget reached before scanning every project. "
        f"Scanned {scanned} of {candidates} candidates. "
        "Narrow with query/manager/status filters or raise scan_limit for more."
    )


def is_phrase_query(query: str) -> bool:
    """True if query is a sentence/filter dump, not a project name or 1C number."""
    raw = (query or "").strip()
    if not raw:
        return False
    low = raw.casefold()
    if any(hint in low for hint in _PHRASE_QUERY_HINTS):
        return True
    parts = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    if len(parts) >= 2 and all(len(chunk.split()) >= 2 for chunk in parts):
        return True
    return len(raw.split()) >= 8


def is_project_name_query(query: str) -> bool:
    return bool((query or "").strip()) and not is_phrase_query(query)


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


def _people_values(item: dict[str, Any]) -> list[str]:
    data = _data_1c(item)
    values = [
        item.get("owner"),
        item.get("curator"),
        item.get("customer"),
        item.get("deputy"),
        data.get("rukovoditel"),
        data.get("kurator"),
        data.get("zakazchik"),
        data.get("zam_rp"),
        data.get("rukovodstvo_proektom"),
    ]
    participants = item.get("participants")
    if isinstance(participants, list):
        values.extend(participants)
    return [str(value).strip() for value in values if str(value or "").strip()]


def _matches_person(item: dict[str, Any], person: str, *, mode: str = "fio") -> bool:
    if not person:
        return True
    return any(_person_name_matches(person, value, mode=mode) for value in _people_values(item))


def _matches_manager(item: dict[str, Any], manager: str) -> bool:
    return _matches_person(item, manager)


def _string_filter(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = str(payload.get(name) or "").strip()
        if value:
            return value
    return ""


def _int_filter(payload: dict[str, Any], name: str, default: int, maximum: int) -> int:
    raw = payload.get(name)
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    if value <= 0:
        value = default
    return min(value, maximum)


def _cursor_offset(payload: dict[str, Any]) -> int:
    raw = payload.get("cursor") or payload.get("offset")
    try:
        value = int(raw) if raw not in (None, "") else 0
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _page(items: list[dict[str, Any]], *, limit: int, cursor: int) -> tuple[list[dict[str, Any]], str]:
    end = cursor + limit
    next_cursor = str(end) if end < len(items) else ""
    return items[cursor:end], next_cursor


def _data_1c(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("data_1c") if isinstance(item.get("data_1c"), dict) else {}


def _matches_text(value: Any, needle: str) -> bool:
    if not needle:
        return True
    return needle.casefold() in str(value or "").casefold()


def _matches_status(item: dict[str, Any], status: str) -> bool:
    if not status:
        return True
    data = _data_1c(item)
    return _matches_text(data.get("status_proekta") or item.get("status"), status)


def _matches_owner(item: dict[str, Any], owner: str) -> bool:
    return _matches_person(item, owner)


def _matches_department(item: dict[str, Any], department: str) -> bool:
    if not department:
        return True
    data = _data_1c(item)
    return _matches_text(data.get("podrazdelenie") or data.get("organizatsiya"), department)


def _project_date(item: dict[str, Any]) -> datetime | None:
    dates = item.get("dates") if isinstance(item.get("dates"), dict) else {}
    data = _data_1c(item)
    for value in (
        dates.get("finish_date"),
        dates.get("plan_finish_1c"),
        data.get("planovaya_data_okonchaniya"),
        data.get("data_okonchaniya"),
        item.get("uploaded_at"),
    ):
        parsed = parse_iso_date(value)
        if parsed is not None:
            return parsed
    return None


def _matches_date_range(item: dict[str, Any], date_from: str, date_to: str) -> bool:
    value = _project_date(item)
    if value is None:
        return True
    start = parse_iso_date(date_from) if date_from else None
    end = parse_iso_date(date_to) if date_to else None
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def _filtered_index_projects(args: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    raw_query = _string_filter(args, "query", "project_name")
    query = raw_query if is_project_name_query(raw_query) else ""
    status = _string_filter(args, "status", "status_proekta")
    owner = _string_filter(
        args, "owner_id", "owner", "manager", "rukovoditel", "employee", "fio", "user"
    )
    department = _string_filter(args, "department_id", "department", "podrazdelenie")
    date_from = _string_filter(args, "date_from", "from")
    date_to = _string_filter(args, "date_to", "to")
    active_token, creds = _login_for_args(args)
    summary = _get_index_files(active_token, creds=creds)
    items = summary.get("items") or []
    with_1c = [item for item in items if item.get("has_1c")]
    projects = [build_project_index_item(item) for item in with_1c]
    if query:
        projects = [item for item in projects if _matches_query(item, query)]
    projects = [
        item
        for item in projects
        if _matches_status(item, status)
        and _matches_department(item, department)
        and _matches_date_range(item, date_from, date_to)
    ]
    if owner:
        projects = _prefer_person_hits(
            projects, lambda item, mode: _matches_person(item, owner, mode=mode)
        )
    sort_by = _string_filter(args, "sort_by", "sort").casefold()
    if sort_by in {"finish_date", "date"}:
        projects.sort(key=lambda item: (_project_date(item) or datetime.max, item.get("project_name") or ""))
    elif sort_by == "project_name":
        projects.sort(key=lambda item: str(item.get("project_name") or "").casefold())
    return projects, len(items), len(with_1c)


def _explicit_project_ids(payload: dict[str, Any]) -> list[str]:
    """ID проектов, которые агент уже выбрал в индексе (project_ids/file_ids/file_id)."""
    raw = payload.get("project_ids") or payload.get("file_ids") or payload.get("file_id")
    if isinstance(raw, str):
        ids = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        ids = [str(item).strip() for item in raw if str(item).strip()]
    elif raw not in (None, ""):
        ids = [str(raw).strip()]
    else:
        ids = []
    return ids[:_MAX_PROJECT_IDS]


def _has_narrowing(payload: dict[str, Any]) -> bool:
    """Есть ли у агрегатора узкий фильтр (manager/query/status/...)."""
    for key in _AGG_NARROW_KEYS:
        if str(payload.get(key) or "").strip():
            return True
    return False


def _aggregator_refusal(mode: str) -> dict[str, Any]:
    """Дешёвый отказ агрегатора без сканирования портфеля."""
    return {
        "summary": (
            "Портфель целиком не сканируется. Сначала turboproject.get_user_portfolio "
            "(employee = ФИО из users.current) или search_projects с manager/query, "
            "затем передай нужные file_id как project_ids."
        ),
        "matched_projects_count": 0,
        "scanned_projects_count": 0,
        "projects": [],
        "source": "turboproject",
        "mode": mode,
        "needs": "turboproject.search_projects",
    }


def _delay_days(date_value: Any) -> int:
    parsed = parse_iso_date(date_value)
    if parsed is None:
        return 0
    return max(0, (datetime.now().date() - parsed.date()).days)


def _select_project_fields(project: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    allowed = set(fields or [])
    if not allowed:
        allowed = {"identity", "dates", "data_1c", "task_stats", "overdue", "resources"}
    result: dict[str, Any] = {}
    if "identity" in allowed:
        result.update(
            {
                "file_id": project.get("file_id"),
                "project_name": project.get("project_name"),
                "original_name": project.get("original_name"),
                "uploaded_at": project.get("uploaded_at"),
            }
        )
    if "dates" in allowed:
        result["dates"] = project.get("dates") or {}
    if "data_1c" in allowed:
        result["data_1c"] = project.get("data_1c") or {}
    if "task_stats" in allowed:
        result["task_stats"] = project.get("task_stats") or {}
    if "overdue" in allowed:
        result["overdue_tasks"] = project.get("overdue_tasks") or []
        result["overdue_milestones"] = project.get("overdue_milestones") or []
    if "resources" in allowed:
        result["resources"] = project.get("resources") or []
    if "budget" in allowed:
        data = _data_1c(project)
        result["budget"] = {
            "byudzhet_plan": data.get("byudzhet_plan"),
            "byudzhet_fakt": data.get("byudzhet_fakt"),
            "istochnik_finansirovaniya": data.get("istochnik_finansirovaniya"),
        }
    if "decisions" in allowed:
        data = _data_1c(project)
        result["decisions"] = {
            "resheniya": data.get("resheniya"),
            "chek_list": data.get("chek_list"),
            "perenosy_proekta": data.get("perenosy_proekta"),
        }
    return result


def _field_list(args: dict[str, Any], *, default: list[str] | None = None) -> list[str]:
    raw = args.get("fields") or default or []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return list(default or [])


def _normalize_person_key(value: str) -> str:
    text = (value or "").casefold().replace("ё", "е")
    for ch in ("ь", "ъ", "\u0301"):
        text = text.replace(ch, "")
    return " ".join(text.split())


def _surname_and_initials(key: str) -> tuple[str, list[str]] | None:
    parts = key.split()
    if len(parts) < 2:
        return None
    surname = parts[0]
    tail = " ".join(parts[1:])
    if "." not in tail:
        return None
    initials: list[str] = []
    for chunk in tail.replace(".", " ").split():
        letter = chunk.strip()
        if letter:
            initials.append(letter[0])
    if not initials:
        return None
    return surname, initials


def _initials_match_name_parts(initials: list[str], name_parts: list[str]) -> bool:
    if not initials or not name_parts:
        return False
    if len(initials) == 1:
        return initials[0] == name_parts[0][0]
    needed = min(len(initials), len(name_parts))
    return all(initials[index] == name_parts[index][0] for index in range(needed))


def _person_name_matches(actor: str, candidate: str, *, mode: str = "fio") -> bool:
    actor_key = _normalize_person_key(actor)
    cand_key = _normalize_person_key(candidate)
    if not actor_key or not cand_key:
        return False
    actor_parts = actor_key.split()
    cand_parts = cand_key.split()
    if mode == "surname":
        return bool(actor_parts and cand_parts and actor_parts[0] == cand_parts[0])
    if actor_key == cand_key:
        return True
    if actor_key in cand_key or cand_key in actor_key:
        shorter = actor_key if len(actor_key) <= len(cand_key) else cand_key
        if len(shorter.split()) >= 2:
            return True
    if len(actor_parts) >= 2 and len(cand_parts) >= 2:
        if actor_parts[0] == cand_parts[0] and actor_parts[1] == cand_parts[1]:
            return True
    actor_init = _surname_and_initials(actor_key)
    cand_init = _surname_and_initials(cand_key)
    if actor_init and len(cand_parts) >= 2:
        surname, initials = actor_init
        if surname == cand_parts[0] and _initials_match_name_parts(initials, cand_parts[1:]):
            return True
    if cand_init and len(actor_parts) >= 2:
        surname, initials = cand_init
        if surname == actor_parts[0] and _initials_match_name_parts(initials, actor_parts[1:]):
            return True
    return False


def _prefer_person_hits(
    items: list[Any],
    predicate: Callable[[Any, str], bool],
) -> list[Any]:
    """Keep FIO hits; if none, fall back to surname-only matches."""
    fio_hits = [item for item in items if predicate(item, "fio")]
    if fio_hits:
        return fio_hits
    return [item for item in items if predicate(item, "surname")]


def _resource_id_values(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    raw = payload.get("resource_id") or payload.get("resource_ids") or payload.get("assignee_resource_ids")
    if isinstance(raw, str):
        for part in raw.split(","):
            text = part.strip()
            if text:
                ids.add(text)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            text = str(item).strip()
            if text:
                ids.add(text)
    elif raw not in (None, ""):
        ids.add(str(raw).strip())
    return ids


def _resolve_task_assignee_filter(payload: dict[str, Any]) -> tuple[str, set[str], bool]:
    """FIO and/or Turbo resource ids; active unless all_assignees is set."""
    if bool(payload.get("all_assignees") or payload.get("allAssignees")):
        return "", set(), False
    assignee = _string_filter(
        payload, "assignee", "assignee_id", "employee_id", "resource", "resource_name"
    )
    resource_ids = _resource_id_values(payload)
    if not assignee:
        assignee = _string_filter(payload, "employee", "fio", "user")
    if not assignee and not resource_ids:
        return "", set(), False
    return assignee, resource_ids, True


def _assignment_resource_name(assignment: Any) -> str:
    if not isinstance(assignment, dict):
        return ""
    direct = str(
        assignment.get("resource_name")
        or assignment.get("ResourceName")
        or assignment.get("resourceName")
        or ""
    ).strip()
    if direct:
        return direct
    resource = assignment.get("resource")
    if isinstance(resource, dict):
        nested = str(resource.get("name") or resource.get("Name") or "").strip()
        if nested:
            return nested
    return str(assignment.get("name") or "").strip()


def _assignment_resource_id(assignment: Any) -> str:
    if not isinstance(assignment, dict):
        return ""
    rid = assignment.get("resource_id") or assignment.get("ResourceId") or assignment.get("resourceId")
    if rid is not None and str(rid).strip():
        return str(rid).strip()
    resource = assignment.get("resource")
    if isinstance(resource, dict):
        nested = resource.get("id") or resource.get("Id")
        if nested is not None and str(nested).strip():
            return str(nested).strip()
    return ""


def _task_assigned_to(
    raw_task: dict[str, Any],
    assignee_fio: str,
    resource_ids: set[str],
    *,
    mode: str = "fio",
) -> bool:
    assignments = raw_task.get("assignments") or []
    if not assignments:
        return False
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        if resource_ids:
            rid = _assignment_resource_id(assignment)
            if rid and rid in resource_ids:
                return True
        name = _assignment_resource_name(assignment)
        if assignee_fio and name and _person_name_matches(assignee_fio, name, mode=mode):
            return True
    return False


def _task_rows(details: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for task in details.get("tasks") or []:
        assignments = task.get("assignments") or []
        executors: list[str] = []
        executor_resource_ids: list[str] = []
        for item in assignments:
            name = _assignment_resource_name(item)
            if name:
                executors.append(name)
            rid = _assignment_resource_id(item)
            if rid:
                executor_resource_ids.append(rid)
        percent = float(task.get("percent_complete") or 0.0)
        finish_date = iso_or_none(task.get("finish_date"))
        rows.append(
            {
                "id": task.get("id"),
                "uid": task.get("uid"),
                "name": task.get("name"),
                "outline_number": task.get("outline_number") or task.get("wbs"),
                "start_date": iso_or_none(task.get("start_date")),
                "finish_date": finish_date,
                "percent_complete": percent,
                "is_summary": bool(task.get("is_summary")),
                "is_milestone": bool(task.get("is_milestone")),
                "executors": executors,
                "executor_resource_ids": executor_resource_ids,
                "delay_days": _delay_days(finish_date),
            }
        )
    return rows


def _matches_task_status(task: dict[str, Any], status: str) -> bool:
    if not status:
        return True
    folded = status.casefold()
    complete = float(task.get("percent_complete") or 0.0) >= 1.0
    if folded in {"done", "completed", "complete", "готово", "завершено"}:
        return complete
    if folded in {"open", "active", "incomplete", "not_done", "в работе", "активно"}:
        return not complete
    return _matches_text(task.get("name"), status)


def list_project_index(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    raw_query = str(payload.get("query") or payload.get("project_name") or "").strip()
    query = raw_query if is_project_name_query(raw_query) else ""
    manager = str(payload.get("manager") or payload.get("rukovoditel") or "").strip()
    overdue_only = bool(payload.get("overdue_only") or payload.get("overdueOnly"))
    if raw_query and not query and not manager and not overdue_only:
        return {
            "summary": (
                "query не применён: нужна строка-название проекта, имя MPP или номер 1С, "
                "не фраза. Участников отдельным полем этот инструмент пока не принимает."
            ),
            "total_projects": 0,
            "projects_with_1c_count": 0,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "projects": [],
            "source": "turboproject",
        }
    raw_limit = payload.get("limit")
    limit = int(raw_limit) if raw_limit not in (None, "") else 50
    if limit <= 0:
        limit = 50
    limit = min(limit, 500)

    token, creds = _login_for_args(payload)
    summary = _get_index_files(token, creds=creds)
    items = summary.get("items") or []
    with_1c = [item for item in items if item.get("has_1c")]
    projects = [build_project_index_item(item) for item in with_1c]
    if query:
        projects = [item for item in projects if _matches_query(item, query)]
    if manager:
        projects = _prefer_person_hits(
            projects, lambda item, mode: _matches_person(item, manager, mode=mode)
        )
    if overdue_only:
        return {
            "summary": (
                "overdue_only требует карточки проекта. Сначала выбери file_id из индекса, "
                "затем вызови turboproject.get для нужных проектов."
            ),
            "total_projects": len(items),
            "projects_with_1c_count": len(with_1c),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "projects": [],
            "source": "turboproject",
            "mode": "index",
            "needs": "turboproject.get",
        }
    total_matched = len(projects)
    projects = projects[:limit]
    return {
        "summary": f"TurboProject index: {len(projects)} из {total_matched} проект(ов) с 1С; карточки читай через turboproject.get(file_id)",
        "total_projects": len(items),
        "projects_with_1c_count": len(with_1c),
        "matched_projects_count": total_matched,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "projects": projects,
        "source": "turboproject",
        "mode": "index",
    }


def get_project_card(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    file_id = payload.get("file_id") or payload.get("fileId")
    if file_id in (None, ""):
        raise TurboProjectError("turboproject.get требует file_id из turboproject.list")
    raw_query = str(payload.get("query") or payload.get("project_name") or "").strip()
    query = raw_query if is_project_name_query(raw_query) else ""
    manager = str(payload.get("manager") or payload.get("rukovoditel") or "").strip()
    overdue_only = bool(payload.get("overdue_only") or payload.get("overdueOnly"))
    token, creds = _login_for_args(payload)
    details = _get_card(file_id, token, creds=creds)
    summary = {
        "id": file_id,
        "original_name": (details.get("file") or {}).get("original_name")
        or (details.get("project") or {}).get("name"),
        "uploaded_at": (details.get("file") or {}).get("uploaded_at"),
        "has_1c": bool(details.get("data_1c")),
    }
    projects = [build_project_payload(summary, details)]
    if query and not _matches_query(projects[0], query):
        projects = []
    if manager and projects:
        card = projects[0]
        if not _matches_person(card, manager, mode="fio") and not _matches_person(
            card, manager, mode="surname"
        ):
            projects = []
    if overdue_only:
        projects = [
            item
            for item in projects
            if item["task_stats"]["overdue_tasks_count"]
            or item["task_stats"]["overdue_milestones_count"]
        ]
    return {
        "summary": f"TurboProject card: {len(projects)} проект(ов)",
        "total_projects": 1,
        "projects_with_1c_count": 1 if summary.get("has_1c") else 0,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "projects": projects,
        "source": "turboproject",
        "mode": "card",
    }


def search_projects(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    limit = _int_filter(payload, "limit", _DEFAULT_SEARCH_LIMIT, _MAX_SEARCH_LIMIT)
    cursor = _cursor_offset(payload)
    projects, total_projects, with_1c_count = _filtered_index_projects(payload)
    page, next_cursor = _page(projects, limit=limit, cursor=cursor)
    return {
        "summary": f"TurboProject search: {len(page)} из {len(projects)} найденных проектов",
        "total_projects": total_projects,
        "projects_with_1c_count": with_1c_count,
        "matched_projects_count": len(projects),
        "limit": limit,
        "cursor": str(cursor),
        "next_cursor": next_cursor,
        "projects": page,
        "source": "turboproject",
        "mode": "search",
    }


def get_user_portfolio(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """All cheap index rows where employee is owner, curator, customer or deputy.

    One call, no card scan. Pass employee = users.current.user.fio.
    """
    payload = args if isinstance(args, dict) else {}
    employee = _string_filter(
        payload, "employee", "fio", "user", "manager", "owner", "rukovoditel"
    )
    if not employee:
        return {
            "summary": (
                "Нужно ФИО сотрудника. Сначала users.current, затем вызови "
                "turboproject.get_user_portfolio с employee = user.fio."
            ),
            "matched_projects_count": 0,
            "projects": [],
            "source": "turboproject",
            "mode": "user_portfolio",
            "needs": "users.current",
        }
    filter_args = dict(payload)
    filter_args["owner"] = employee
    projects, total_projects, with_1c_count = _filtered_index_projects(filter_args)
    limit = _int_filter(payload, "limit", _MAX_USER_PORTFOLIO, _MAX_USER_PORTFOLIO)
    cursor = _cursor_offset(payload)
    page, next_cursor = _page(projects, limit=limit, cursor=cursor)
    turbo_login = ""
    try:
        turbo_login = _resolve_turbo_credentials(payload)[0]
    except TurboProjectError:
        pass
    summary = (
        f"Портфель {employee}: {len(page)} из {len(projects)} проект(ов), "
        "где сотрудник руководитель, куратор, заказчик или зам. "
        "Карточки читай только если нужны задачи или просрочки."
    )
    result: dict[str, Any] = {
        "summary": summary,
        "employee": employee,
        "total_projects": total_projects,
        "projects_with_1c_count": with_1c_count,
        "matched_projects_count": len(projects),
        "limit": limit,
        "cursor": str(cursor),
        "next_cursor": next_cursor,
        "projects": page,
        "source": "turboproject",
        "mode": "user_portfolio",
    }
    if turbo_login:
        result["turbo_login_email"] = turbo_login
    if not projects:
        result["portfolio_empty_hint"] = (
            f"Логин TurboProject {turbo_login or '(не задан)'}: индекс /api/projects/files "
            f"({total_projects} файлов, {with_1c_count} с 1С) не содержит ролей для ФИО «{employee}». "
            "Это фильтр по руководитель/куратор/заказчик/зам в 1С, не список задач исполнителя. "
            "Проверьте MY_NAME (ФИО) и MY_NAME_MAIL/TURBOPROJECT_EMAIL (латинский логин API)."
        )
    return result


def get_project(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    project_id = payload.get("project_id") or payload.get("file_id") or payload.get("fileId")
    if project_id in (None, ""):
        raise TurboProjectError("turboproject.get_project требует project_id или file_id")
    fields = _field_list(
        payload,
        default=["identity", "dates", "data_1c", "task_stats", "overdue", "resources"],
    )
    card = get_project_card({"file_id": project_id})
    projects = card.get("projects") if isinstance(card.get("projects"), list) else []
    selected = [_select_project_fields(project, fields) for project in projects if isinstance(project, dict)]
    return {
        "summary": f"TurboProject project: {len(selected)} проект(ов), fields={','.join(fields) or 'default'}",
        "project_id": str(project_id),
        "fields": fields,
        "projects": selected,
        "source": "turboproject",
        "mode": "project",
    }


def get_project_tasks(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    project_id = payload.get("project_id") or payload.get("file_id") or payload.get("fileId")
    if project_id in (None, ""):
        raise TurboProjectError("turboproject.get_project_tasks требует project_id или file_id")
    status = _string_filter(payload, "status")
    assignee_fio, resource_ids, filter_assignees = _resolve_task_assignee_filter(payload)
    overdue_only = bool(payload.get("overdue_only") or payload.get("overdueOnly"))
    limit = _int_filter(payload, "limit", 50, 100)
    cursor = _cursor_offset(payload)
    token, creds = _login_for_args(payload)
    details = _get_card(project_id, token, creds=creds)
    raw_tasks = details.get("tasks") or []
    tasks = _task_rows(details)
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw_task, task in zip(raw_tasks, tasks, strict=False):
        if task.get("is_summary"):
            continue
        if not _matches_task_status(task, status):
            continue
        if overdue_only and int(task.get("delay_days") or 0) <= 0:
            continue
        candidates.append((raw_task, task))
    if filter_assignees:
        fio_hits = [
            task
            for raw_task, task in candidates
            if _task_assigned_to(raw_task, assignee_fio, resource_ids, mode="fio")
        ]
        filtered = fio_hits or [
            task
            for raw_task, task in candidates
            if _task_assigned_to(raw_task, assignee_fio, resource_ids, mode="surname")
        ]
    else:
        filtered = [task for _raw_task, task in candidates]
    filtered.sort(key=lambda item: (-(int(item.get("delay_days") or 0)), item.get("finish_date") or ""))
    page, next_cursor = _page(filtered, limit=limit, cursor=cursor)
    return {
        "summary": f"TurboProject tasks: {len(page)} из {len(filtered)} задач проекта {project_id}",
        "project_id": str(project_id),
        "matched_tasks_count": len(filtered),
        "limit": limit,
        "cursor": str(cursor),
        "next_cursor": next_cursor,
        "tasks": page,
        "source": "turboproject",
        "mode": "tasks",
    }


def get_project_metrics(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    raw_ids = payload.get("project_ids") or payload.get("file_ids") or []
    if isinstance(raw_ids, str):
        project_ids = [part.strip() for part in raw_ids.split(",") if part.strip()]
    elif isinstance(raw_ids, list):
        project_ids = [str(item).strip() for item in raw_ids if str(item).strip()]
    else:
        project_ids = []
    project_ids = project_ids[:_MAX_PROJECT_IDS]
    if not project_ids:
        raise TurboProjectError("turboproject.get_project_metrics требует project_ids")
    metrics = _field_list(
        payload,
        default=["task_stats", "overdue", "resources", "dates"],
    )
    rows: list[dict[str, Any]] = []
    for project_id in project_ids:
        card = get_project_card({**payload, "file_id": project_id})
        projects = card.get("projects") if isinstance(card.get("projects"), list) else []
        if not projects:
            continue
        project = projects[0]
        item = {
            "project_id": project_id,
            "project_name": project.get("project_name"),
        }
        if "task_stats" in metrics:
            item["task_stats"] = project.get("task_stats") or {}
        if "overdue" in metrics:
            stats = project.get("task_stats") or {}
            item["overdue_tasks_count"] = stats.get("overdue_tasks_count", 0)
            item["overdue_milestones_count"] = stats.get("overdue_milestones_count", 0)
        if "resources" in metrics:
            item["resources_count"] = len(project.get("resources") or [])
        if "dates" in metrics:
            item["dates"] = project.get("dates") or {}
        rows.append(item)
    return {
        "summary": f"TurboProject metrics: {len(rows)} проект(ов)",
        "metrics": metrics,
        "projects": rows,
        "source": "turboproject",
        "mode": "metrics",
    }


def get_overdue_projects(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    limit = _int_filter(payload, "limit", 10, 50)
    min_delay_days = _int_filter(payload, "min_delay_days", 1, 3650)
    ids = _explicit_project_ids(payload)
    if not ids and not _has_narrowing(payload):
        return _aggregator_refusal("overdue_projects")
    token, creds = _login_for_args(payload)
    if ids:
        projects = [{"file_id": pid} for pid in ids]
        total_projects = len(ids)
        with_1c_count = len(ids)
        scan_limit = len(ids)
    else:
        projects, total_projects, with_1c_count = _filtered_index_projects(payload)
        scan_limit = _int_filter(payload, "scan_limit", _DEFAULT_AGG_SCAN, _MAX_ANALYTICS_SCAN)
    rows: list[dict[str, Any]] = []

    def consume(index_item: dict[str, Any], details: dict[str, Any]) -> None:
        project = build_project_payload(details.get("file") or index_item, details)
        stats = project.get("task_stats") or {}
        dates = project.get("dates") or {}
        delay_days = max(
            int(stats.get("max_delay_days") or 0),
            _delay_days(dates.get("finish_date") or dates.get("plan_finish_1c")),
        )
        overdue_count = int(stats.get("overdue_tasks_count") or 0) + int(
            stats.get("overdue_milestones_count") or 0
        )
        if delay_days < min_delay_days and overdue_count <= 0:
            return
        rows.append(
            {
                "project_id": index_item.get("file_id"),
                "project_name": project.get("project_name"),
                "status": _data_1c(project).get("status_proekta"),
                "owner": _data_1c(project).get("rukovoditel"),
                "department": _data_1c(project).get("podrazdelenie"),
                "finish_date": dates.get("finish_date") or dates.get("plan_finish_1c"),
                "delay_days": delay_days,
                "overdue_tasks_count": int(stats.get("overdue_tasks_count") or 0),
                "overdue_milestones_count": int(stats.get("overdue_milestones_count") or 0),
            }
        )

    scanned, timed_out = _scan_project_cards(
        projects, token, creds=creds, scan_limit=scan_limit, consume=consume
    )
    rows.sort(key=lambda item: (-(int(item.get("delay_days") or 0)), str(item.get("project_name") or "")))
    page = rows[:limit]
    result = {
        "summary": f"TurboProject overdue: {len(page)} из {len(rows)} просроченных проектов",
        "total_projects": total_projects,
        "projects_with_1c_count": with_1c_count,
        "scanned_projects_count": scanned,
        "matched_projects_count": len(rows),
        "limit": limit,
        "next_cursor": "",
        "projects": page,
        "source": "turboproject",
        "mode": "overdue_projects",
    }
    _mark_partial(result, scanned=scanned, candidates=len(projects), timed_out=timed_out)
    return result


def get_projects_with_blocked_tasks(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    limit = _int_filter(payload, "limit", 10, 50)
    blocked_days = _int_filter(payload, "blocked_days", 14, 3650)
    ids = _explicit_project_ids(payload)
    if not ids and not _has_narrowing(payload):
        return _aggregator_refusal("blocked_tasks")
    token, creds = _login_for_args(payload)
    if ids:
        projects = [{"file_id": pid} for pid in ids]
        scan_limit = len(ids)
    else:
        projects, _, _ = _filtered_index_projects(payload)
        scan_limit = _int_filter(payload, "scan_limit", _DEFAULT_AGG_SCAN, _MAX_ANALYTICS_SCAN)
    rows: list[dict[str, Any]] = []

    def consume(index_item: dict[str, Any], details: dict[str, Any]) -> None:
        tasks = [
            task
            for task in _task_rows(details)
            if not task.get("is_summary")
            and float(task.get("percent_complete") or 0.0) < 1.0
            and int(task.get("delay_days") or 0) >= blocked_days
        ]
        if not tasks:
            return
        rows.append(
            {
                "project_id": index_item.get("file_id"),
                "project_name": index_item.get("project_name"),
                "blocked_tasks_count": len(tasks),
                "max_delay_days": max(int(task.get("delay_days") or 0) for task in tasks),
                "tasks": tasks[:5],
            }
        )

    scanned, timed_out = _scan_project_cards(
        projects, token, creds=creds, scan_limit=scan_limit, consume=consume
    )
    rows.sort(key=lambda item: (-(int(item.get("max_delay_days") or 0)), str(item.get("project_name") or "")))
    heuristic_note = (
        "TurboProject card does not expose a dedicated blocked flag; "
        "used overdue incomplete task heuristic."
    )
    result = {
        "summary": f"TurboProject blocked tasks: {min(len(rows), limit)} из {len(rows)} проектов",
        "partial_result": heuristic_note,
        "scanned_projects_count": scanned,
        "matched_projects_count": len(rows),
        "limit": limit,
        "next_cursor": "",
        "projects": rows[:limit],
        "source": "turboproject",
        "mode": "blocked_tasks",
    }
    if timed_out or scanned < len(projects):
        result["partial_result"] = (
            heuristic_note
            + " Time budget reached: "
            + f"scanned {scanned} of {len(projects)} candidates, narrow filters or raise scan_limit."
        )
    return result


def get_workload_summary(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    scan_limit = _int_filter(payload, "scan_limit", _DEFAULT_ANALYTICS_SCAN, _MAX_ANALYTICS_SCAN)
    employee = _string_filter(payload, "employee_id", "employee", "resource")
    token, creds = _login_for_args(payload)
    projects, _, _ = _filtered_index_projects(payload)
    fio_employees: dict[str, dict[str, Any]] = {}
    surname_employees: dict[str, dict[str, Any]] = {}

    def _add_workload(bucket: dict[str, dict[str, Any]], name: str, project_id: Any, task: dict[str, Any]) -> None:
        item = bucket.setdefault(
            name,
            {
                "employee": name,
                "tasks_count": 0,
                "overdue_tasks_count": 0,
                "projects_count": 0,
                "project_ids": set(),
            },
        )
        item["tasks_count"] += 1
        if _delay_days(task.get("finish_date")) > 0 and float(task.get("percent_complete") or 0.0) < 1.0:
            item["overdue_tasks_count"] += 1
        item["project_ids"].add(project_id)

    def consume(index_item: dict[str, Any], details: dict[str, Any]) -> None:
        project_id = index_item.get("file_id")
        for task in details.get("tasks") or []:
            if task.get("is_summary"):
                continue
            for assignment in task.get("assignments") or []:
                name = _assignment_resource_name(assignment)
                if not name:
                    continue
                if not employee:
                    _add_workload(fio_employees, name, project_id, task)
                    continue
                if _person_name_matches(employee, name, mode="fio"):
                    _add_workload(fio_employees, name, project_id, task)
                elif _person_name_matches(employee, name, mode="surname"):
                    _add_workload(surname_employees, name, project_id, task)

    scanned, timed_out = _scan_project_cards(
        projects, token, creds=creds, scan_limit=scan_limit, consume=consume
    )
    employees = fio_employees or surname_employees
    rows = []
    for item in employees.values():
        project_ids = sorted(item.pop("project_ids"))
        item["project_ids"] = project_ids[:10]
        item["projects_count"] = len(project_ids)
        rows.append(item)
    rows.sort(key=lambda item: (-(int(item.get("overdue_tasks_count") or 0)), -(int(item.get("tasks_count") or 0))))
    result = {
        "summary": f"TurboProject workload: {len(rows)} сотрудник(ов)",
        "scanned_projects_count": scanned,
        "employees": rows,
        "source": "turboproject",
        "mode": "workload_summary",
    }
    _mark_partial(result, scanned=scanned, candidates=len(projects), timed_out=timed_out)
    return result


def get_project_portfolio_summary(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    group_by = _string_filter(payload, "group_by", "group").casefold() or "status"
    if group_by not in {"status", "department", "owner"}:
        return {
            "error": "unsupported_filter",
            "message": "group_by должен быть одним из: status, department, owner",
            "source": "turboproject",
            "mode": "portfolio_summary",
        }
    projects, total_projects, with_1c_count = _filtered_index_projects(payload)
    groups: dict[str, dict[str, Any]] = {}
    for project in projects:
        data = _data_1c(project)
        if group_by == "status":
            key = str(data.get("status_proekta") or "Без статуса")
        elif group_by == "department":
            key = str(data.get("podrazdelenie") or "Без подразделения")
        else:
            key = str(data.get("rukovoditel") or "Без руководителя")
        item = groups.setdefault(
            key,
            {
                group_by: key,
                "projects_count": 0,
                "project_ids": [],
                "with_finish_date_count": 0,
            },
        )
        item["projects_count"] += 1
        item["project_ids"].append(project.get("file_id"))
        if _project_date(project) is not None:
            item["with_finish_date_count"] += 1
    rows = sorted(groups.values(), key=lambda item: (-(int(item.get("projects_count") or 0)), str(item.get(group_by) or "")))
    for row in rows:
        row["project_ids"] = row["project_ids"][:10]
    return {
        "summary": f"TurboProject portfolio: {len(rows)} групп по {group_by}",
        "total_projects": total_projects,
        "projects_with_1c_count": with_1c_count,
        "matched_projects_count": len(projects),
        "group_by": group_by,
        "groups": rows,
        "source": "turboproject",
        "mode": "portfolio_summary",
    }


def list_projects(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    if payload.get("file_id") not in (None, "") or payload.get("fileId") not in (None, ""):
        return get_project_card(payload)
    return list_project_index(payload)


def list_project_cards(args: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    raw_query = str(payload.get("query") or payload.get("project_name") or "").strip()
    query = raw_query if is_project_name_query(raw_query) else ""
    manager = str(payload.get("manager") or payload.get("rukovoditel") or "").strip()
    overdue_only = bool(payload.get("overdue_only") or payload.get("overdueOnly"))
    raw_limit = payload.get("limit")
    limit = int(raw_limit) if raw_limit not in (None, "") else _DEFAULT_PROJECT_LIMIT
    if limit <= 0:
        limit = _DEFAULT_PROJECT_LIMIT
    limit = min(limit, 20)

    token, creds = _login_for_args(payload)
    summary = _get_index_files(token, creds=creds)
    items = summary.get("items") or []
    with_1c = [item for item in items if item.get("has_1c")]
    fio_projects: list[dict[str, Any]] = []
    surname_projects: list[dict[str, Any]] = []
    for item in with_1c:
        current_id = item.get("id")
        if not current_id:
            continue
        details = _get_card(current_id, token, creds=creds)
        project = build_project_payload(item, details)
        if query and not _matches_query(project, query):
            continue
        if overdue_only and not (
            project["task_stats"]["overdue_tasks_count"]
            or project["task_stats"]["overdue_milestones_count"]
        ):
            continue
        if manager:
            if _matches_person(project, manager, mode="fio"):
                fio_projects.append(project)
            elif _matches_person(project, manager, mode="surname"):
                surname_projects.append(project)
        else:
            fio_projects.append(project)
        if len(fio_projects) >= limit:
            break
    projects = fio_projects[:limit] if fio_projects else surname_projects[:limit]
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
    if tool not in TURBOPROJECT_TOOLS:
        raise TurboProjectError(f"Неизвестный инструмент TurboProject: {tool}")
    args = arguments if isinstance(arguments, dict) else {}
    if not turboproject_configured():
        return stub_projects(args)
    try:
        if tool == SEARCH_PROJECTS_TOOL_NAME:
            return search_projects(args)
        if tool == GET_USER_PORTFOLIO_TOOL_NAME:
            return get_user_portfolio(args)
        if tool == GET_PROJECT_TOOL_NAME:
            return get_project(args)
        if tool == GET_PROJECT_TASKS_TOOL_NAME:
            return get_project_tasks(args)
        if tool == GET_PROJECT_METRICS_TOOL_NAME:
            return get_project_metrics(args)
        if tool == GET_OVERDUE_PROJECTS_TOOL_NAME:
            return get_overdue_projects(args)
        if tool == GET_BLOCKED_TASKS_TOOL_NAME:
            return get_projects_with_blocked_tasks(args)
        if tool == GET_WORKLOAD_SUMMARY_TOOL_NAME:
            return get_workload_summary(args)
        if tool == GET_PORTFOLIO_SUMMARY_TOOL_NAME:
            return get_project_portfolio_summary(args)
        if tool == GET_TOOL_NAME:
            return get_project_card(args)
        if tool == "turboproject.projects":
            return list_project_cards(args)
        return list_projects(args)
    except TurboProjectError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TurboProjectError(str(exc)) from exc

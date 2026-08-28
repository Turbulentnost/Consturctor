"""Server-side 1C OData / SQL tools (ported from jalko platform-tool-onec).

Runs in-process inside the Constructor backend. Desktop must not execute onec.*.
When ODATA_BASE_URL + credentials are set → real OData; otherwise → stub.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.services.docflow_tasks import (
    handle_docflow_tasks as _docflow_tasks,
    stub_docflow_tasks as _stub_docflow_tasks,
)
from app.services.erp_tasks import (
    ErpTaskError,
    handle_current as _erp_tasks_current,
    handle_period as _erp_tasks_period,
    handle_subordinate_tasks as _erp_subordinate_tasks,
    stub_current as _stub_erp_tasks_current,
    stub_period as _stub_erp_tasks_period,
    stub_subordinate_tasks as _stub_erp_subordinate_tasks,
)
from app.services.onec_security import (
    default_odata_entities,
    looks_like_odata_entity,
    odata_entity_allowlist,
    sql_table_allowlist,
    stub_odata_rows,
    validate_odata_entity,
    validate_odata_path,
    validate_sql_query,
)

_INCOMING_DOC_MARKERS = (
    "Document_ТД_ВходящаяКорреспонденция",
    "Document_ВходящаяКорреспонденция",
)
_TOP_RE = re.compile(r"\$top=(\d+)", re.IGNORECASE)
_SKIP_RE = re.compile(r"\$skip=(\d+)", re.IGNORECASE)
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ENTITYSET_NAME_RE = re.compile(r"<EntitySet\b[^>]*\bName=\"([^\"]+)\"", re.IGNORECASE)
_SUBJECT_KEYS = (
    "ТемаСлужебнойЗаписки",
    "Тема",
    "Subject",
    "Наименование",
    "Description",
    "ТемаСовещания",
    "Содержание",
    "Комментарий",
)
_ODATA_TYPE_PREFIX = "StandardODATA."
_MEETING_NOTE_ENTITY = "Document_ТД_СлужебнаяЗаписка"
_MEETING_NOTE_PARTICIPANTS = "Document_ТД_СлужебнаяЗаписка_СписокУчастников"
_MEETING_THEME_CATALOG = "Catalog_ТД_ТемыСлужебныхЗаписок"
_COLLECTION_HREF_RE = re.compile(r"<collection\b[^>]*\bhref=\"([^\"]+)\"", re.IGNORECASE)
_KIND_ALIASES = {
    "document": "document",
    "documents": "document",
    "документ": "document",
    "документы": "document",
    "catalog": "catalog",
    "catalogs": "catalog",
    "table": "catalog",
    "tables": "catalog",
    "таблица": "catalog",
    "таблицы": "catalog",
    "справочник": "catalog",
    "справочники": "catalog",
    "register": "register",
    "registers": "register",
    "регистр": "register",
    "регистры": "register",
    "other": "other",
    "прочее": "other",
}
_REGISTER_PREFIXES = (
    "InformationRegister_",
    "AccumulationRegister_",
    "AccountingRegister_",
    "CalculationRegister_",
)
_stub_counter = 0
_catalog_cache: list[dict[str, str]] | None = None

ONEC_TOOLS = frozenset(
    {
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
        "onec.sql_query",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
        "onec.docflow_tasks",
        "onec.meeting_service_notes",
    }
)
ONEC_WRITE_TOOLS = frozenset(
    {
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
    }
)
_ERP_TASK_TOOLS = frozenset(
    {
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
    }
)
_JWT_ONEC_TOOLS = _ERP_TASK_TOOLS | {"onec.docflow_tasks"}


class OnecToolError(RuntimeError):
    pass


def odata_configured() -> bool:
    has_url = bool(settings.odata_base_url.strip())
    has_creds = bool(
        (settings.erp_login.strip() and settings.erp_password.strip())
        or (settings.odata_username.strip() and settings.odata_password.strip())
    )
    return has_url and has_creds


def _erp_sql_ready() -> bool:
    return bool(
        settings.erp_sql_server
        and (
            settings.erp_sql_trusted_connection
            or (settings.erp_sql_user and settings.erp_sql_password)
        )
    )


def invoke_onec(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    actor_user_id: str = "",
    actor_fio: str = "",
) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    handlers = REAL_HANDLERS if odata_configured() else STUB_HANDLERS
    # sql_query / задачи работают от ERP SQL даже без OData URL
    if _erp_sql_ready() and not odata_configured():
        extra = {"onec.sql_query": _sql_query}
        extra.update({name: REAL_HANDLERS[name] for name in _ERP_TASK_TOOLS})
        handlers = {**STUB_HANDLERS, **extra}
    elif _erp_sql_ready():
        handlers = {**handlers, **{name: REAL_HANDLERS[name] for name in _ERP_TASK_TOOLS}}
    from app.services.docflow_tasks import docflow_configured

    if docflow_configured():
        handlers = {**handlers, "onec.docflow_tasks": REAL_HANDLERS["onec.docflow_tasks"]}
    handler = handlers.get(tool)
    if handler is None:
        raise OnecToolError(f"Неизвестный 1С-инструмент: {tool}")
    try:
        if tool in _JWT_ONEC_TOOLS:
            return handler(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
        return handler(args)
    except OnecToolError:
        raise
    except ErpTaskError as exc:
        raise OnecToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise OnecToolError(str(exc)) from exc


def _next_stub_id() -> int:
    global _stub_counter
    _stub_counter += 1
    return _stub_counter


def _is_incoming_correspondence_path(path: str) -> bool:
    return any(marker in path for marker in _INCOMING_DOC_MARKERS)


def _parse_top_limit(path: str, payload: dict[str, Any]) -> int:
    match = _TOP_RE.search(path)
    if match:
        return max(1, min(100, int(match.group(1))))
    raw_top = payload.get("top")
    if raw_top is not None:
        return max(1, min(100, int(raw_top)))
    return 3


def _parse_skip(path: str, payload: dict[str, Any]) -> int:
    """OData $skip — смещение (сколько записей пропустить)."""
    match = _SKIP_RE.search(path or "")
    if match:
        return max(0, min(100_000, int(match.group(1))))
    raw_skip = payload.get("skip")
    if raw_skip is not None:
        return max(0, min(100_000, int(raw_skip)))
    return 0


def _entity_set_name(raw: str) -> str:
    head = str(raw or "").strip().lstrip("/").split("?", 1)[0]
    if "(" in head:
        head = head.split("(", 1)[0]
    return head.strip()


def _is_keyed_odata_path(path: str) -> bool:
    head = str(path or "").strip().lstrip("/").split("?", 1)[0]
    lowered = head.casefold()
    if "(guid'" in lowered:
        return True
    return "(" in head and ")" in head


def _entity_from_args(args: dict[str, Any]) -> str:
    entity = _entity_set_name(str(args.get("entity", "")).strip())
    if entity:
        return entity
    path = str(args.get("path", "")).strip().lstrip("/")
    if not path:
        return ""
    head = path.split("?", 1)[0]
    if _is_incoming_correspondence_path(head):
        return (
            settings.odata_incoming_doc_entity
            or "Document_ТД_ВходящаяКорреспонденция"
        ).strip()
    return _entity_set_name(head)


def _looks_like_odata_entity(entity: str) -> bool:
    return looks_like_odata_entity(entity)


def _odata_allowlist() -> set[str] | None:
    return odata_entity_allowlist(settings.onec_odata_entity_allowlist)


def _odata_extra_entities(*, autoload: bool = True) -> set[str]:
    return set(_cached_catalog_names(autoload=autoload))


def _sql_allowlist() -> set[str]:
    return sql_table_allowlist(settings.onec_sql_allowlist)


def _build_list_path(entity: str, top: int, *, skip: int = 0) -> str:
    entity = entity.strip().lstrip("/")
    path = f"{entity}?$format=json&$top={top}"
    if skip > 0:
        path = f"{path}&$skip={skip}"
    return path


def _ensure_odata_query(
    path: str,
    *,
    top: int | None = None,
    skip: int | None = None,
) -> str:
    """1C OData: $format=json; пагинация через $top (лимит) и $skip (смещение)."""
    normalized = path.strip().lstrip("/")
    if "$format" not in normalized.lower():
        normalized = f"{normalized}{'&' if '?' in normalized else '?'}$format=json"
    if top is not None and "$top" not in normalized.lower():
        normalized = f"{normalized}&$top={top}"
    if skip is not None and skip > 0 and "$skip" not in normalized.lower():
        normalized = f"{normalized}&$skip={skip}"
    return normalized


def _payload_credentials(payload: dict[str, Any]) -> tuple[str, str] | None:
    username = str(
        payload.get("username") or payload.get("erp_login") or payload.get("user") or ""
    ).strip()
    password = str(payload.get("password") or payload.get("erp_password") or "").strip()
    if username and password:
        return username, password
    return None


def _odata_auth(args: dict[str, Any] | None = None) -> tuple[str, str] | None:
    payload = args or {}
    explicit = _payload_credentials(payload)
    if explicit:
        return explicit
    if settings.erp_login and settings.erp_password:
        return settings.erp_login, settings.erp_password
    if settings.odata_username and settings.odata_password:
        return settings.odata_username, settings.odata_password
    return None


def _parse_onec_http_error(response: httpx.Response) -> str:
    text = response.text.lstrip("\ufeff")
    try:
        data = json.loads(text)
        exc = data.get("exception")
        if isinstance(exc, dict):
            desc = str(exc.get("descr") or exc.get("desc") or "").strip()
            if desc:
                if response.status_code == 402:
                    return f"1C OData: неверный пользователь или пароль (HTTP 402). {desc}"
                return f"1C OData HTTP {response.status_code}: {desc}"
    except json.JSONDecodeError:
        pass
    if response.status_code == 402:
        return (
            "1C OData: неверный пользователь или пароль (HTTP 402). "
            "Укажите ERP_LOGIN/ERP_PASSWORD или ODATA_USERNAME/ODATA_PASSWORD в backend/.env."
        )
    return f"1C OData HTTP {response.status_code}: {text[:300]}"


def _nonempty_odata_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if text.startswith("00000000-0000-0000-0000-000000000000"):
        return False
    if text.startswith("0001-01-01"):
        return False
    return True


def _refresh_subject(row: dict[str, Any]) -> None:
    subject = _subject_from_row(row)
    if subject is not None:
        row["Subject"] = subject


def _catalog_entity_from_type(type_name: str) -> str:
    text = str(type_name or "").strip()
    if text.startswith(_ODATA_TYPE_PREFIX):
        text = text[len(_ODATA_TYPE_PREFIX) :]
    if looks_like_odata_entity(text):
        return text
    return ""


def _subject_from_row(row: dict[str, Any]) -> Any:
    fallback = None
    for key in _SUBJECT_KEYS:
        value = row.get(key)
        if not _nonempty_odata_value(value):
            continue
        if _GUID_RE.match(str(value).strip()):
            if fallback is None:
                fallback = value
            continue
        return value
    return fallback


def _odata_payload_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows = data.get("value")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if any(key in data for key in ("Ref_Key", "Number", "Date", "Posted", "Description")):
        return [data]
    return []


def _normalize_odata_row(row: dict[str, Any]) -> dict[str, Any]:
    extra = {
        key: value
        for key, value in row.items()
        if not str(key).startswith("odata.") and key not in {"odata.metadata"}
    }
    normalized = dict(extra)
    normalized["Ref_Key"] = row.get("Ref_Key")
    normalized["Number"] = row.get("Number") or row.get("Code")
    normalized["Date"] = row.get("Date") or row.get("Дата")
    normalized["Description"] = (
        row.get("Description")
        or row.get("Комментарий")
        or row.get("Наименование")
        or row.get("Содержание")
    )
    normalized["Posted"] = row.get("Posted")
    subject = _subject_from_row(row)
    if subject is not None:
        normalized["Subject"] = subject
    elif "Subject" not in normalized:
        normalized["Subject"] = None
    return normalized


def _normalize_odata_rows(data: Any) -> list[dict[str, Any]]:
    return [_normalize_odata_row(row) for row in _odata_payload_rows(data)]


def _append_odata_query(path: str, **params: str) -> str:
    cleaned = path.strip().lstrip("/")
    parts: list[str] = []
    for key, value in params.items():
        if not value:
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return cleaned
    sep = "&" if "?" in cleaned else "?"
    return f"{cleaned}{sep}{'&'.join(parts)}"


def _fetch_related_tabular_parts(
    entity: str,
    ref_key: str,
    args: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    if not entity or not _GUID_RE.match(ref_key):
        return {}
    prefix = f"{entity}_"
    names = [name for name in sorted(_cached_catalog_names()) if name.startswith(prefix)]
    parts: dict[str, list[dict[str, Any]]] = {}
    filter_expr = quote(f"Ref_Key eq guid'{ref_key}'", safe="=,'")
    for name in names[:12]:
        try:
            path = _append_odata_query(name, **{"$format": "json", "$top": "50", "$filter": filter_expr})
            raw = _odata_get(
                {
                    **{key: value for key, value in args.items() if key not in {"path", "entity", "top", "skip", "filter"}},
                    "path": path,
                }
            )
            payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            rows = _normalize_odata_rows(payload)
            if rows:
                parts[name] = rows
        except Exception:  # noqa: BLE001
            continue
    return parts


def _navigation_display_name(data: dict[str, Any]) -> str:
    for key in ("Description", "Наименование", "FullName", "DescriptionFull", "Code"):
        value = data.get(key)
        if _nonempty_odata_value(value) and not _GUID_RE.match(str(value).strip()):
            return str(value).strip()
    return ""


def _resolve_navigation_names(row: dict[str, Any], args: dict[str, Any], *, budget: int = 8) -> None:
    """Подставить ФИО/названия вместо GUID по @navigationLinkUrl."""
    creds = {
        key: value
        for key, value in args.items()
        if key in {"username", "password", "erp_login", "erp_password", "user"}
    }
    remaining = budget

    def resolve_catalog_guid(obj: dict[str, Any], key: str, guid: str) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        entity_name = _catalog_entity_from_type(str(obj.get(f"{key}_Type") or ""))
        if not entity_name:
            return
        try:
            raw = _odata_get({"path": f"{entity_name}(guid'{guid}')", **creds})
        except Exception:  # noqa: BLE001
            remaining -= 1
            return
        remaining -= 1
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        if not isinstance(data, dict):
            return
        name = _navigation_display_name(data)
        if not name:
            return
        obj[key] = name
        obj[f"{key}_Name"] = name

    def resolve_obj(obj: dict[str, Any]) -> None:
        nonlocal remaining
        for key, value in list(obj.items()):
            if remaining <= 0:
                return
            if str(key).endswith("_Type") or str(key).endswith("_Name"):
                continue
            text = str(value or "").strip()
            if (
                _GUID_RE.match(text)
                and obj.get(f"{key}_Type")
                and not str(key).endswith("_Key")
            ):
                resolve_catalog_guid(obj, key, text)
            if remaining <= 0:
                return
            if not str(key).endswith("@navigationLinkUrl"):
                continue
            path = str(value or "").strip().lstrip("/")
            if not path:
                continue
            try:
                raw = _odata_get({"path": path, **creds})
            except Exception:  # noqa: BLE001
                remaining -= 1
                continue
            remaining -= 1
            data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
            if not isinstance(data, dict):
                continue
            name = _navigation_display_name(data)
            if not name:
                continue
            field = key[: -len("@navigationLinkUrl")]
            obj[field] = name
            obj[f"{field}_Name"] = name

    resolve_obj(row)
    for value in list(row.values()):
        if remaining <= 0:
            break
        if isinstance(value, list):
            for item in value[:10]:
                if isinstance(item, dict):
                    resolve_obj(item)
        elif isinstance(value, dict) and value is not row.get("tabular_parts"):
            resolve_obj(value)
    parts = row.get("tabular_parts")
    if isinstance(parts, dict):
        for part_rows in parts.values():
            if remaining <= 0:
                break
            if not isinstance(part_rows, list):
                continue
            for item in part_rows[:10]:
                if isinstance(item, dict):
                    resolve_obj(item)
    _refresh_subject(row)


def _fetch_odata_list(args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path", "")).strip()
    entity = _entity_from_args(args)
    if not entity:
        raise OnecToolError("entity or path required")
    entity = validate_odata_entity(
        entity,
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    ref_key = str(args.get("ref_key") or args.get("Ref_Key") or "").strip()
    number = str(args.get("number") or args.get("Number") or "").strip()
    extra_filter = str(args.get("filter") or "").strip()
    top = _parse_top_limit(path, args)
    skip = _parse_skip(path, args)
    cleaned_path = path.strip().lstrip("/")
    keyed = _is_keyed_odata_path(cleaned_path)
    if number and args.get("top") is None and "$top" not in cleaned_path.lower():
        top = max(top, 20)
    if ref_key and not _GUID_RE.match(ref_key):
        raise OnecToolError("ref_key must be a GUID")
    if ref_key and not keyed:
        cleaned_path = f"{entity}(guid'{ref_key}')"
        keyed = True
    elif not cleaned_path:
        cleaned_path = entity

    if keyed:
        odata_path = _ensure_odata_query(cleaned_path)
    else:
        if cleaned_path.split("?", 1)[0] == entity:
            odata_path = _ensure_odata_query(cleaned_path, top=top, skip=skip)
        else:
            odata_path = _build_list_path(entity, top, skip=skip)
        filters: list[str] = []
        if extra_filter:
            filters.append(extra_filter)
        elif number:
            safe_number = number.replace("'", "''")
            filters.append(f"Number eq '{safe_number}'")
        if filters and "$filter" not in odata_path.lower():
            odata_path = _append_odata_query(
                odata_path,
                **{"$filter": quote(" and ".join(filters), safe="=,'")},
            )
        if (number or extra_filter) and entity.startswith("Document_") and "$orderby" not in odata_path.lower():
            odata_path = _append_odata_query(odata_path, **{"$orderby": "Date%20desc"})

    if not settings.odata_base_url:
        raise OnecToolError(
            "ODATA_BASE_URL не настроен. Добавьте ODATA_BASE_URL, "
            "ODATA_USERNAME/ODATA_PASSWORD (или ERP_LOGIN/ERP_PASSWORD) в backend/.env."
        )

    raw = _odata_get(
        {
            "path": odata_path,
            **{
                key: value
                for key, value in args.items()
                if key
                not in {
                    "path",
                    "entity",
                    "top",
                    "skip",
                    "filter",
                    "ref_key",
                    "Ref_Key",
                    "number",
                    "Number",
                }
            },
        }
    )
    payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    value = _normalize_odata_rows(payload)
    value.sort(key=lambda row: str(row.get("Date") or ""), reverse=True)
    tabular_parts: dict[str, list[dict[str, Any]]] = {}
    nav_suffix = cleaned_path.split(")", 1)[-1] if ")" in cleaned_path else ""
    is_navigation = keyed and nav_suffix.startswith("/")
    if value and not is_navigation:
        for row in value[:10]:
            _resolve_navigation_names(row, args, budget=2)
        card = value[0] if (keyed or number or extra_filter or len(value) == 1) else None
        if isinstance(card, dict):
            row_ref = str(card.get("Ref_Key") or ref_key or "").strip()
            tabular_parts = _fetch_related_tabular_parts(entity, row_ref, args)
            if tabular_parts:
                card["tabular_parts"] = tabular_parts
            _resolve_navigation_names(card, args, budget=8)
    numbers = [str(item.get("Number") or "") for item in value if item.get("Number")]
    summary = f"получено {len(value)} записей из 1С OData ({entity})"
    if numbers:
        summary += f": {', '.join(numbers)}"
    if tabular_parts:
        summary += f", табличные части: {', '.join(tabular_parts)}"
    result = {
        "summary": summary,
        "path": odata_path,
        "entity": entity,
        "count": len(value),
        "top": 1 if keyed else top,
        "skip": 0 if keyed else skip,
        "value": value,
        "source": "odata",
    }
    if tabular_parts:
        result["tabular_parts"] = tabular_parts
    return result


def _parse_note_day(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "")[:19]).date()
        except ValueError:
            return None
    return None


def _note_period(args: dict[str, Any]) -> tuple[date, date]:
    one = _parse_note_day(args.get("date"))
    start = _parse_note_day(args.get("date_from") or args.get("from"))
    end = _parse_note_day(args.get("date_to") or args.get("to"))
    if one and not start and not end:
        return one, one
    if start and not end:
        return start, start
    if end and not start:
        return end, end
    if start and end:
        if end < start:
            start, end = end, start
        return start, end
    today = date.today()
    return today, today


def _odata_datetime(day: date, *, end_of_day: bool = False) -> str:
    stamp = "23:59:59" if end_of_day else "00:00:00"
    return f"datetime'{day.isoformat()}T{stamp}'"


def _is_meeting_service_theme(text: str) -> bool:
    low = " ".join(str(text or "").split()).casefold()
    if not low:
        return False
    if "организация совещаний" in low:
        return True
    return "совеща" in low and "организац" in low


def _odata_creds(args: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in args.items()
        if key in {"username", "password", "erp_login", "erp_password", "user"}
    }


def _meeting_theme_keys(args: dict[str, Any]) -> list[str]:
    try:
        raw = _fetch_odata_list(
            {
                "entity": _MEETING_THEME_CATALOG,
                "filter": "DeletionMark eq false",
                "top": 80,
                **_odata_creds(args),
            }
        )
    except Exception:  # noqa: BLE001
        return []
    keys: list[str] = []
    for row in raw.get("value") or []:
        if not isinstance(row, dict):
            continue
        desc = str(row.get("Description") or row.get("Наименование") or "")
        if not _is_meeting_service_theme(desc):
            continue
        key = str(row.get("Ref_Key") or "").strip()
        if key and _GUID_RE.match(key):
            keys.append(key)
    return keys


def _note_participants(ref: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    if not ref or not _GUID_RE.match(ref):
        return []
    try:
        raw = _fetch_odata_list(
            {
                "entity": _MEETING_NOTE_PARTICIPANTS,
                "filter": f"Ref_Key eq guid'{ref}'",
                "top": 50,
                **_odata_creds(args),
            }
        )
        rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
        if rows:
            return rows
    except Exception:  # noqa: BLE001
        pass
    extra = _fetch_related_tabular_parts(_MEETING_NOTE_ENTITY, ref, args)
    parts = extra.get(_MEETING_NOTE_PARTICIPANTS) or []
    return [row for row in parts if isinstance(row, dict)]


def _note_from_odata_row(row: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
    theme = str(row.get("ТемаСлужебнойЗаписки_Name") or row.get("Subject") or row.get("ТемаСлужебнойЗаписки") or "")
    if _GUID_RE.match(theme.strip()):
        theme = str(row.get("Subject") or "")
    topic = str(row.get("ТемаСовещания_Name") or row.get("ТемаСовещания") or "")
    if _GUID_RE.match(topic.strip()):
        topic = ""
    place = str(row.get("МестоПроведенияСовещания_Name") or row.get("МестоПроведенияСовещания") or "")
    if _GUID_RE.match(place.strip()):
        place = ""
    people = []
    for item in participants:
        name = str(
            item.get("Участник_Name")
            or item.get("Участник")
            or item.get("Description")
            or ""
        ).strip()
        if name and not _GUID_RE.match(name):
            people.append(name)
    return {
        "document_type": "Служебная записка",
        "metadata_name": "ТД_СлужебнаяЗаписка",
        "ref": str(row.get("Ref_Key") or ""),
        "number": str(row.get("Number") or ""),
        "date": str(row.get("Date") or ""),
        "theme": theme,
        "meeting_topic": topic,
        "place": place,
        "participants": people,
        "meeting": {
            "topic": topic,
            "place": place,
            "desired_date": str(row.get("ЖелаемаяДатаПроведенияСовещания") or ""),
            "meeting_date": str(row.get("ДатаПроведенияСовещания") or ""),
            "start_time": str(row.get("ВремяНачалаСовещания") or ""),
            "end_time": str(row.get("ВремяОкончанияСовещания") or ""),
        },
    }


def _list_meeting_service_notes_odata(args: dict[str, Any]) -> dict[str, Any]:
    """Служебные записки на совещания через OData — без COM."""
    start, end = _note_period(args)
    limit = max(1, min(200, int(args.get("max_results") or args.get("limit") or 50)))
    date_filter = (
        f"DeletionMark eq false and Date ge {_odata_datetime(start)} "
        f"and Date le {_odata_datetime(end, end_of_day=True)}"
    )
    theme_keys = _meeting_theme_keys(args)
    if theme_keys:
        theme_clause = " or ".join(f"ТемаСлужебнойЗаписки eq guid'{key}'" for key in theme_keys[:8])
        date_filter = f"{date_filter} and ({theme_clause})"
    try:
        raw = _fetch_odata_list(
            {
                "entity": _MEETING_NOTE_ENTITY,
                "filter": date_filter,
                "top": min(100, max(limit, 20)),
                **_odata_creds(args),
            }
        )
    except OnecToolError as exc:
        return {
            "notes": [],
            "count": 0,
            "source": "odata",
            "readonly": True,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "theme": "организация совещаний",
            "entity": _MEETING_NOTE_ENTITY,
            "method": "odata_meeting_service_notes",
            "error": str(exc),
            "hint": (
                "OData не отдал Document_ТД_СлужебнаяЗаписка. "
                "Проверьте права учётки OData на этот документ "
                "или читайте его через onec.odata_get, если доступ появится."
            ),
        }
    rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
    notes: list[dict[str, Any]] = []
    for row in rows:
        theme = str(row.get("ТемаСлужебнойЗаписки_Name") or row.get("Subject") or "")
        topic = str(row.get("ТемаСовещания_Name") or row.get("ТемаСовещания") or "")
        if theme and not _is_meeting_service_theme(theme) and not _is_meeting_service_theme(topic):
            if not row.get("ТемаСовещания") and not row.get("ЖелаемаяДатаПроведенияСовещания"):
                continue
        ref = str(row.get("Ref_Key") or "").strip()
        parts = row.get("tabular_parts") if isinstance(row.get("tabular_parts"), dict) else {}
        participants = parts.get(_MEETING_NOTE_PARTICIPANTS) or []
        if not participants:
            participants = _note_participants(ref, args)
        notes.append(_note_from_odata_row(row, participants if isinstance(participants, list) else []))
        if len(notes) >= limit:
            break
    return {
        "notes": notes,
        "count": len(notes),
        "source": "odata",
        "readonly": True,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "theme": "организация совещаний",
        "entity": _MEETING_NOTE_ENTITY,
        "path": raw.get("path"),
        "method": "odata_meeting_service_notes",
    }


def _stub_meeting_service_notes(args: dict[str, Any]) -> dict[str, Any]:
    start, end = _note_period(args)
    return {
        "notes": [],
        "count": 0,
        "source": "stub",
        "readonly": True,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "theme": "организация совещаний",
        "note": "OData 1С не настроена — живые служебные записки не прочитаны.",
    }


def _odata_get_dispatch(args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity_from_args(args)
    path = str(args.get("path", ""))
    if (
        _is_incoming_correspondence_path(path)
        or _looks_like_odata_entity(entity)
        or entity in _odata_extra_entities()
    ):
        return _fetch_odata_list(args)
    return _odata_get(args)


def _stub_odata_get(args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity_from_args(args)
    path = str(args.get("path", ""))
    if (
        _is_incoming_correspondence_path(path)
        or _looks_like_odata_entity(entity)
        or entity in _odata_extra_entities()
    ):
        if not entity:
            raise OnecToolError("entity or path required")
        entity = validate_odata_entity(
            entity,
            allowlist=_odata_allowlist(),
            extra_allowed=_odata_extra_entities(),
        )
        top = _parse_top_limit(path, args)
        return stub_odata_rows(entity, top)
    path_clean = path.strip().lstrip("/")
    if path_clean:
        validate_odata_path(
            path_clean,
            allowlist=_odata_allowlist(),
            extra_allowed=_odata_extra_entities(),
        )
    return {
        "summary": "stub odata get",
        "path": path,
        "value": [{"Ref_Key": "00000000-0000-0000-0000-000000000001"}],
        "source": "stub",
    }


def _stub_odata_post(args: dict[str, Any]) -> dict[str, Any]:
    n = _next_stub_id()
    return {
        "summary": f"stub document {n}",
        "erp_document_number": f"ВК-STUB-{n:06d}",
        "erp_document_id": f"11111111-1111-1111-1111-{n:012d}"[:36],
        "source": "stub",
    }


def _stub_odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "stub patch ok",
        "updated": True,
        "ref_key": args.get("ref_key"),
        "source": "stub",
    }


def _stub_attach_file(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "stub attach",
        "ref_key": args.get("document_ref_key"),
        "filename": args.get("filename", "file.pdf"),
        "source": "stub",
    }


def _stub_sql_query(args: dict[str, Any]) -> dict[str, Any]:
    sql = validate_sql_query(str(args.get("sql", "")), allowlist=_sql_allowlist())
    return {
        "summary": "stub sql",
        "sql": sql,
        "rows": [{"id": 1, "name": "stub"}],
        "source": "stub",
    }


def _odata_url(path: str) -> str:
    base = settings.odata_base_url.rstrip("/")
    cleaned = path.lstrip("/")
    safe = "/()'=,:$"
    if "?" in cleaned:
        head, query = cleaned.split("?", 1)
        return f"{base}/{quote(head, safe=safe)}?{query}"
    return f"{base}/{quote(cleaned, safe=safe)}"


def _odata_get(args: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path", ""))
    path = validate_odata_path(
        raw_path,
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    keyed = _is_keyed_odata_path(raw_path)
    top = None if keyed else (_parse_top_limit(raw_path, args) if raw_path else None)
    skip = None if keyed else (_parse_skip(raw_path, args) if raw_path else None)
    path = _ensure_odata_query(
        path,
        top=top if top is not None and "$top" not in path.lower() else None,
        skip=skip if skip and "$skip" not in path.lower() else None,
    )
    if not settings.odata_base_url:
        raise OnecToolError("ODATA_BASE_URL not configured")
    auth = _odata_auth(args)
    if not auth:
        raise OnecToolError(
            "OData credentials not configured: set ERP_LOGIN/ERP_PASSWORD "
            "или ODATA_USERNAME/ODATA_PASSWORD"
        )
    url = _odata_url(path)
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OnecToolError(_parse_onec_http_error(response))
        data = response.json()
    return {"summary": "odata get ok", "path": path, "data": data, "source": "odata"}


def _odata_post(args: dict[str, Any]) -> dict[str, Any]:
    entity = validate_odata_entity(
        str(args.get("entity", "")),
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    body = args.get("body") or {}
    if not settings.odata_base_url:
        raise OnecToolError("ODATA_BASE_URL not configured")
    auth = _odata_auth(args)
    if not auth:
        raise OnecToolError("OData credentials not configured")
    url = _odata_url(entity)
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.post(url, json=body, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OnecToolError(_parse_onec_http_error(response))
        data = response.json()
    return {
        "summary": "odata post ok",
        "erp_document_id": data.get("Ref_Key") or data.get("ref_key"),
        "data": data,
        "source": "odata",
    }


def _odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    entity = validate_odata_entity(
        str(args.get("entity", "")),
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    ref_key = str(args.get("ref_key", "")).strip()
    body = args.get("body") or {}
    if not ref_key:
        raise OnecToolError("ref_key required")
    url = _odata_url(f"{entity}(guid'{ref_key}')")
    auth = _odata_auth(args)
    if not auth:
        raise OnecToolError("OData credentials not configured")
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.patch(url, json=body, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OnecToolError(_parse_onec_http_error(response))
    return {"summary": "odata patch ok", "updated": True, "ref_key": ref_key, "source": "odata"}


def _attach_file(_args: dict[str, Any]) -> dict[str, Any]:
    raise OnecToolError(
        "NOT_IMPLEMENTED: onec.attach_file требует OData file upload — пока недоступно. "
        "Используйте onec.odata_patch для метаданных или прикрепите файл вручную в 1С."
    )


def _build_connection_string() -> str:
    parts = [
        f"DRIVER={{{settings.erp_sql_driver}}}",
        f"SERVER={settings.erp_sql_server}",
        f"DATABASE={settings.erp_sql_database}",
        f"Encrypt={settings.erp_sql_encrypt}",
        "TrustServerCertificate=yes",
    ]
    if settings.erp_sql_trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={settings.erp_sql_user}")
        parts.append(f"PWD={settings.erp_sql_password}")
    return ";".join(parts) + ";"


def _sql_query(args: dict[str, Any]) -> dict[str, Any]:
    try:
        import pyodbc
    except ImportError as exc:
        raise OnecToolError("pyodbc не установлен") from exc
    sql = validate_sql_query(str(args.get("sql", "")), allowlist=_sql_allowlist())
    conn = pyodbc.connect(_build_connection_string(), autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        columns = [col[0] for col in cur.description] if cur.description else []
        rows = []
        for row in cur.fetchmany(100):
            rows.append({columns[i]: row[i] for i in range(len(columns))})
    finally:
        conn.close()
    return {"summary": f"rows={len(rows)}", "rows": rows, "source": "sql"}


def _classify_odata_entity(name: str) -> str:
    if name.startswith("Document_"):
        return "document"
    if name.startswith("Catalog_"):
        return "catalog"
    if name.startswith(_REGISTER_PREFIXES):
        return "register"
    return "other"


def _entity_prefix(name: str) -> str:
    for prefix in (
        "InformationRegister_",
        "AccumulationRegister_",
        "AccountingRegister_",
        "CalculationRegister_",
        "ChartOfCharacteristicTypes_",
        "ChartOfAccounts_",
        "ChartOfCalculationTypes_",
        "BusinessProcess_",
        "ExchangePlan_",
        "Document_",
        "Catalog_",
        "Constant_",
        "Task_",
        "Enum_",
    ):
        if name.startswith(prefix):
            return prefix.rstrip("_")
    return ""


def _catalog_item(name: str) -> dict[str, str] | None:
    cleaned = str(name or "").strip().lstrip("/").split("?", 1)[0]
    cleaned = cleaned.split("(", 1)[0]
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    if not cleaned or cleaned.startswith("$"):
        return None
    return {
        "name": cleaned,
        "kind": _classify_odata_entity(cleaned),
        "prefix": _entity_prefix(cleaned),
    }


def _stub_catalog_items() -> list[dict[str, str]]:
    names = list(default_odata_entities()) + [
        "Catalog_Контрагенты",
        "AccumulationRegister_Остатки",
        "InformationRegister_КурсыВалют",
    ]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        item = _catalog_item(name)
        if item is None or item["name"] in seen:
            continue
        seen.add(item["name"])
        items.append(item)
    return items


def _names_from_service_document(data: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(data, dict):
        return names
    value = data.get("value")
    if not isinstance(value, list):
        return names
    for item in value:
        if isinstance(item, dict):
            raw = str(item.get("name") or item.get("url") or "").strip()
        elif isinstance(item, str):
            raw = item.strip()
        else:
            continue
        if raw:
            names.append(raw)
    return names


def _names_from_metadata_xml(text: str) -> list[str]:
    names = [match.group(1) for match in _ENTITYSET_NAME_RE.finditer(text)]
    if names:
        return names
    return [match.group(1) for match in _COLLECTION_HREF_RE.finditer(text)]


def _items_from_names(names: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        item = _catalog_item(name)
        if item is None or item["name"] in seen:
            continue
        seen.add(item["name"])
        items.append(item)
    items.sort(key=lambda row: (row["kind"], row["name"]))
    return items


def _cached_catalog_names(*, autoload: bool = True) -> set[str]:
    global _catalog_cache
    if _catalog_cache is None and autoload:
        try:
            if odata_configured():
                _load_odata_catalog()
            else:
                _catalog_cache = _stub_catalog_items()
        except Exception:  # noqa: BLE001
            return set()
    if not _catalog_cache:
        return set()
    return {item["name"] for item in _catalog_cache}


def _load_odata_catalog(*, force: bool = False) -> list[dict[str, str]]:
    global _catalog_cache
    if _catalog_cache is not None and not force:
        return _catalog_cache
    if not settings.odata_base_url:
        raise OnecToolError("ODATA_BASE_URL not configured")
    auth = _odata_auth()
    if not auth:
        raise OnecToolError(
            "OData credentials not configured: set ERP_LOGIN/ERP_PASSWORD "
            "или ODATA_USERNAME/ODATA_PASSWORD"
        )
    names: list[str] = []
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        service_url = settings.odata_base_url.rstrip("/")
        response = client.get(
            service_url,
            params={"$format": "json"},
            headers={"Accept": "application/json"},
        )
        if response.status_code < 400:
            try:
                names = _names_from_service_document(response.json())
            except json.JSONDecodeError:
                names = []
        if not names:
            meta = client.get(
                _odata_url("$metadata"),
                headers={"Accept": "application/xml"},
            )
            if meta.status_code >= 400:
                raise OnecToolError(_parse_onec_http_error(meta))
            names = _names_from_metadata_xml(meta.text)
    if not names:
        raise OnecToolError("1C OData: пустой каталог сущностей (service document / $metadata)")
    _catalog_cache = _items_from_names(names)
    return _catalog_cache


def _normalize_kind_filter(raw: str) -> str:
    return _KIND_ALIASES.get(raw.strip().casefold(), "")


def _format_catalog(
    items: list[dict[str, str]],
    args: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    kind = _normalize_kind_filter(str(args.get("kind") or args.get("type") or ""))
    search = str(args.get("search") or args.get("query") or "").strip().casefold()
    try:
        limit = int(args.get("limit") or 400)
    except (TypeError, ValueError):
        limit = 400
    limit = max(1, min(2000, limit))

    filtered = items
    if kind:
        filtered = [item for item in filtered if item["kind"] == kind]
    if search:
        filtered = [item for item in filtered if search in item["name"].casefold()]
    truncated = filtered[:limit]

    documents = [item["name"] for item in truncated if item["kind"] == "document"]
    catalogs = [item["name"] for item in truncated if item["kind"] == "catalog"]
    registers = [item["name"] for item in truncated if item["kind"] == "register"]
    other = [item["name"] for item in truncated if item["kind"] == "other"]
    summary = (
        f"OData каталог: {len(documents)} документов, "
        f"{len(catalogs)} справочников/таблиц, {len(registers)} регистров"
    )
    if other and not kind:
        summary += f", {len(other)} прочих"
    if search or kind:
        summary += f" (показано {len(truncated)} из {len(filtered)})"
    return {
        "summary": summary,
        "source": source,
        "count": len(truncated),
        "total_matched": len(filtered),
        "kind": kind or "all",
        "search": search,
        "documents": documents,
        "catalogs": catalogs,
        "registers": registers,
        "other": other,
        "entities": truncated,
    }


def _odata_catalog(args: dict[str, Any]) -> dict[str, Any]:
    force = bool(args.get("refresh") or args.get("force"))
    items = _load_odata_catalog(force=force)
    return _format_catalog(items, args, source="odata")


def _stub_odata_catalog(args: dict[str, Any]) -> dict[str, Any]:
    global _catalog_cache
    items = _stub_catalog_items()
    if _catalog_cache is None:
        _catalog_cache = items
    return _format_catalog(items, args, source="stub")


STUB_HANDLERS = {
    "onec.odata_catalog": _stub_odata_catalog,
    "onec.odata_get": _stub_odata_get,
    "onec.odata_post": _stub_odata_post,
    "onec.odata_patch": _stub_odata_patch,
    "onec.attach_file": _stub_attach_file,
    "onec.sql_query": _stub_sql_query,
    "onec.erp_tasks_current": _stub_erp_tasks_current,
    "onec.erp_tasks_period": _stub_erp_tasks_period,
    "onec.erp_subordinate_tasks": _stub_erp_subordinate_tasks,
    "onec.docflow_tasks": _stub_docflow_tasks,
    "onec.meeting_service_notes": _stub_meeting_service_notes,
}

REAL_HANDLERS = {
    "onec.odata_catalog": _odata_catalog,
    "onec.odata_get": _odata_get_dispatch,
    "onec.odata_post": _odata_post,
    "onec.odata_patch": _odata_patch,
    "onec.attach_file": _attach_file,
    "onec.sql_query": _sql_query,
    "onec.erp_tasks_current": _erp_tasks_current,
    "onec.erp_tasks_period": _erp_tasks_period,
    "onec.erp_subordinate_tasks": _erp_subordinate_tasks,
    "onec.docflow_tasks": _docflow_tasks,
    "onec.meeting_service_notes": _list_meeting_service_notes_odata,
}

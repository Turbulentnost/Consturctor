"""Открытые задачи пользователя из 1С:Документооборота (HTTP SOAP dm.1cws).

Автономный клиент: стандартная библиотека Python.
Хост — DOK_HTTP_SERVER/PORT (есть значения по умолчанию).
SOAP Basic: если desktop передал логин и пароль сеанса — только они
(без ODATA_* / DOK_HTTP_*). Для CLI-дампа без сеанса — сервисные пары
DOK_HTTP_* → DOCFLOW_ODATA_* → ODATA_* → ERP_*.
ФИО сеанса режет дамп (исполнитель/автор).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)
_DEFAULT_LIST_TIMEOUT_SEC = 210.0
_DEFAULT_CACHE_TTL_SEC = 1800.0
_cache_guard = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_inbox_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_refreshing: set[str] = set()

DM_NS = "http://www.1c.ru/dm"
NS = {"m": DM_NS}
SOAP_ACTION = "http://www.1c.ru/dm#DMService:execute"
EMPTY_DATE_PREFIX = "0001-01-01"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


@dataclass(frozen=True)
class DokConfig:
    server: str
    port: int
    user: str
    password: str
    timeout: float
    base_path: str
    encoding: str = "utf-8"

    def soap_url(self) -> str:
        return f"http://{self.server}:{self.port}{self.base_path}/ws/dm.1cws"

    def with_encoding(self, encoding: str) -> "DokConfig":
        if encoding == self.encoding:
            return self
        return DokConfig(
            server=self.server,
            port=self.port,
            user=self.user,
            password=self.password,
            timeout=self.timeout,
            base_path=self.base_path,
            encoding=encoding,
        )

    def auth_header(self) -> str:
        token = base64.b64encode(f"{self.user}:{self.password}".encode(self.encoding)).decode("ascii")
        return f"Basic {token}"


def _strip_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = _strip_env_value(raw)
    return values


def discover_env_files(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit)]
    here = Path(__file__).resolve()
    cwd = Path.cwd()
    candidates = [
        cwd / ".env",
        here.parent / ".env",
    ]
    for parent in here.parents:
        candidates.append(parent / ".env")
        candidates.append(parent / "infrastructure" / ".env")
        if parent.name in {"backend", "NewConstructor"}:
            break
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def env_get(files: list[dict[str, str]], key: str, default: str = "") -> str:
    if key in os.environ and str(os.environ[key]).strip():
        return str(os.environ[key]).strip()
    for mapping in files:
        value = str(mapping.get(key) or "").strip()
        if value:
            return value
    return default


def _settings_mapping() -> dict[str, str]:
    try:
        from app.config import settings
    except Exception:
        return {}
    return {
        "DOK_HTTP_SERVER": str(getattr(settings, "dok_http_server", "") or "").strip(),
        "DOK_HTTP_PORT": str(getattr(settings, "dok_http_port", "") or "").strip(),
        "DOK_HTTP_USER": str(getattr(settings, "dok_http_user", "") or "").strip(),
        "DOK_HTTP_PASSWORD": str(getattr(settings, "dok_http_password", "") or "").strip(),
        "DOK_HTTP_TIMEOUT": str(getattr(settings, "dok_http_timeout", "") or "").strip(),
        "DOK_HTTP_BASE_PATH": str(getattr(settings, "dok_http_base_path", "") or "").strip(),
        "DOCFLOW_ODATA_USERNAME": str(getattr(settings, "docflow_odata_username", "") or "").strip(),
        "DOCFLOW_ODATA_PASSWORD": str(getattr(settings, "docflow_odata_password", "") or "").strip(),
        "ODATA_USERNAME": str(getattr(settings, "odata_username", "") or "").strip(),
        "ODATA_PASSWORD": str(getattr(settings, "odata_password", "") or "").strip(),
        "ERP_LOGIN": str(getattr(settings, "erp_login", "") or "").strip(),
        "ERP_PASSWORD": str(getattr(settings, "erp_password", "") or "").strip(),
    }


_SOAP_CREDENTIAL_PAIRS = (
    ("DOK_HTTP_USER", "DOK_HTTP_PASSWORD"),
    ("DOCFLOW_ODATA_USERNAME", "DOCFLOW_ODATA_PASSWORD"),
    ("ODATA_USERNAME", "ODATA_PASSWORD"),
    ("ERP_LOGIN", "ERP_PASSWORD"),
)


def _pick_soap_credentials(loaded: list[dict[str, str]]) -> tuple[str, str]:
    """Service account for SOAP Basic when the session did not send a password."""
    for user_key, pass_key in _SOAP_CREDENTIAL_PAIRS:
        user = env_get(loaded, user_key)
        secret = env_get(loaded, pass_key)
        if user and secret:
            return user, secret
    return "", ""


def load_config(
    *,
    env_file: str | None = None,
    username: str | None = None,
    password: str | None = None,
    require_user: bool = True,
) -> DokConfig:
    # Документооборот /doc принимает учётку 1С (обычно ФИО + пароль сеанса).
    # ODATA_* — erp_pm, на dm.1cws часто даёт HTTP 401.
    session_user = (username or "").strip()
    session_secret = (password or "").strip()
    loaded = [load_env_file(path) for path in discover_env_files(env_file)]
    settings_map = _settings_mapping()
    if any(settings_map.values()):
        loaded.append(settings_map)
    server = env_get(loaded, "DOK_HTTP_SERVER", "192.168.2.229")
    # Desktop session: never substitute OData / .env service account.
    if session_user or session_secret:
        user, secret = session_user, session_secret
    else:
        user, secret = _pick_soap_credentials(loaded)
    if not server:
        raise RuntimeError("Задайте DOK_HTTP_SERVER в окружении или .env")
    if require_user and not user:
        raise RuntimeError(
            "Документооборот SOAP: нет пользователя. Войдите с паролем 1С."
        )
    if require_user and not secret:
        raise RuntimeError(
            "Документооборот SOAP: нет пароля. Войдите с паролем 1С."
        )
    return DokConfig(
        server=server,
        port=int(env_get(loaded, "DOK_HTTP_PORT", "81") or "81"),
        user=user,
        password=secret,
        timeout=float(env_get(loaded, "DOK_HTTP_TIMEOUT", "210") or "210"),
        base_path=(env_get(loaded, "DOK_HTTP_BASE_PATH", "/doc") or "/doc").rstrip("/") or "/doc",
    )


def soap_configured(*, env_file: str | None = None) -> bool:
    """Host plus a service credential pair (DOK_HTTP_*, DOCFLOW_ODATA_*, ODATA_*, ERP_*)."""
    try:
        config = load_config(env_file=env_file, require_user=False)
    except (RuntimeError, ValueError, OSError):
        return False
    return bool(config.server and config.user and config.password)


def decode_body(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def envelope(request_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:dm="{DM_NS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        f"<soap:Body><dm:execute>{request_xml}</dm:execute></soap:Body></soap:Envelope>"
    )


def condition(property_name: str, value_xml: str, operator: str | None = None) -> str:
    op_xml = (
        f"<dm:comparisonOperator>{xml_escape(operator)}</dm:comparisonOperator>"
        if operator
        else ""
    )
    return (
        "<dm:conditions>"
        f"<dm:property>{xml_escape(property_name)}</dm:property>"
        f"{value_xml}{op_xml}"
        "</dm:conditions>"
    )


def string_value(value: str) -> str:
    return f'<dm:value xsi:type="xs:string">{xml_escape(value)}</dm:value>'


def bool_value(value: bool) -> str:
    return f'<dm:value xsi:type="xs:boolean">{"true" if value else "false"}</dm:value>'


def datetime_value(value: datetime) -> str:
    return f'<dm:value xsi:type="xs:dateTime">{value.strftime("%Y-%m-%dT%H:%M:%S")}</dm:value>'


def object_id_value(object_id: str, type_name: str = "DMUser") -> str:
    return (
        '<dm:value xsi:type="dm:DMObjectID">'
        f"<dm:id>{xml_escape(object_id)}</dm:id>"
        f"<dm:type>{xml_escape(type_name)}</dm:type>"
        "</dm:value>"
    )


def performer_value(user: dict[str, str]) -> str:
    type_name = user.get("type") or "DMUser"
    return (
        '<dm:value xsi:type="dm:DMBusinessProcessTaskExecutor">'
        "<dm:user>"
        f"<dm:name>{xml_escape(user.get('name') or '')}</dm:name>"
        "<dm:objectID>"
        f"<dm:id>{xml_escape(user.get('id') or '')}</dm:id>"
        f"<dm:type>{xml_escape(type_name)}</dm:type>"
        "</dm:objectID>"
        "</dm:user>"
        "</dm:value>"
    )


def _dump_cache_key(
    endpoint: str,
    only_open: bool,
    soap_user: str = "",
    soap_secret: str = "",
) -> str:
    secret_fp = hashlib.sha256(soap_secret.encode("utf-8")).hexdigest()[:16] if soap_secret else ""
    return f"dump|{endpoint}|{int(only_open)}|{soap_user}|{secret_fp}"


def _lock_for(key: str) -> threading.Lock:
    with _cache_guard:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def _cache_ttl_sec() -> float:
    try:
        from app.config import settings

        return max(60.0, float(getattr(settings, "dok_http_cache_ttl_sec", 0) or _DEFAULT_CACHE_TTL_SEC))
    except Exception:
        return _DEFAULT_CACHE_TTL_SEC


def _cache_dir() -> Path:
    try:
        from app.config import settings

        path = Path(getattr(settings, "dok_inbox_cache_dir", "") or "")
        if path:
            path.mkdir(parents=True, exist_ok=True)
            return path
    except Exception:
        pass
    path = Path(__file__).resolve().parents[3] / "storage" / "docflow_inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
    return _cache_dir() / f"{digest}.json"


def _read_disk_cache(key: str) -> tuple[float, dict[str, Any]] | None:
    path = _cache_path(key)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    payload = data.get("payload") if isinstance(data, dict) else None
    fetched_at = data.get("fetched_at") if isinstance(data, dict) else None
    if not isinstance(payload, dict) or not fetched_at:
        return None
    return float(fetched_at), payload


def _write_disk_cache(key: str, fetched_at: float, payload: dict[str, Any]) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = {k: v for k, v in payload.items() if k not in {"cached", "cached_at"}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"fetched_at": fetched_at, "payload": stored}, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _cache_entry(key: str) -> tuple[float, dict[str, Any]] | None:
    hit = _inbox_cache.get(key)
    if hit:
        return hit
    disk = _read_disk_cache(key)
    if disk:
        _inbox_cache[key] = disk
    return disk


def _store_cache(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    fetched_at = time.time()
    stored = {k: v for k, v in payload.items() if k not in {"cached", "cached_at"}}
    _inbox_cache[key] = (fetched_at, stored)
    try:
        _write_disk_cache(key, fetched_at, stored)
    except OSError as exc:
        logger.warning("dok_soap cache write failed: %s", exc)
    return _with_cache_meta(stored, cached=False, fetched_at=fetched_at)


def _with_cache_meta(payload: dict[str, Any], *, cached: bool, fetched_at: float) -> dict[str, Any]:
    out = dict(payload)
    out["cached"] = cached
    out["cached_at"] = datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d %H:%M:%S")
    return out


def _schedule_refresh(
    key: str,
    *,
    only_open: bool,
    env_file: str | None,
    username: str | None,
    password: str | None,
) -> None:
    with _cache_guard:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _run() -> None:
        try:
            config = load_config(env_file=env_file, username=username, password=password)
            _store_cache(key, fetch_open_dump(config, only_open=only_open))
        except Exception as exc:  # noqa: BLE001 — background refresh must not crash
            logger.warning("dok_soap background refresh failed: %s", exc)
        finally:
            with _cache_guard:
                _refreshing.discard(key)

    threading.Thread(target=_run, name="dok-soap-refresh", daemon=True).start()


def soap_timeout_message(timeout: float) -> str:
    return f"Документооборот SOAP: нет ответа за {int(timeout)} с"


def _is_timeout_reason(reason: object) -> bool:
    text = str(reason or "").lower()
    return "timed out" in text or "timeout" in text


def _auth_encodings(config: DokConfig) -> list[str]:
    blob = f"{config.user}{config.password}"
    if not any(ord(ch) > 127 for ch in blob):
        return [config.encoding]
    seen: list[str] = []
    for encoding in (config.encoding, "utf-8", "cp1251"):
        if encoding not in seen:
            seen.append(encoding)
    return seen


def _execute_dm_once(config: DokConfig, request_xml: str, *, timeout: float) -> ET.Element:
    body = envelope(request_xml).encode("utf-8")
    request = Request(
        config.soap_url(),
        data=body,
        method="POST",
        headers={
            "Authorization": config.auth_header(),
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SOAP_ACTION,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            text = decode_body(response.read())
            status = getattr(response, "status", 200)
    except HTTPError as error:
        text = decode_body(error.read() or b"")
        if error.code in {401, 402, 403}:
            raise RuntimeError(
                f"HTTP {error.code}: Документооборот отклонил Basic-учётку"
            ) from error
        raise RuntimeError(f"HTTP {error.code}: {text[:800]}") from error
    except TimeoutError as error:
        raise RuntimeError(soap_timeout_message(timeout)) from error
    except URLError as error:
        if _is_timeout_reason(error.reason):
            raise RuntimeError(soap_timeout_message(timeout)) from error
        raise RuntimeError(f"Нет связи с ДО: {error.reason}") from error
    if status > 299:
        raise RuntimeError(f"HTTP {status}: {text[:800]}")

    root = ET.fromstring(text)
    for node in root.findall(".//m:return", NS):
        type_name = node.attrib.get(XSI_TYPE, "")
        if type_name.endswith("DMError"):
            subject = node.findtext("m:subject", default="", namespaces=NS)
            description = node.findtext("m:description", default="", namespaces=NS)
            raise RuntimeError(f"{subject}: {description}".strip(": "))
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        raise RuntimeError(fault.findtext("faultstring") or text[:800])
    return root


def execute_dm(config: DokConfig, request_xml: str, *, timeout: float) -> ET.Element:
    last_error: RuntimeError | None = None
    for encoding in _auth_encodings(config):
        try:
            return _execute_dm_once(config.with_encoding(encoding), request_xml, timeout=timeout)
        except RuntimeError as error:
            last_error = error
            if _is_soap_http_auth_error(str(error)):
                continue
            raise
        except (LookupError, UnicodeEncodeError):
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("Документооборот отклонил Basic-учётку")


def _is_soap_http_auth_error(text: str) -> bool:
    return bool(re.search(r"\bHTTP\s*40[123]\b", text or "", flags=re.I))


def xml_text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def parse_users(root: ET.Element) -> list[dict[str, str]]:
    users: list[dict[str, str]] = []
    for item in root.findall(".//m:items", NS):
        obj = item.find("m:object", NS)
        if obj is None:
            continue
        user_id = xml_text(obj, "m:objectID/m:id")
        if not user_id:
            continue
        users.append(
            {
                "name": xml_text(obj, "m:name"),
                "id": user_id,
                "type": xml_text(obj, "m:objectID/m:type") or "DMUser",
            }
        )
    return users


def parse_tasks(root: ET.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    objects = list(root.findall(".//m:items/m:object", NS))
    if not objects:
        objects = list(root.findall(".//m:objects", NS))
    for obj in objects:
        due = xml_text(obj, "m:dueDate")
        task_id = xml_text(obj, "m:objectID/m:id")
        if not task_id:
            continue
        rows.append(
            {
                "name": xml_text(obj, "m:name"),
                "id": task_id,
                "performer": xml_text(obj, "m:performer/m:user/m:name")
                or xml_text(obj, "m:performer/m:name"),
                "author": xml_text(obj, "m:author/m:name"),
                "begin": xml_text(obj, "m:beginDate"),
                "due": "" if due.startswith(EMPTY_DATE_PREFIX) else due,
                "executed": xml_text(obj, "m:executed") == "true",
                "step": xml_text(obj, "m:businessProcessStep"),
                "number": xml_text(obj, "m:number"),
                "description": xml_text(obj, "m:description"),
                "target": xml_text(obj, "m:target/m:name"),
                "target_id": xml_text(obj, "m:target/m:objectID/m:id"),
                "state": xml_text(obj, "m:state/m:name"),
            }
        )
    return rows


def find_user(config: DokConfig, name: str) -> dict[str, str]:
    fio = name.strip()
    if not fio:
        raise ValueError("Пустое ФИО пользователя ДО")
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMUser</dm:type>"
        "<dm:query>"
        f"{condition('name', string_value(fio))}"
        "<dm:limit>5</dm:limit>"
        "</dm:query>"
        "</dm:request>",
        timeout=max(config.timeout, 30.0),
    )
    users = parse_users(root)
    if not users:
        raise ValueError(f"Пользователь ДО не найден: «{fio}»")
    return users[0]


def parse_soap_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.startswith(EMPTY_DATE_PREFIX):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "")[:19])
    except ValueError:
        return None


def is_today_or_overdue(
    row: dict[str, Any],
    *,
    today: date | None = None,
) -> bool:
    """Open task due today / earlier, or without due but started today."""
    if row.get("executed") or row.get("done"):
        return False
    day = today or date.today()
    due = parse_soap_datetime(str(row.get("due") or row.get("due_at") or ""))
    if due is not None:
        return due.date() <= day
    began = parse_soap_datetime(str(row.get("begin") or row.get("created_at") or ""))
    return began is not None and began.date() == day


def list_open_tasks(
    config: DokConfig,
    since: datetime | None,
    *,
    timeout: float,
    only_open: bool = True,
    user: dict[str, str] | None = None,
    limit: int = 500,
    filter_mode: Literal["byUser", "performer"] | None = "byUser",
    due_to: datetime | None = None,
) -> list[dict[str, Any]]:
    filters = [condition("withExecuted", bool_value(not only_open))]
    if since is not None:
        filters.append(condition("beginDate", datetime_value(since), ">="))
    if due_to is not None:
        filters.append(condition("dueDate", datetime_value(due_to), "<="))
    if user and user.get("id") and filter_mode == "byUser":
        filters.append(
            condition("byUser", object_id_value(user["id"], user.get("type") or "DMUser"))
        )
    elif user and user.get("id") and filter_mode == "performer":
        filters.append(condition("performer", performer_value(user)))
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMBusinessProcessTask</dm:type>"
        "<dm:query>"
        f"{''.join(filters)}"
        f"<dm:limit>{max(1, min(int(limit), 500))}</dm:limit>"
        "<dm:columnSet>name</dm:columnSet>"
        "<dm:columnSet>performer</dm:columnSet>"
        "<dm:columnSet>author</dm:columnSet>"
        "<dm:columnSet>beginDate</dm:columnSet>"
        "<dm:columnSet>dueDate</dm:columnSet>"
        "<dm:columnSet>executed</dm:columnSet>"
        "<dm:columnSet>description</dm:columnSet>"
        "<dm:columnSet>target</dm:columnSet>"
        "</dm:query>"
        "</dm:request>",
        timeout=timeout,
    )
    rows = parse_tasks(root)
    if only_open:
        return [row for row in rows if not row["executed"]]
    return rows


def retrieve_tasks(config: DokConfig, task_ids: list[str], *, timeout: float) -> list[dict[str, Any]]:
    if not task_ids:
        return []
    ids_xml = "".join(
        "<dm:objectIds>"
        f"<dm:id>{xml_escape(task_id)}</dm:id>"
        "<dm:type>DMBusinessProcessTask</dm:type>"
        "</dm:objectIds>"
        for task_id in task_ids
    )
    root = execute_dm(
        config,
        f'<dm:request xsi:type="dm:DMRetrieveRequest">{ids_xml}</dm:request>',
        timeout=timeout,
    )
    return parse_tasks(root)


ROLE_EXECUTOR = "executor"
ROLE_AUTHOR = "author"
ROLE_BOTH = "both"

SOURCE_INBOX = "документооборот"
SOURCE_FROM_ME = "документооборот (от меня)"
CHANNEL_SOAP = "soap"


def normalize_person(value: str) -> str:
    return " ".join(value.lower().replace("ё", "е").split())


def task_role_for_user(row: dict[str, Any], user_fio: str) -> str | None:
    """executor / author / both when the dump row belongs to the session FIO."""
    mine = normalize_person(user_fio)
    if not mine:
        return None
    is_performer = normalize_person(str(row.get("performer") or "")) == mine
    is_author = normalize_person(str(row.get("author") or "")) == mine
    if is_performer and is_author:
        return ROLE_BOTH
    if is_performer:
        return ROLE_EXECUTOR
    if is_author:
        return ROLE_AUTHOR
    return None


def source_for_role(role: str) -> str:
    if role in {ROLE_AUTHOR, ROLE_BOTH}:
        return SOURCE_FROM_ME
    return SOURCE_INBOX


def _filter_ignored(rows: list[dict[str, Any]], user_name: str) -> bool:
    mine = normalize_person(user_name)
    others = {
        normalize_person(str(row.get("performer") or ""))
        for row in rows
        if normalize_person(str(row.get("performer") or "")) not in {"", mine}
    }
    return len(others) >= 3


def fetch_open_dump(config: DokConfig, *, only_open: bool = True) -> dict[str, Any]:
    """One unfiltered SOAP list — this DO ignores byUser/limit anyway."""
    started = time.perf_counter()
    timeout = max(float(config.timeout), _DEFAULT_LIST_TIMEOUT_SEC)
    logger.info("dok_soap dump start")
    rows = list_open_tasks(
        config,
        None,
        timeout=timeout,
        only_open=only_open,
        user=None,
        limit=500,
        filter_mode=None,
        due_to=None,
    )
    logger.info("dok_soap dump list=%.1fs raw=%s", time.perf_counter() - started, len(rows))
    return {
        "endpoint": config.soap_url(),
        "only_open": only_open,
        "count": len(rows),
        "rows": rows,
    }


def _dump_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("rows")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def task_dedup_key(row: dict[str, Any]) -> str:
    """Stable identity for SOAP dump rows (1C may repeat the same task)."""
    for field in ("id", "number"):
        value = str(row.get(field) or "").strip()
        if value:
            return f"id:{value.casefold()}"
    desc = " ".join(str(row.get("description") or row.get("target") or row.get("name") or "").split())
    due = str(row.get("due") or "").strip()[:10]
    author = normalize_person(str(row.get("author") or ""))
    performer = normalize_person(str(row.get("performer") or ""))
    if desc or due:
        return f"sig:{author}|{performer}|{desc.casefold()}|{due}"
    return ""


def slice_dump_for_user(
    dump: dict[str, Any],
    user_fio: str,
    *,
    today_and_overdue: bool = False,
) -> dict[str, Any]:
    today = date.today()
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in _dump_rows(dump):
        role = task_role_for_user(row, user_fio)
        if role is None:
            continue
        key = task_dedup_key(row)
        if key:
            if key in seen:
                continue
            seen.add(key)
        tagged = dict(row)
        tagged["role"] = role
        rows.append(tagged)
    if today_and_overdue:
        rows = [row for row in rows if is_today_or_overdue(row, today=today)]
    return {
        "endpoint": str(dump.get("endpoint") or ""),
        "user_ref": "",
        "user_fio": user_fio,
        "since": today.isoformat() if today_and_overdue else "",
        "count": len(rows),
        "rows": rows,
        "dump_count": len(_dump_rows(dump)),
    }


def fetch_inbox(
    config: DokConfig,
    user_fio: str,
    *,
    since_days: int,
    only_open: bool = True,
    retrieve: bool = True,
    today_and_overdue: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    user = find_user(config, user_fio)
    found_user_at = time.perf_counter()
    today = date.today()
    since = None if today_and_overdue else datetime.now() - timedelta(days=max(int(since_days), 1))
    due_to = (
        datetime.combine(today, datetime.max.time()).replace(microsecond=0)
        if today_and_overdue
        else None
    )
    timeout = max(float(config.timeout), _DEFAULT_LIST_TIMEOUT_SEC)
    raw: list[dict[str, Any]] = []
    last_error: RuntimeError | None = None
    used_mode = ""

    def _list(mode: str, due: datetime | None) -> list[dict[str, Any]]:
        return list_open_tasks(
            config,
            since,
            timeout=timeout,
            only_open=only_open,
            user=user,
            limit=80,
            filter_mode=mode,
            due_to=due,
        )

    logger.info(
        "dok_soap inbox start fio=%s scope=%s",
        user.get("name") or user_fio,
        "today_overdue" if today_and_overdue else "period",
    )
    for mode in ("byUser", "performer"):
        try:
            raw = _list(mode, due_to)
        except RuntimeError as error:
            last_error = error
            text = str(error)
            if _is_timeout_reason(text) or "нет связи" in text.lower():
                raise
            if due_to is not None:
                try:
                    raw = _list(mode, None)
                except RuntimeError as retry_error:
                    last_error = retry_error
                    if _is_timeout_reason(str(retry_error)) or "нет связи" in str(retry_error).lower():
                        raise
                    continue
            else:
                continue
        used_mode = mode
        if _filter_ignored(raw, user["name"]):
            logger.info(
                "dok_soap %s ignored server filter, keep dump raw=%s and filter in Python",
                mode,
                len(raw),
            )
        break
    if not used_mode:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Документооборот SOAP: не удалось отобрать задачи исполнителя")
    listed_at = time.perf_counter()
    rows = [row for row in raw if task_role_for_user(row, user["name"])]
    if today_and_overdue:
        rows = [row for row in rows if is_today_or_overdue(row, today=today)]
    if rows and retrieve:
        details = {
            row["id"]: row
            for row in retrieve_tasks(
                config, [row["id"] for row in rows], timeout=min(timeout, 20.0)
            )
        }
        rows = [details.get(row["id"], row) for row in rows]
    logger.info(
        "dok_soap inbox user=%.1fs list=%.1fs mode=%s scope=%s raw=%s kept=%s",
        found_user_at - started,
        listed_at - found_user_at,
        used_mode,
        "today_overdue" if today_and_overdue else "period",
        len(raw),
        len(rows),
    )
    return {
        "endpoint": config.soap_url(),
        "user_ref": user["id"],
        "user_fio": user["name"],
        "since": today.isoformat() if today_and_overdue else since.strftime("%Y-%m-%d") if since else "",
        "count": len(rows),
        "rows": rows,
    }


def fetch_user_inbox_tasks(
    user_fio: str,
    since_days: int = 90,
    *,
    env_file: str | None = None,
    username: str | None = None,
    password: str | None = None,
    only_open: bool = True,
    retrieve: bool = False,
    today_and_overdue: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Public API for inbox SOAP (used by dump script and onec.docflow_tasks).

    1C returns the full open-task dump; we cache that once and slice per user.
    """
    try:
        endpoint = load_config(env_file=env_file, username=username, password=password).soap_url()
    except (RuntimeError, ValueError, OSError):
        endpoint = "http://192.168.2.229:81/doc/ws/dm.1cws"
    key = _dump_cache_key(
        endpoint,
        only_open,
        soap_user=(username or "").strip(),
        soap_secret=(password or "").strip(),
    )
    lock = _lock_for(key)

    def _serve(dump: dict[str, Any], *, cached: bool, fetched_at: float) -> dict[str, Any]:
        payload = slice_dump_for_user(
            dump,
            user_fio,
            today_and_overdue=today_and_overdue,
        )
        if retrieve and payload["rows"]:
            try:
                config = load_config(env_file=env_file, username=username, password=password)
                details = {
                    row["id"]: row
                    for row in retrieve_tasks(
                        config,
                        [str(row.get("id") or "") for row in payload["rows"] if row.get("id")],
                        timeout=min(max(float(config.timeout), 20.0), 20.0),
                    )
                }
                payload["rows"] = [details.get(row.get("id"), row) for row in payload["rows"]]
            except Exception:
                logger.warning("dok_soap retrieve after dump slice failed")
        logger.info(
            "dok_soap slice fio=%s cached=%s dump=%s kept=%s",
            user_fio,
            cached,
            payload.get("dump_count"),
            payload.get("count"),
        )
        return _with_cache_meta(payload, cached=cached, fetched_at=fetched_at)

    with lock:
        if not force_refresh:
            hit = _cache_entry(key)
            if hit:
                fetched_at, dump = hit
                age = time.time() - fetched_at
                if age >= _cache_ttl_sec():
                    _schedule_refresh(
                        key,
                        only_open=only_open,
                        env_file=env_file,
                        username=username,
                        password=password,
                    )
                logger.info("dok_soap dump cache hit age=%.0fs raw=%s", age, len(_dump_rows(dump)))
                return _serve(dump, cached=True, fetched_at=fetched_at)
        try:
            config = load_config(env_file=env_file, username=username, password=password)
            dump = fetch_open_dump(config, only_open=only_open)
            _store_cache(key, dump)
            hit = _cache_entry(key)
            fetched_at = hit[0] if hit else time.time()
            return _serve(dump, cached=False, fetched_at=fetched_at)
        except Exception:
            stale = _cache_entry(key)
            if stale:
                fetched_at, dump = stale
                logger.warning("dok_soap live dump failed, serving cache")
                return _serve(dump, cached=True, fetched_at=fetched_at)
            raise


def format_when(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or text.startswith(EMPTY_DATE_PREFIX):
        return "—"
    date = text[:10]
    if len(date) == 10 and date[4] == "-" and date[7] == "-":
        return f"{date[8:10]}.{date[5:7]}.{date[0:4]}"
    return text


def format_table(payload: dict[str, Any]) -> str:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    header = [
        f"Пользователь: {payload.get('user_fio') or '—'}",
        f"Открытых задач: {payload.get('count', len(rows))}",
        f"С {payload.get('since') or '—'} (невыполненные)",
        "",
    ]
    if not rows:
        return "\n".join([*header, "Открытых задач нет."])

    lines = [
        *header,
        f"{'№':<3} {'Шаг':<14} {'Срок':<12} {'Автор':<28} Задача",
        "-" * 100,
    ]
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("description") or row.get("target") or row.get("name") or "").strip()
        name = str(row.get("name") or "").strip()
        extra = f"  ({name})" if name and title != name else ""
        lines.append(
            f"{index:<3} {str(row.get('step') or '—'):<14} "
            f"{format_when(str(row.get('due') or '')):<12} "
            f"{str(row.get('author') or '—'):<28} {title}{extra}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Открытые задачи пользователя из 1С:Документооборота (HTTP SOAP dm.1cws)",
    )
    parser.add_argument("users", nargs="+", help="ФИО одного или нескольких пользователей")
    parser.add_argument("--since-days", type=int, default=90, help="Окно дат, по умолчанию 90")
    parser.add_argument("-o", "--output", help="Сохранить JSON")
    parser.add_argument("--json", action="store_true", help="Печатать JSON, а не таблицу")
    parser.add_argument("--env-file", help="Путь к .env с DOK_HTTP_*")
    args = parser.parse_args(argv)

    try:
        payloads = [
            fetch_user_inbox_tasks(
                user,
                since_days=args.since_days,
                env_file=args.env_file,
            )
            for user in args.users
        ]
    except (RuntimeError, ValueError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    result: dict[str, Any] | list[dict[str, Any]] = (
        payloads[0] if len(payloads) == 1 else payloads
    )
    if args.output:
        Path(args.output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"Сохранено: {args.output}", file=sys.stderr)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print("\n\n".join(format_table(payload) for payload in payloads))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

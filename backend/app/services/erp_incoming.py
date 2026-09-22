"""Входящая корреспонденция 1С (Document_ТД_ВходящаяКорреспонденция) через OData — как agent-pochta."""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import BACKEND_ROOT, settings

INCOMING_ENTITY = "Document_ТД_ВходящаяКорреспонденция"
ATTACHED_FILES_ENTITY = "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы"

DEFAULT_SOURCE = "EMAIL"
DEFAULT_STATUS = "Подготовлен"
DEFAULT_AUTHOR = "Конструктор (ручная регистрация)"
_MSK = ZoneInfo("Europe/Moscow")
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ORG_PAYER = frozenset({"АЛ", "МГ", "АМ", "МИ", "БМ"})
_DEPARTMENT_ODATA_DIRECTION: dict[str, str] = {
    "00-000001": "ГенеральныйДиректор",
    "00-000152": "ОперационныйДиректор",
    "00-000182": "ОперационныйДиректор",
    "00-000066": "УправлениеДелами",
}
_MAX_MSG_ATTACH_BYTES = 12 * 1024 * 1024


class IncomingCorrespondenceError(RuntimeError):
    pass


def _pochta_data_dir() -> Path:
    raw = (os.environ.get("ORCH_POCHTA_DATA_DIR") or "").strip()
    if raw:
        path = Path(raw)
        if path.is_dir():
            return path
    bundled = BACKEND_ROOT / "data" / "pochta"
    if bundled.is_dir():
        return bundled
    fallback = Path(
        r"C:\Users\mdj\Desktop\рабочее\Входящая корреспонденция"
        r"\2. Входящая корреспонденция\agent-pochta\data"
    )
    return fallback if fallback.is_dir() else bundled


def _load_json_map(name: str) -> dict[str, str]:
    path = _pochta_data_dir() / name
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in data.items()
        if str(key).strip() and str(value).strip()
    }


def _load_incoming_defaults() -> dict[str, Any]:
    path = _pochta_data_dir() / "odata_incoming_defaults.json"
    if not path.is_file():
        return {"Posted": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"Posted": False}


def _load_attached_file_map() -> dict[str, Any]:
    path = _pochta_data_dir() / "odata_attached_file_field_map.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_department_names() -> dict[str, str]:
    rules_path = _pochta_data_dir() / "routing_rules.json"
    if not rules_path.is_file():
        alt = Path(
            r"C:\Users\mdj\Desktop\рабочее\Входящая корреспонденция"
            r"\2. Входящая корреспонденция\agent-pochta\data\routing_rules.json"
        )
        rules_path = alt if alt.is_file() else rules_path
    names: dict[str, str] = {}
    if rules_path.is_file():
        try:
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
            block = rules.get("department_names") if isinstance(rules, dict) else None
            if isinstance(block, dict):
                for code, label in block.items():
                    code_s = str(code).strip()
                    label_s = str(label).strip()
                    if code_s and label_s:
                        names[code_s] = label_s
        except (OSError, json.JSONDecodeError):
            pass
    for code in _load_json_map("odata_department_keys.json"):
        names.setdefault(code, code)
    return names


def _odata_post(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_post

    return _odata_post(args)


def _odata_datetime(value: datetime | None = None) -> str:
    dt = value or datetime.now(tz=_MSK)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_MSK)
    return dt.astimezone(_MSK).replace(microsecond=0, tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def _clip(text: str, max_len: int) -> str:
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def _resolve_payer_direction(org_code: str) -> str:
    code = (org_code or "НП").strip().upper()
    if code in _ORG_PAYER:
        return code
    if code == "НП":
        return "ТурбулентностьДОНКС"
    return code


def _resolve_odata_direction(department_id: str) -> str:
    return _DEPARTMENT_ODATA_DIRECTION.get((department_id or "").strip(), "")


def build_create_body(args: dict[str, Any]) -> dict[str, Any]:
    department_id = str(
        args.get("department_id") or args.get("assignee") or args.get("Кому") or ""
    ).strip()
    if not department_id:
        raise IncomingCorrespondenceError("Укажите код подразделения (Кому на исполнение), например 00-000066")

    department_keys = _load_json_map("odata_department_keys.json")
    department_key = department_keys.get(department_id, "")
    if not department_key:
        raise IncomingCorrespondenceError(
            f"Не найден GUID подразделения для {department_id!r} — проверьте odata_department_keys.json"
        )

    department_names = _load_department_names()
    department_name = str(
        args.get("department_name")
        or department_names.get(department_id)
        or department_id
    ).strip()

    org_code = str(args.get("organization") or args.get("org_code") or "НП").strip().upper()
    org_keys = _load_json_map("odata_organization_keys.json")
    org_key = org_keys.get(org_code, org_keys.get("НП", ""))

    theme = _clip(str(args.get("theme") or args.get("subject") or args.get("Тема") or ""), 200)
    if not theme:
        raise IncomingCorrespondenceError("Укажите тему документа")

    partner = _clip(str(args.get("partner") or args.get("Партнер") or ""), 200)
    content = _clip(
        str(args.get("content") or args.get("body_preview") or args.get("summary") or theme),
        800,
    )
    email_sender = _clip(str(args.get("email_sender") or args.get("sender") or ""), 200)
    email_recipient = _clip(str(args.get("email_recipient") or args.get("recipient") or ""), 200)

    received_raw = str(args.get("received_at") or args.get("mail_received_at") or "").strip()
    doc_date = _odata_datetime()
    if received_raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%y %H:%M", "%d.%m.%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(received_raw[:19], fmt)
                doc_date = _odata_datetime(parsed)
                break
            except ValueError:
                continue

    body: dict[str, Any] = {
        "Date": doc_date,
        "ИсточникПоступления": DEFAULT_SOURCE,
        "Статус": DEFAULT_STATUS,
        "ТемаСлужебнойЗаписки": theme,
        "Подразделение": department_name,
        "ПодразделениеИсполнитель_Key": department_key,
        "КомуПодразделениеСсылка_Key": department_key,
        "Кому": department_id,
        "Содержание": content,
        "Автор": DEFAULT_AUTHOR,
        "EmailОтправителяПисьма": email_sender,
        "EmailПолучателяПисьма": email_recipient,
        "ПлательщикНаправление": _resolve_payer_direction(org_code),
    }
    if partner:
        body["Партнер"] = partner
    if org_key:
        body["Организация_Key"] = org_key
    direction = _resolve_odata_direction(department_id)
    if direction:
        body["Направление"] = direction

    defaults = _load_incoming_defaults()
    for key, value in defaults.items():
        if key not in body and value is not None:
            body[key] = value

    extra = args.get("extra_fields")
    if isinstance(extra, dict):
        body.update(extra)

    return body


def _split_filename(filename: str) -> tuple[str, str]:
    name = (filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        raise IncomingCorrespondenceError("Имя файла вложения не задано")
    if "." in name:
        base, ext = name.rsplit(".", 1)
        return base.strip() or "message", ext.strip().lower()
    return name, ""


def _resolve_msg_bytes(args: dict[str, Any]) -> tuple[bytes, str]:
    b64 = str(args.get("msg_base64") or args.get("file_base64") or "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64, validate=True)
        except ValueError as exc:
            raise IncomingCorrespondenceError("Некорректный msg_base64") from exc
        name = str(args.get("msg_filename") or args.get("filename") or "message.msg").strip()
        return raw, name

    for key in ("msg_file_path", "staged_path", "mail_file_path", "file_path"):
        path_raw = str(args.get(key) or "").strip()
        if not path_raw:
            continue
        path = Path(path_raw)
        if path.is_file():
            raw = path.read_bytes()
            if len(raw) > _MAX_MSG_ATTACH_BYTES:
                raise IncomingCorrespondenceError(
                    f"Файл письма слишком большой для OData ({len(raw)} байт)"
                )
            return raw, path.name

    return b"", ""


def _build_attached_file_body(
    *,
    document_ref_key: str,
    filename: str,
    content: bytes,
    author_key: str = "",
) -> dict[str, Any]:
    cfg = _load_attached_file_map()
    fields = cfg.get("fields") if isinstance(cfg.get("fields"), dict) else {}
    defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
    base_name, extension = _split_filename(filename)
    if extension and not filename.lower().endswith(f".{extension}"):
        filename = f"{base_name}.{extension}"
    payload: dict[str, Any] = {}
    if name_field := fields.get("name"):
        payload[str(name_field)] = base_name
    if ext_field := fields.get("extension"):
        payload[str(ext_field)] = extension
    owner_field = str(fields.get("owner_key") or "ВладелецФайла_Key")
    payload[owner_field] = document_ref_key
    if size_field := fields.get("size"):
        payload[str(size_field)] = len(content)
    binary_field = str(fields.get("storage_binary") or "ФайлХранилище_Base64Data")
    payload[binary_field] = base64.b64encode(content).decode("ascii")
    type_field = str(fields.get("storage_binary_type") or "ФайлХранилище_Type")
    payload[type_field] = str(defaults.get("storage_binary_type") or "application/octet-stream")
    if not defaults.get("omit_storage_kind") and (kind_field := fields.get("storage_kind")):
        payload[str(kind_field)] = str(defaults.get("storage_kind") or "ВИнформационнойБазе")
    author = (author_key or str(_load_incoming_defaults().get("Ответственный_Key") or "")).strip()
    if author and _GUID_RE.match(author) and (author_field := fields.get("author_key")):
        payload[str(author_field)] = author
    return payload


def _attach_msg_to_document(document_ref_key: str, args: dict[str, Any]) -> dict[str, Any] | None:
    try:
        content, filename = _resolve_msg_bytes(args)
    except IncomingCorrespondenceError:
        return None
    if not content:
        return None
    body = _build_attached_file_body(
        document_ref_key=document_ref_key,
        filename=filename or "message.msg",
        content=content,
    )
    entity = str(
        (_load_attached_file_map().get("entity") or ATTACHED_FILES_ENTITY)
    ).strip()
    result = _odata_post({"entity": entity, "body": body})
    return {
        "summary": "msg attached",
        "filename": filename,
        "entity": entity,
        **result,
    }


def handle_incoming_correspondence(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = str(args.get("action") or "departments").strip().casefold()
    if action in {"departments", "list_departments", "meta"}:
        names = _load_department_names()
        items = [
            {"code": code, "name": label}
            for code, label in sorted(names.items(), key=lambda item: item[1].casefold())
        ]
        return {
            "summary": f"Подразделения для маршрутизации: {len(items)}",
            "departments": items,
            "count": len(items),
            "source": "pochta_data",
        }
    raise IncomingCorrespondenceError("action: departments | list_departments | meta")


def handle_incoming_correspondence_write(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = str(args.get("action") or "create").strip().casefold()
    if action != "create":
        raise IncomingCorrespondenceError("Пока поддерживается только action=create")

    entity = str(args.get("entity") or settings.odata_incoming_doc_entity or INCOMING_ENTITY).strip()
    body = build_create_body(args)
    created = _odata_post({"entity": entity, "body": body})
    data = created.get("data") if isinstance(created.get("data"), dict) else {}
    ref_key = str(
        created.get("erp_document_id")
        or data.get("Ref_Key")
        or data.get("ref_key")
        or ""
    ).strip()
    number = str(data.get("Number") or created.get("number") or "").strip()

    attach_result: dict[str, Any] | None = None
    attach_error = ""
    if ref_key and str(args.get("attach_msg", "true")).strip().lower() not in {"0", "false", "no"}:
        try:
            attach_result = _attach_msg_to_document(ref_key, args)
        except Exception as exc:
            attach_error = str(exc)

    summary = "Создана входящая корреспонденция в 1С (OData POST)"
    if number:
        summary += f": {number}"

    out: dict[str, Any] = {
        "summary": summary,
        "entity": entity,
        "body": body,
        "erp_document_id": ref_key,
        "number": number,
        **created,
    }
    if attach_result:
        out["attachment"] = attach_result
    elif attach_error:
        out["attachment_warning"] = attach_error
    return out


def stub_incoming_correspondence(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = str(args.get("action") or "departments").strip().casefold()
    if action in {"departments", "list_departments", "meta"}:
        return {
            "summary": "stub departments",
            "departments": [
                {"code": "00-000066", "name": "Управление делами"},
                {"code": "00-000001", "name": "Генеральный директор"},
            ],
            "count": 2,
            "source": "stub",
        }
    return {"summary": "stub incoming meta", "source": "stub"}


def stub_incoming_correspondence_write(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    body = build_create_body(args) if args.get("theme") or args.get("subject") else {}
    return {
        "summary": "stub: входящая корреспонденция OData create",
        "entity": INCOMING_ENTITY,
        "erp_document_id": "00000000-0000-0000-0000-000000000099",
        "number": "ВК-STUB-001",
        "body": body,
        "source": "stub",
    }

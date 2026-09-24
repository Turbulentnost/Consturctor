"""Входящая корреспонденция 1С (Document_ТД_ВходящаяКорреспонденция) через OData — как agent-pochta."""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import BACKEND_ROOT, settings

INCOMING_ENTITY = "Document_ТД_ВходящаяКорреспонденция"
ATTACHED_FILES_ENTITY = "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы"

DEFAULT_SOURCE = "EMAIL"
DEFAULT_STATUS = "Подготовлен"
DEFAULT_AUTHOR = "Конструктор (ручная регистрация)"
# Составной строковый реквизит OData: значение и соседнее поле *_Type.
_COMPOSITE_STRING_TYPE = "Edm.String"
_MSK = ZoneInfo("Europe/Moscow")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Как agent-pochta routing/organizations.py — в UI полное имя, в OData код + GUID.
ORG_FULL_NAMES: dict[str, str] = {
    "НП": "НПО «Турбулентность-ДОН»",
    "АЛ": "ООО «Алмаз»",
    "МГ": "ООО «Метрогазсервис»",
    "АМ": "ООО «Амурская легенда»",
    "МИ": "ООО «МИЛАКА»",
    "БМ": "БМИ (блочно-модульные изделия)",
}
ORG_ORDER = ("НП", "АЛ", "МГ", "АМ", "МИ", "БМ")
# БМИ в 1С — та же организация, что НПО.
_ORG_KEY_ALIAS = {"БМ": "НП"}
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
    from_file = _load_json_map("odata_department_names.json")
    if from_file:
        return from_file
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


def _odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_patch

    return _odata_patch(args)


def _odata_datetime(value: datetime | None = None) -> str:
    """Naive Europe/Moscow wall-clock for 1C OData Date (no Z / no offset)."""
    dt = value or datetime.now(tz=_MSK)
    if dt.tzinfo is None:
        # Already a Moscow wall clock from the client/UI — do not shift.
        return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    return dt.astimezone(_MSK).replace(microsecond=0, tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def _clip(text: str, max_len: int) -> str:
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def _resolve_org_code(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "НП"
    upper = text.upper()
    if upper in ORG_FULL_NAMES:
        return upper
    folded = text.casefold()
    for code, name in ORG_FULL_NAMES.items():
        if name.casefold() == folded:
            return code
    return upper if len(upper) <= 4 else "НП"


# Enum 1С «ТД_ПлательщикНаправление». Коды организаций (АЛ, МГ) туда не входят.
# Fallback, если нет odata_payer_direction_map.json (как default в agent-pochta).
_PAYER_DIRECTION = {
    "НП": "ТурбулентностьДОНПроизводство1",
    "АЛ": "АЛМАЗ",
    "МГ": "Метрогазсервис",
    "АМ": "АмурскаяЛегенда",
    "МИ": "ТурбулентностьДОНКС",
    "БМ": "БМИ",
}
_ORG_AS_PAYER_DIRECTION = frozenset({"АЛ", "МГ", "АМ", "МИ", "БМ"})


def _load_payer_direction_map() -> dict[str, Any]:
    path = _pochta_data_dir() / "odata_payer_direction_map.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_payer_direction(org_code: str, direction_code: str = "") -> str:
    """Как agent-pochta resolve_payer_direction: org + optional XML direction → enum."""
    org = (org_code or "НП").strip().upper() or "НП"
    direction = (direction_code or "").strip().upper()
    if org in _ORG_AS_PAYER_DIRECTION and not direction:
        direction = org

    data = _load_payer_direction_map()
    organizations = data.get("organizations") if isinstance(data, dict) else None
    if isinstance(organizations, dict):
        org_entry = organizations.get(org)
        if not isinstance(org_entry, dict):
            org_entry = organizations.get("НП")
        if isinstance(org_entry, dict):
            directions = org_entry.get("directions")
            if isinstance(directions, dict) and direction:
                mapped = directions.get(direction)
                if isinstance(mapped, str) and mapped.strip():
                    return mapped.strip()
            default = org_entry.get("default")
            if isinstance(default, str) and default.strip():
                return default.strip()
            np_entry = organizations.get("НП")
            if isinstance(np_entry, dict):
                np_default = np_entry.get("default")
                if isinstance(np_default, str) and np_default.strip():
                    return np_default.strip()

    return _PAYER_DIRECTION.get(org, _PAYER_DIRECTION["НП"])


def _resolve_odata_direction(department_id: str) -> str:
    return _DEPARTMENT_ODATA_DIRECTION.get((department_id or "").strip(), "")


def _load_payer_display() -> dict[str, str]:
    """enum ПлательщикНаправление → отображаемое имя (для UI и валидации override)."""
    return _load_json_map("odata_payer_direction_display.json")


def _resolve_payer_override(raw: Any) -> str:
    """Плательщик из формы: enum-код или отображаемое имя; иначе пусто (вычислим)."""
    text = str(raw or "").strip()
    if not text:
        return ""
    display = _load_payer_display()
    if text in display:
        return text
    folded = text.casefold()
    for code, name in display.items():
        if name.casefold() == folded:
            return code
    return ""


def _put_composite_string(body: dict[str, Any], key: str, value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    body[key] = text
    body[f"{key}_Type"] = _COMPOSITE_STRING_TYPE


def build_create_body(args: dict[str, Any]) -> dict[str, Any]:
    department_id = str(
        args.get("department_id") or args.get("assignee") or args.get("Кому") or ""
    ).strip()
    department_names = _load_department_names()
    department_name = str(args.get("department_name") or "").strip()
    if not department_id and department_name:
        folded = department_name.casefold()
        for code, label in department_names.items():
            if label.casefold() == folded:
                department_id = code
                break
    if not department_id:
        raise IncomingCorrespondenceError("Выберите подразделение из списка (кому на исполнение)")

    department_keys = _load_json_map("odata_department_keys.json")
    department_key = department_keys.get(department_id, "")
    if not department_key:
        raise IncomingCorrespondenceError(
            f"Подразделение «{department_name or department_id}» не сопоставлено с 1С"
        )

    department_name = (
        department_name
        or department_names.get(department_id)
        or department_id
    ).strip()

    org_code = _resolve_org_code(str(args.get("organization") or args.get("org_code") or "НП"))
    org_lookup = _ORG_KEY_ALIAS.get(org_code, org_code)
    org_keys = _load_json_map("odata_organization_keys.json")
    org_key = org_keys.get(org_lookup, org_keys.get("НП", ""))

    theme = _clip(str(args.get("theme") or args.get("subject") or args.get("Тема") or ""), 200)
    if not theme:
        raise IncomingCorrespondenceError("Укажите тему документа")

    partner = _clip(str(args.get("partner") or args.get("Партнер") or ""), 200)
    if not partner:
        raise IncomingCorrespondenceError("Укажите партнёра — без него 1С не записывает входящую")
    content = _clip(
        str(args.get("content") or args.get("body_preview") or args.get("summary") or theme),
        800,
    )
    email_sender = _clip(str(args.get("email_sender") or args.get("sender") or ""), 200)
    email_recipient = _clip(str(args.get("email_recipient") or args.get("recipient") or ""), 200)

    # Document Date = moment of registration (Moscow), not letter ReceivedTime.
    # Manual UI fills at "now"; using mail received_at produced 08:07 when the user
    # registered at 14:57. agent-pochta uses letter time only after UTC→MSK conversion.
    doc_date = _odata_datetime(datetime.now(tz=_MSK))

    body: dict[str, Any] = {
        "Date": doc_date,
        "ИсточникПоступления": DEFAULT_SOURCE,
        "Статус": DEFAULT_STATUS,
        "ПодразделениеИсполнитель_Key": department_key,
        "КомуПодразделениеСсылка_Key": department_key,
        "Кому": department_id,
        "Содержание": content,
        "EmailОтправителяПисьма": email_sender,
        "EmailПолучателяПисьма": email_recipient,
    }
    # Плательщик: значение из формы (подсказка onec.incoming_suggest, редактируемое),
    # иначе как раньше — по организации.
    payer = _resolve_payer_override(
        args.get("payer_direction") or args.get("payer") or ""
    ) or _resolve_payer_direction(org_code, str(args.get("direction_code") or ""))

    _put_composite_string(body, "ТемаСлужебнойЗаписки", theme)
    _put_composite_string(body, "Подразделение", department_name)
    _put_composite_string(body, "Автор", DEFAULT_AUTHOR)
    _put_composite_string(body, "ПлательщикНаправление", payer)
    _put_composite_string(body, "Партнер", partner)
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
    """Read .msg bytes: local staged path first, then base64 fallback."""
    tried_paths: list[str] = []
    for key in ("msg_file_path", "staged_path", "mail_file_path", "file_path"):
        path_raw = str(args.get(key) or "").strip()
        if not path_raw or path_raw in tried_paths:
            continue
        tried_paths.append(path_raw)
        path = Path(path_raw)
        if path.is_file():
            raw = path.read_bytes()
            if len(raw) > _MAX_MSG_ATTACH_BYTES:
                raise IncomingCorrespondenceError(
                    f"Файл письма слишком большой для OData ({len(raw)} байт)"
                )
            if not raw:
                raise IncomingCorrespondenceError(f"Файл письма пуст: {path}")
            return raw, path.name

    b64 = str(args.get("msg_base64") or args.get("file_base64") or "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as exc:
            raise IncomingCorrespondenceError("Некорректный msg_base64") from exc
        if len(raw) > _MAX_MSG_ATTACH_BYTES:
            raise IncomingCorrespondenceError(
                f"Файл письма слишком большой для OData ({len(raw)} байт)"
            )
        if not raw:
            raise IncomingCorrespondenceError("msg_base64 пуст")
        name = str(args.get("msg_filename") or args.get("filename") or "message.msg").strip()
        return raw, name or "message.msg"

    if tried_paths:
        raise IncomingCorrespondenceError(
            "Не удалось прочитать .msg по staged_path "
            f"({tried_paths[0]}) и msg_base64 не передан"
        )
    raise IncomingCorrespondenceError(
        "Нет файла письма для вложения: укажите staged_path или msg_base64"
    )


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
    # Base64 POST: 1С падает с 500 на application/vnd.ms-outlook — как agent-pochta.
    payload[type_field] = str(defaults.get("storage_binary_type") or "application/octet-stream")
    if not defaults.get("omit_storage_kind") and (kind_field := fields.get("storage_kind")):
        payload[str(kind_field)] = str(defaults.get("storage_kind") or "ВИнформационнойБазе")
    # Даты как agent-pochta (MSK created / UTC modified), иначе БСП может не отдать файл.
    if not bool(defaults.get("omit_dates", False)):
        now_msk = datetime.now(tz=_MSK).replace(microsecond=0, tzinfo=None)
        now_utc = datetime.now(tz=timezone.utc).replace(microsecond=0, tzinfo=None)
        if created_field := fields.get("created_at"):
            payload[str(created_field)] = now_msk.strftime("%Y-%m-%dT%H:%M:%S")
        if modified_field := fields.get("modified_at"):
            payload[str(modified_field)] = now_utc.strftime("%Y-%m-%dT%H:%M:%S")
    author = (author_key or str(_load_incoming_defaults().get("Ответственный_Key") or "")).strip()
    if author and _GUID_RE.match(author) and (author_field := fields.get("author_key")):
        payload[str(author_field)] = author
    return payload


def _release_attached_file_edit_lock(entity: str, file_ref_key: str) -> None:
    """Снять Редактирует_Key после POST — иначе БСП помечает файл недоступным."""
    cfg = _load_attached_file_map()
    fields = cfg.get("fields") if isinstance(cfg.get("fields"), dict) else {}
    lock_field = str(fields.get("edit_lock_key") or "Редактирует_Key").strip()
    if not lock_field or not file_ref_key:
        return
    try:
        _odata_patch(
            {
                "entity": entity,
                "ref_key": file_ref_key,
                "body": {lock_field: _EMPTY_GUID},
            }
        )
    except Exception:
        # Attach already created; lock release is best-effort like agent-pochta verify.
        pass


def _attach_msg_to_document(
    document_ref_key: str,
    args: dict[str, Any],
    *,
    document_number: str = "",
) -> dict[str, Any]:
    content, filename = _resolve_msg_bytes(args)
    number = (document_number or "").strip()
    if number:
        filename = f"{number}.msg"
    elif not str(filename or "").lower().endswith(".msg"):
        filename = f"{filename or 'message'}.msg"
    body = _build_attached_file_body(
        document_ref_key=document_ref_key,
        filename=filename or "message.msg",
        content=content,
    )
    entity = str(
        (_load_attached_file_map().get("entity") or ATTACHED_FILES_ENTITY)
    ).strip()
    result = _odata_post({"entity": entity, "body": body})
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    file_ref = str(
        result.get("erp_document_id") or data.get("Ref_Key") or data.get("ref_key") or ""
    ).strip()
    if file_ref:
        _release_attached_file_edit_lock(entity, file_ref)
    return {
        "summary": "msg attached",
        "filename": filename,
        "entity": entity,
        "file_ref_key": file_ref,
        "size": len(content),
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
        organizations = [
            {"code": code, "name": ORG_FULL_NAMES[code]}
            for code in ORG_ORDER
            if code in ORG_FULL_NAMES
        ]
        payers = [
            {"code": code, "name": name} for code, name in _load_payer_display().items()
        ]
        return {
            "summary": f"Подразделения для маршрутизации: {len(items)}",
            "departments": items,
            "organizations": organizations,
            "payers": payers,
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
    want_attach = str(args.get("attach_msg", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if ref_key and want_attach:
        try:
            attach_result = _attach_msg_to_document(ref_key, args, document_number=number)
        except Exception as exc:
            attach_error = str(exc) or exc.__class__.__name__

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
    elif want_attach:
        out["attachment_warning"] = attach_error or (
            "Файл .msg не прикреплён: нет данных письма или ошибка OData"
        )
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

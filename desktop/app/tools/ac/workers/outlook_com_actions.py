"""Низкоуровневые безопасные действия Outlook через COM."""

from __future__ import annotations

import importlib
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from app.tools.ac.workers import com_availability
from app.tools.ac.workers.outlook_com_errors import (
    ComUnavailableError,
    DangerousOutlookActionBlockedError,
    OutlookAccessError,
    OutlookComError,
)

INBOX_FOLDER_ID = 6
SENT_FOLDER_ID = 5
CALENDAR_FOLDER_ID = 9
DEFAULT_FOLDER = "Inbox"
SENT_FOLDER = "Sent"
ALL_MAIL_FOLDERS = "All"
CALENDAR_FOLDER = "Calendar"
DEFAULT_DAYS = 7
DEFAULT_DAYS_FORWARD = 365
DEFAULT_MAX_RESULTS = 50
DEFAULT_CALENDAR_MAX_RESULTS = 200
MAX_DAYS = 365
MAX_RESULTS = 50
MAX_CALENDAR_RESULTS = 500

# Транзиентные COM/RPC HRESULT-ы: Outlook занят или сервер ещё поднимается.
# При них имеет смысл короткий повтор вместо провала всего запуска.
TRANSIENT_COM_HRESULTS = {
    -2147467263,  # E_UNEXPECTED — Outlook «Не выполнено» на Save/Start
    -2147467260,  # E_ABORT — "Операция прервана"
    -2147418111,  # RPC_E_CALL_REJECTED — вызов отклонён callee
    -2147417846,  # RPC_E_SERVERCALL_RETRYLATER — сервер занят
    -2147417851,  # RPC_E_SERVERFAULT
    -2147023174,  # RPC_S_SERVER_UNAVAILABLE — Outlook RPC временно недоступен
    -2146959355,  # CO_E_SERVER_EXEC_FAILURE — сбой запуска COM-сервера
}
MAX_COM_ATTEMPTS = 3
COM_RETRY_DELAY_SECONDS = 1.0

# HRESULT-ы «классический Outlook не установлен / COM-класс не зарегистрирован».
# Частая причина на других ПК: установлен только «новый Outlook», который не
# поддерживает COM-автоматизацию, либо classic Outlook не зарегистрирован.
CLASS_NOT_REGISTERED_HRESULTS = {
    -2147221164,  # REGDB_E_CLASSNOTREG (0x80040154)
    -2147221005,  # CO_E_CLASSSTRING — недопустимая строка класса (0x800401F3)
    -2147221231,  # CO_E_CLASSNOTREG для отдельного класса (0x80040111)
}
DISP_E_EXCEPTION = -2147352567  # 0x80020009
MAPI_E_NOT_FOUND = -2147221233  # 0x8004010F
TRUST_CENTER_HINT = (
    "Классический Outlook должен быть открыт, календарь — свой (не только чтение). "
    "Файл → Параметры → центр управления безопасностью → программный доступ: "
    "не блокировать автоматизацию."
)
MAPI_NOT_FOUND_HINT = (
    "Календарь или элемент профиля не найден (MAPI_E_NOT_FOUND). "
    "Откройте классический Outlook с загруженным почтовым ящиком "
    "и своим календарём, затем повторите."
)
OUTLOOK_NOT_REGISTERED_MESSAGE = (
    "Классический Outlook не найден или COM-автоматизация не зарегистрирована на "
    "этом компьютере. Установите классический Microsoft Outlook (desktop) и хотя бы "
    "раз запустите его с настроенным профилем. «Новый Outlook» и веб-версия COM не "
    "поддерживают."
)
DEFAULT_MAIL_MAX_SCAN_ITEMS = 200
DEFAULT_CALENDAR_MAX_SCAN_ITEMS = 1000
MAX_SCAN_ITEMS = 2000
BODY_PREVIEW_LIMIT = 12000
CALENDAR_BODY_PREVIEW_LIMIT = 300

# MAPI proptag-схемы для чтения адресных свойств через PropertyAccessor.
# Прямое обращение к SenderName/Organizer/attendees триггерит Outlook Object
# Model Guard (окно "Программа пытается получить доступ к адресам..."), которое
# блокирует COM-поток и роняет чтение по таймауту. PropertyAccessor читает те же
# строковые свойства без срабатывания guard, поэтому окно не появляется.
PROPTAG_BASE = "http://schemas.microsoft.com/mapi/proptag/"
PR_SENDER_NAME_W = PROPTAG_BASE + "0x0C1A001F"
PR_SENT_REPRESENTING_NAME_W = PROPTAG_BASE + "0x0042001F"
PR_DISPLAY_TO_W = PROPTAG_BASE + "0x0E04001F"
PR_DISPLAY_CC_W = PROPTAG_BASE + "0x0E03001F"
# SMTP-адрес отправителя (не X.500 DN Exchange) — для «Почта отправителя» в 1С.
PR_SENDER_SMTP_ADDRESS_W = PROPTAG_BASE + "0x5D01001F"
PR_SENT_REPRESENTING_SMTP_ADDRESS_W = PROPTAG_BASE + "0x5D02001F"
PR_SENDER_EMAIL_ADDRESS_W = PROPTAG_BASE + "0x0C1F001F"


def _log_progress(message: str) -> None:
    """Записать COM progress-сообщение в stderr, не загрязняя stdout JSON."""
    print(f"[COM_DIAG] {message}", file=sys.stderr, flush=True)


def _read_sender_smtp(item: Any) -> str:
    """SMTP-адрес отправителя письма; пусто, если только X.500 DN Exchange."""
    for schema in (
        PR_SENDER_SMTP_ADDRESS_W,
        PR_SENT_REPRESENTING_SMTP_ADDRESS_W,
        PR_SENDER_EMAIL_ADDRESS_W,
    ):
        value = _read_guarded_property(item, schema).strip()
        if "@" in value:
            return value
    return ""


def _read_guarded_property(item: Any, schema: str) -> str:
    """Прочитать адресное свойство через PropertyAccessor без Outlook guard.

    Возвращает пустую строку при любой ошибке, чтобы не откатываться на прямой
    getattr (который снова вызвал бы окно защиты Outlook) и не ронять чтение.
    """
    try:
        accessor = item.PropertyAccessor
    except Exception:
        return ""
    try:
        return _safe_str(accessor.GetProperty(schema))
    except Exception:
        return ""


def _load_pywin32_modules():
    """Загрузить pywin32-модули только внутри worker/action слоя."""
    if not com_availability.is_windows():
        raise ComUnavailableError("COM доступен только на Windows")

    com_availability.ensure_pywin32_dll_path()
    try:
        pythoncom = importlib.import_module("pythoncom")
        win32com_client = importlib.import_module("win32com.client")
    except ImportError as exc:
        raise ComUnavailableError("pywin32 не установлен") from exc
    except Exception as exc:
        raise ComUnavailableError(f"pywin32 недоступен: {exc}") from exc

    return pythoncom, win32com_client


def _is_transient_com_error(exc: Exception) -> bool:
    """Определить, что COM-ошибка транзиентная (Outlook занят / сервер поднимается)."""
    args = getattr(exc, "args", None)
    if args and isinstance(args[0], int) and args[0] in TRANSIENT_COM_HRESULTS:
        return True
    nested = args[2] if args and len(args) > 2 and isinstance(args[2], tuple) else ()
    if nested and isinstance(nested[-1], int) and nested[-1] in TRANSIENT_COM_HRESULTS:
        return True
    text = str(exc).casefold()
    return "не выполнено" in text or "rpc_e_servercall_retrylater" in text


def _com_hresults(exc: Exception) -> set[int]:
    """Собрать HRESULT из pywin32 com_error, включая вложенный код Outlook."""
    found: set[int] = set()
    args = getattr(exc, "args", None) or ()
    if args and isinstance(args[0], int):
        found.add(args[0])
    nested = args[2] if len(args) > 2 and isinstance(args[2], tuple) else ()
    if nested and isinstance(nested[-1], int):
        found.add(nested[-1])
    return found


def _is_mapi_not_found(exc: Exception) -> bool:
    """MAPI_E_NOT_FOUND: папка/элемент календаря не найден, не блок Trust Center."""
    codes = _com_hresults(exc)
    if MAPI_E_NOT_FOUND in codes:
        return True
    text = str(exc).casefold()
    return "8004010f" in text or "2147221233" in text


def _is_class_not_registered_error(exc: Exception) -> bool:
    """Определить, что COM-класс Outlook не зарегистрирован (нет classic Outlook)."""
    if _com_hresults(exc) & CLASS_NOT_REGISTERED_HRESULTS:
        return True
    text = str(exc).casefold()
    return "80040154" in text or "class not registered" in text or (
        "недопустимая строка класса" in text
    )


def _outlook_access_message(prefix: str, exc: Exception) -> str:
    """Человекочитаемая причина COM-ошибки Outlook, без универсального Trust Center."""
    if _is_class_not_registered_error(exc):
        return f"{prefix}: {OUTLOOK_NOT_REGISTERED_MESSAGE} (детали COM: {exc})"
    if _is_mapi_not_found(exc):
        return f"{prefix}: {MAPI_NOT_FOUND_HINT} ({exc})"
    return f"{prefix}: {exc}. {TRUST_CENTER_HINT}"


# Outlook COM — один STA-сервер. Параллельный обход почты и клик «В Outlook»
# дают MK_E_UNAVAILABLE, и кнопка молча не открывает письмо.
_OUTLOOK_COM_LOCK = threading.Lock()


def _run_com_read(operation: Callable[[Any], dict], access_error_prefix: str) -> dict:
    """Выполнить read-only COM-операцию с CoInitialize и повтором транзиентных ошибок.

    ``operation`` получает модуль ``win32com.client`` и возвращает готовый payload.
    ComUnavailableError из загрузки pywin32 пробрасывается как есть (нужно тестам).
    """
    with _OUTLOOK_COM_LOCK:
        return _run_com_read_locked(operation, access_error_prefix)


def _run_com_read_locked(operation: Callable[[Any], dict], access_error_prefix: str) -> dict:
    pythoncom, win32com_client = _load_pywin32_modules()
    _log_progress("step=load_pywin32 ok")
    last_exc: Exception | None = None
    for attempt in range(1, MAX_COM_ATTEMPTS + 1):
        com_initialized = False
        try:
            _log_progress(f"step=co_initialize start attempt={attempt}")
            pythoncom.CoInitialize()
            com_initialized = True
            _log_progress("step=co_initialize ok")
            return operation(win32com_client)
        except OutlookComError:
            raise
        except Exception as exc:  # noqa: BLE001 — COM бросает разнотипные ошибки
            last_exc = exc
            if _is_class_not_registered_error(exc):
                _log_progress(f"step=com_error attempt={attempt} class_not_registered")
                raise OutlookAccessError(
                    f"{OUTLOOK_NOT_REGISTERED_MESSAGE} (детали COM: {exc})"
                ) from exc
            transient = _is_transient_com_error(exc)
            _log_progress(
                f"step=com_error attempt={attempt} transient={transient}: {exc}"
            )
            if transient and attempt < MAX_COM_ATTEMPTS:
                if com_initialized:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass
                    com_initialized = False
                time.sleep(COM_RETRY_DELAY_SECONDS * attempt)
                continue
            raise OutlookAccessError(_outlook_access_message(access_error_prefix, exc)) from exc
        finally:
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
    raise OutlookAccessError(
        _outlook_access_message(access_error_prefix, last_exc or RuntimeError("Outlook COM failed"))
    )


def _safe_str(value: Any) -> str:
    """Безопасно привести COM-значение к строке."""
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _decode_mime_header(value: str) -> str:
    """Тема IMAP/Outlook иногда приходит как =?utf-8?Q?...?= / =?utf-8?B?...?=."""
    text = _safe_str(value)
    if "=?" not in text:
        return text
    try:
        from email.header import decode_header, make_header

        return str(make_header(decode_header(text)))
    except Exception:
        return text


OL_MEETING = 1
OL_RECIPIENT_REQUIRED = 1
_PEOPLE_KEYS = (
    "people",
    "attendees",
    "required_attendees",
    "participants",
    "fios",
    "users",
    "calendars",
)
_ORGANIZER_KEYS = ("organizer", "organizer_fio", "calendar_owner", "for_user")


def _people_names(value: Any) -> list[str]:
    """Разобрать ФИО/почту из строки, списка или словаря."""
    names: list[str] = []
    if value is None or value is False:
        return names
    if isinstance(value, str):
        for part in re.split(r"[;\n,]+", value):
            name = part.strip()
            if name:
                names.append(name)
        return names
    if isinstance(value, dict):
        for key in ("fio", "name", "email", "display_name", "user"):
            names.extend(_people_names(value.get(key)))
        return names
    if isinstance(value, (list, tuple, set)):
        for item in value:
            names.extend(_people_names(item))
        return names
    text = _safe_str(value).strip()
    if text:
        names.append(text)
    return names


def _unique_people(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _people_from_input(data: dict | None, extra_keys: tuple[str, ...] = ()) -> list[str]:
    """Люди из полей people/attendees/… — для чтения чужих календарей и состава встречи."""
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    for key in (*_PEOPLE_KEYS, *extra_keys):
        if key in data:
            names.extend(_people_names(data.get(key)))
    return _unique_people(names)


def _organizer_from_input(data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    for key in _ORGANIZER_KEYS:
        name = _safe_str(data.get(key)).strip()
        if name:
            return name
    return ""


def _current_calendar_owner(namespace: Any) -> str:
    try:
        return _safe_str(namespace.CurrentUser.Name).strip()
    except Exception:
        return ""


def _ensure_mapi_logon(namespace: Any) -> None:
    """Подключить профиль, если Dispatch поднял Outlook без сессии."""
    try:
        current = getattr(namespace, "CurrentUser", None)
        if current is not None and _safe_str(getattr(current, "Name", "")).strip():
            return
    except Exception:
        pass
    try:
        namespace.Logon("", "", False, False)
        _log_progress("step=mapi_logon ok")
    except Exception as exc:
        _log_progress(f"step=mapi_logon skipped: {exc}")


def _mapi_namespace(outlook: Any) -> Any:
    namespace = outlook.GetNamespace("MAPI")
    _ensure_mapi_logon(namespace)
    return namespace


def _walk_typed_folder(root: Any, item_type: int, *, depth: int = 0) -> Any | None:
    if root is None or depth > 3:
        return None
    try:
        if int(getattr(root, "DefaultItemType", 0) or 0) == item_type:
            return root
    except Exception:
        pass
    try:
        children = root.Folders
    except Exception:
        return None
    try:
        for child in children:
            found = _walk_typed_folder(child, item_type, depth=depth + 1)
            if found is not None:
                return found
    except Exception:
        return None
    return None


def _find_typed_folder(namespace: Any, item_type: int) -> Any | None:
    try:
        for folder in namespace.Folders:
            found = _walk_typed_folder(folder, item_type)
            if found is not None:
                return found
    except Exception as exc:
        _log_progress(f"step=walk_folders skipped: {exc}")
    return None


def _default_folder(namespace: Any, folder_id: int) -> Any:
    """Папка профиля: Logon → GetDefaultFolder → store → обход дерева."""
    last_exc: Exception | None = None
    _ensure_mapi_logon(namespace)
    try:
        folder = namespace.GetDefaultFolder(folder_id)
        if folder is not None:
            return folder
    except Exception as exc:
        last_exc = exc
        _log_progress(f"step=default_folder_failed id={folder_id}: {exc}")
    try:
        for store in namespace.Stores:
            try:
                folder = store.GetDefaultFolder(folder_id)
            except Exception:
                continue
            if folder is not None:
                _log_progress(
                    f"step=default_folder_store id={folder_id} "
                    f"name={_safe_str(getattr(store, 'DisplayName', ''))}"
                )
                return folder
    except Exception as exc:
        last_exc = last_exc or exc
    item_type = OL_APPOINTMENT_ITEM if folder_id == CALENDAR_FOLDER_ID else 0
    walked = _find_typed_folder(namespace, item_type)
    if walked is not None:
        _log_progress(f"step=default_folder_walk id={folder_id}")
        return walked
    if folder_id == CALENDAR_FOLDER_ID:
        raise OutlookAccessError(
            "Календарь текущего профиля Outlook не найден (MAPI). "
            "Откройте классический Outlook с почтовым профилем и повторите. "
            f"({last_exc})"
        ) from last_exc
    raise OutlookAccessError(
        "Папка Outlook не найдена (MAPI). "
        "Откройте классический Outlook с почтовым профилем и повторите. "
        f"({last_exc})"
    ) from last_exc


def _same_calendar_person(left: str, right: str) -> bool:
    """ФИО из 1С и Display Name Outlook часто не совпадают буква в букву."""
    a = (left or "").strip().casefold()
    b = (right or "").strip().casefold()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    a_parts = a.replace(".", " ").split()
    b_parts = b.replace(".", " ").split()
    if not a_parts or not b_parts or a_parts[0] != b_parts[0] or len(a_parts[0]) < 4:
        return False
    if len(a_parts) > 1 and len(b_parts) > 1:
        return a_parts[1][0] == b_parts[1][0]
    return True


def _folder_matches_person(label: str, person: str) -> bool:
    """Папка «Календарь — Жалыбин» или store DisplayName совпадает с ФИО."""
    if _same_calendar_person(label, person):
        return True
    label_cf = (label or "").casefold()
    parts = (person or "").replace(".", " ").split()
    last = parts[0].casefold() if parts else ""
    return bool(last) and len(last) >= 4 and last in label_cf


def _calendar_access_hint(status: str) -> str:
    if status in {"own", "shared", "visible", "meetings"}:
        return ""
    return (
        "Нет доступа к этому календарю. Нужен общий доступ в Outlook "
        "или запуск с профиля владельца."
    )


PUBLIC_MEETINGS_FOLDER = "Совещания"


def _is_public_meetings_label(label: str) -> bool:
    """Общедоступный ящик «Совещания», не личный календарь."""
    text = (label or "").casefold()
    return "совещани" in text


def _find_public_meeting_folders(
    outlook: Any, namespace: Any, own_name: str = ""
) -> list[tuple[str, Any]]:
    """Календари общего ящика Совещания: панель, store, GetSharedDefaultFolder."""
    found: list[tuple[str, Any]] = []
    seen: set[str] = set()

    def add(label: str, folder: Any) -> None:
        if folder is None:
            return
        key = _folder_entry_id(folder) or f"{label}:{id(folder)}"
        if key in seen:
            return
        seen.add(key)
        found.append((label or PUBLIC_MEETINGS_FOLDER, folder))

    for label, folder, is_own in _iter_visible_calendar_folders(outlook, namespace, own_name):
        if is_own:
            continue
        if _is_public_meetings_label(label):
            add(label, folder)
    if not found:
        folder, _status = _open_shared_calendar(namespace, PUBLIC_MEETINGS_FOLDER)
        if folder is not None:
            add(PUBLIC_MEETINGS_FOLDER, folder)
    return found


def _resolve_person_calendar_folder(
    outlook: Any,
    namespace: Any,
    person: str,
    own_name: str,
) -> tuple[Any | None, str]:
    """Свой календарь, уже открытый в панели, затем GetSharedDefaultFolder.

    Чужой календарь не подменяем своим: иначе помощник ПСД читает свой ящик.
    """
    if not person or _same_calendar_person(person, own_name):
        return _own_calendar_folder(namespace), "own"
    visible = _iter_visible_calendar_folders(outlook, namespace, own_name)
    for label, folder, is_own in visible:
        if is_own or folder is None:
            continue
        if _folder_matches_person(label, person):
            return folder, "visible"
    folder, status = _open_shared_calendar(namespace, person)
    if folder is not None:
        return folder, status
    return None, status


OL_APPOINTMENT_ITEM = 1
OL_NAVIGATION_MODULE_CALENDAR = 1


def _iter_outlook_explorers(outlook: Any):
    """ActiveExplorer часто пуст у скрытого COM — берём все открытые окна."""
    seen: set[int] = set()
    try:
        active = outlook.ActiveExplorer()
    except Exception:
        active = None
    if active is not None:
        seen.add(id(active))
        yield active
    try:
        explorers = outlook.Explorers
    except Exception:
        return
    try:
        count = int(explorers.Count or 0)
    except Exception:
        count = 0
    for index in range(1, count + 1):
        try:
            explorer = explorers.Item(index)
        except Exception:
            continue
        key = id(explorer)
        if key in seen:
            continue
        seen.add(key)
        yield explorer


def _folder_entry_id(folder: Any) -> str:
    return _safe_str(getattr(folder, "EntryID", "")).strip()


def _folder_label(folder: Any, fallback: str = "") -> str:
    return _safe_str(getattr(folder, "Name", "")).strip() or fallback or "Календарь"


def _is_appointment_folder(folder: Any) -> bool:
    try:
        return int(getattr(folder, "DefaultItemType", 0) or 0) == OL_APPOINTMENT_ITEM
    except Exception:
        return False


def _iter_visible_calendar_folders(
    outlook: Any, namespace: Any, own_name: str = ""
) -> list[tuple[str, Any, bool]]:
    """Свой календарь + все календари из панели Outlook (в т.ч. «Совещания»)."""
    found: list[tuple[str, Any, bool]] = []
    seen: set[str] = set()
    own_label = (own_name or "").strip() or "Календарь"

    def add(folder: Any, label: str, is_own: bool = False) -> None:
        if folder is None:
            return
        key = _folder_entry_id(folder) or f"{label}:{id(folder)}"
        if key in seen:
            return
        seen.add(key)
        found.append((label, folder, is_own))

    try:
        add(_own_calendar_folder(namespace), own_label, True)
    except OutlookAccessError:
        pass

    try:
        seen_explorers = 0
        for explorer in _iter_outlook_explorers(outlook):
            seen_explorers += 1
            try:
                module = explorer.NavigationPane.Modules.GetNavigationModule(
                    OL_NAVIGATION_MODULE_CALENDAR
                )
            except Exception as exc:
                _log_progress(f"step=nav_module skipped: {exc}")
                continue
            for group in module.NavigationGroups:
                group_name = _safe_str(getattr(group, "Name", "")).strip()
                for nav in group.NavigationFolders:
                    try:
                        folder = nav.Folder
                    except Exception:
                        continue
                    add(folder, _folder_label(folder, group_name))
        if seen_explorers == 0:
            _log_progress("step=nav_calendars skipped: no explorer")
    except Exception as exc:
        _log_progress(f"step=nav_calendars skipped: {exc}")

    try:
        for store in namespace.Stores:
            try:
                add(store.GetDefaultFolder(CALENDAR_FOLDER_ID), _safe_str(store.DisplayName))
            except Exception:
                continue
    except Exception as exc:
        _log_progress(f"step=store_calendars skipped: {exc}")

    extra: list[tuple[str, Any]] = []
    for label, folder, _is_own in found:
        try:
            for sub in folder.Folders:
                if _is_appointment_folder(sub):
                    extra.append((_folder_label(sub, label), sub))
        except Exception:
            continue
    for label, folder in extra:
        add(folder, label)
    return found


def person_match_needles(person: str) -> list[str]:
    """Строки, по которым ищем участника в теме/организаторе/списке."""
    raw = (person or "").strip()
    if not raw:
        return []
    needles = [raw.casefold()]
    parts = raw.replace(".", " ").split()
    if parts:
        needles.append(parts[0].casefold())
        if len(parts) > 1:
            needles.append(f"{parts[0]} {parts[1][0]}".casefold())
            needles.append(parts[1].casefold())
    unique: list[str] = []
    seen: set[str] = set()
    for item in needles:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def event_involves_person(event: dict, person: str) -> bool:
    """Встреча относится к пользователю системы: организатор или участник."""
    if event.get("own_calendar"):
        return True
    name = (person or "").strip()
    if not name:
        return True
    hay = " ".join(
        [
            str(event.get("organizer") or ""),
            str(event.get("required_attendees") or ""),
            str(event.get("optional_attendees") or ""),
            str(event.get("subject") or ""),
            str(event.get("calendar_owner") or ""),
        ]
    ).casefold()
    if not hay.strip():
        return False
    parts = name.replace(".", " ").split()
    last = parts[0].casefold() if parts else ""
    if len(last) >= 4 and last not in hay:
        return False
    if len(parts) > 1:
        first = parts[1].casefold()
        if first in hay:
            return True
        if last and f"{last} {first[0]}" in hay:
            return True
        if len(first) >= 4 and first[:4] in hay:
            return True
        if last in hay:
            return True
        return False
    return last in hay if last else False


def _dedupe_calendar_events(events: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in events:
        key = "|".join(
            [
                str(item.get("entry_id") or ""),
                str(item.get("start") or ""),
                str(item.get("subject") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _own_calendar_folder(namespace: Any) -> Any:
    """Календарь профиля, который уже открыт в Outlook. MAPI_E_NOT_FOUND = нет профиля."""
    return _default_folder(namespace, CALENDAR_FOLDER_ID)


def _open_shared_calendar(namespace: Any, person: str) -> tuple[Any | None, str]:
    """Календарь сотрудника через адресную книгу Outlook. None если нет прав или не найден."""
    name = (person or "").strip()
    if not name:
        return None, "empty"
    try:
        recipient = namespace.CreateRecipient(name)
        recipient.Resolve()
    except Exception as exc:
        return None, f"unresolved:{exc}"
    try:
        resolved = bool(recipient.Resolved)
    except Exception:
        resolved = False
    if not resolved:
        return None, "unresolved"
    try:
        folder = namespace.GetSharedDefaultFolder(recipient, CALENDAR_FOLDER_ID)
    except Exception as exc:
        return None, f"denied:{exc}"
    if folder is None:
        return None, "denied"
    return folder, "shared"


def _prepare_calendar_items(folder: Any, *, include_recurrences: bool = True) -> Any:
    items = folder.Items
    try:
        items.IncludeRecurrences = bool(include_recurrences)
    except Exception:
        pass
    try:
        items.Sort("[Start]")
    except Exception:
        pass
    return items


def _attach_attendees(appt: Any, names: list[str]) -> list[str]:
    """Пометить встречу как совещание и внести обязательных участников."""
    added: list[str] = []
    if not names:
        return added
    try:
        appt.MeetingStatus = OL_MEETING
    except Exception:
        _log_progress("step=meeting_status skipped")
    recipients = getattr(appt, "Recipients", None)
    if recipients is None:
        return added
    for name in names:
        try:
            recipient = recipients.Add(name)
        except Exception as exc:
            _log_progress(f"step=attendee_add_failed name={name}: {exc}")
            continue
        try:
            recipient.Type = OL_RECIPIENT_REQUIRED
        except Exception:
            pass
        added.append(name)
    try:
        recipients.ResolveAll()
    except Exception:
        _log_progress("step=attendees_resolve skipped")
    return added


def _matches_query(subject: str, body: str, query: str | None) -> bool:
    """Проверить, подходит ли письмо под простой query с поддержкой OR."""
    if query is None or not query.strip():
        return True

    haystack = f"{subject}\n{body}".casefold()
    terms = [
        term.strip().casefold()
        for term in re.split(r"\s+OR\s+", query, flags=re.IGNORECASE)
        if term.strip()
    ]
    if not terms:
        return True

    return any(term in haystack for term in terms)


def _resolve_mail_folder_specs(folder_value: object) -> list[tuple[str, int, str, str, str]]:
    """Вернуть папки Outlook для чтения почты.

    Поддерживаются:
    - Inbox / Входящие;
    - Sent / SentItems / Отправленные;
    - All / Все — входящие и отправленные.
    """
    folder = _safe_str(folder_value or DEFAULT_FOLDER).strip().casefold()
    inbox = (DEFAULT_FOLDER, INBOX_FOLDER_ID, "[ReceivedTime]", "ReceivedTime", "inbox")
    sent = (SENT_FOLDER, SENT_FOLDER_ID, "[SentOn]", "SentOn", "sent")
    inbox_aliases = {"inbox", "входящие", "incoming", "received"}
    sent_aliases = {"sent", "sentitems", "sent mail", "отправленные", "исходящие"}
    all_aliases = {"all", "все", "inbox+sent", "both", "входящие+отправленные"}
    if folder in inbox_aliases:
        return [inbox]
    if folder in sent_aliases:
        return [sent]
    if folder in all_aliases:
        return [inbox, sent]
    raise OutlookComError(
        "UNSUPPORTED_FOLDER: поддерживаются Inbox, Sent или All"
    )


def search_mail(input_data: dict) -> dict:
    """Безопасно прочитать входящие/отправленные письма Outlook без изменений."""
    _log_progress("step=load_pywin32 start")
    days = _clamp_int(input_data.get("days"), DEFAULT_DAYS, 1, MAX_DAYS)
    max_results = _clamp_int(
        input_data.get("max_results"),
        DEFAULT_MAX_RESULTS,
        1,
        MAX_RESULTS,
    )
    max_scan_items = _clamp_int(
        input_data.get("max_scan_items"),
        DEFAULT_MAIL_MAX_SCAN_ITEMS,
        1,
        MAX_SCAN_ITEMS,
    )
    query = input_data.get("query")
    start_at, end_at = _resolve_date_range(
        input_data,
        default_days=days,
        forward=False,
    )
    folder_specs = _resolve_mail_folder_specs(input_data.get("folder"))

    def _read(win32com_client: Any) -> dict:
        _log_progress("step=dispatch_outlook start")
        outlook = _dispatch_outlook(win32com_client)
        _log_progress("step=dispatch_outlook ok")
        _log_progress("step=get_namespace start")
        namespace = _mapi_namespace(outlook)
        _log_progress("step=get_namespace ok")

        results = []
        scanned_count = 0
        for folder_name, folder_id, sort_field, date_attr, direction in folder_specs:
            _log_progress(f"step=get_mail_folder start folder={folder_name}")
            folder_obj = _default_folder(namespace, folder_id)
            _log_progress(f"step=get_mail_folder ok folder={folder_name}")
            _log_progress(f"step=get_items start folder={folder_name}")
            messages = folder_obj.Items
            _log_progress(f"step=get_items ok folder={folder_name}")
            _log_progress(f"step=sort_items start folder={folder_name}")
            messages.Sort(sort_field, True)
            _log_progress(f"step=sort_items ok folder={folder_name}")

            folder_results, folder_scanned = _collect_mail_messages(
                messages,
                folder_name=folder_name,
                date_attr=date_attr,
                direction=direction,
                query=_safe_str(query) if query else None,
                start_at=start_at,
                end_at=end_at,
                max_results=max_results - len(results),
                max_scan_items=max_scan_items,
            )
            scanned_count += folder_scanned
            results.extend(folder_results)
            if len(results) >= max_results:
                break

        results.sort(key=lambda item: item.get("datetime_sort") or "", reverse=True)
        for item in results:
            item.pop("datetime_sort", None)

        _log_progress("step=done ok")
        payload = {
            "messages": results,
            "count": len(results),
            "scanned_count": scanned_count,
            "source": "outlook_com",
            "folder": _safe_str(input_data.get("folder") or DEFAULT_FOLDER),
            "folders": [item[0] for item in folder_specs],
            "range_start": start_at.isoformat(),
            "range_end": end_at.isoformat(),
        }
        if not results:
            payload["hint"] = (
                "Писем по этому query нет. Не повторяй поиск с другими словами "
                "и не подставляй список ФИО в query."
            )
        return payload

    return _run_com_read(_read, "Ошибка доступа к Outlook или MAPI")


def read_calendar(input_data: dict) -> dict:
    """Прочитать встречи своего и чужих календарей Outlook (если есть доступ)."""
    _log_progress("step=load_pywin32 start")
    days_forward = _clamp_int(
        input_data.get("days_forward"),
        DEFAULT_DAYS_FORWARD,
        1,
        MAX_DAYS,
    )
    max_results = _clamp_int(
        input_data.get("max_results"),
        DEFAULT_CALENDAR_MAX_RESULTS,
        1,
        MAX_CALENDAR_RESULTS,
    )
    max_scan_items = _clamp_int(
        input_data.get("max_scan_items"),
        DEFAULT_CALENDAR_MAX_SCAN_ITEMS,
        1,
        MAX_SCAN_ITEMS,
    )
    include_body = _truthy(input_data.get("include_body"))
    people = _people_from_input(input_data)
    filter_user = (
        _safe_str(input_data.get("for_user") or input_data.get("filter_user") or "").strip()
    )
    folder_hint = _safe_str(input_data.get("folder") or input_data.get("calendar") or "").strip()
    all_visible = _truthy(input_data.get("all_visible"))

    def _read(win32com_client: Any) -> dict:
        _log_progress("step=dispatch_outlook start")
        outlook = _dispatch_outlook(win32com_client)
        _log_progress("step=dispatch_outlook ok")
        _log_progress("step=get_namespace start")
        namespace = _mapi_namespace(outlook)
        _log_progress("step=get_namespace ok")
        start_at, end_at = _resolve_date_range(
            input_data,
            default_days=days_forward,
            forward=True,
        )
        own_name = _current_calendar_owner(namespace)
        events: list[dict] = []
        checked_count = 0
        calendars: list[dict] = []
        want_meetings = _is_public_meetings_label(folder_hint) or bool(people)
        if want_meetings:
            meeting_folders = _find_public_meeting_folders(outlook, namespace, own_name)
            _log_progress(f"step=meetings_folders count={len(meeting_folders)}")
            if meeting_folders:
                for label, folder in meeting_folders:
                    remaining_results = max_results - len(events)
                    remaining_scan = max_scan_items - checked_count
                    if remaining_results <= 0 or remaining_scan <= 0:
                        break
                    try:
                        items = _prepare_calendar_items(folder)
                    except Exception as exc:
                        calendars.append(
                            {"person": label, "status": f"items:{exc}", "count": 0}
                        )
                        continue
                    chunk, scanned = _collect_calendar_range(
                        items,
                        start_at,
                        end_at,
                        max_results=remaining_results,
                        max_scan_items=remaining_scan,
                        include_body=include_body,
                        calendar_owner=label,
                        own_calendar=False,
                    )
                    if not chunk and scanned == 0:
                        try:
                            plain = _prepare_calendar_items(
                                folder, include_recurrences=False
                            )
                            chunk, scanned = _collect_calendar_range(
                                plain,
                                start_at,
                                end_at,
                                max_results=remaining_results,
                                max_scan_items=remaining_scan,
                                include_body=include_body,
                                calendar_owner=label,
                                own_calendar=False,
                            )
                        except Exception as exc:
                            _log_progress(f"step=meetings_retry_failed: {exc}")
                    checked_count += scanned
                    events.extend(chunk)
                    calendars.append(
                        {"person": label, "status": "meetings", "count": len(chunk)}
                    )
                    _log_progress(
                        f"step=meetings_ok folder={label} events={len(chunk)} "
                        f"scanned={scanned}"
                    )
                events = _dedupe_calendar_events(events)
                filters = _unique_people([*people, filter_user] if filter_user else people)
                if filters:
                    before = len(events)
                    events = [
                        item
                        for item in events
                        if any(event_involves_person(item, name) for name in filters)
                    ]
                    _log_progress(
                        f"step=filter_meetings names={filters} "
                        f"before={before} after={len(events)}"
                    )
                events.sort(key=lambda item: str(item.get("start") or ""))
                _log_progress("step=done ok")
                return {
                    "events": events,
                    "count": len(events),
                    "free_slots": _compute_free_slots(events, start_at, end_at),
                    "calendars": calendars,
                    "scanned_count": checked_count,
                    "source": "outlook_com",
                    "folder": PUBLIC_MEETINGS_FOLDER,
                    "filter_user": ", ".join(filters),
                    "range_start": start_at.isoformat(),
                    "range_end": end_at.isoformat(),
                }
            if _is_public_meetings_label(folder_hint):
                _log_progress("step=meetings_folder_missing")
                return {
                    "events": [],
                    "count": 0,
                    "free_slots": [],
                    "calendars": [
                        {
                            "person": PUBLIC_MEETINGS_FOLDER,
                            "status": "missing",
                            "count": 0,
                            "hint": (
                                "Календарь «Совещания» не найден. "
                                "Откройте общедоступный ящик в классическом Outlook."
                            ),
                        }
                    ],
                    "scanned_count": 0,
                    "source": "outlook_com",
                    "folder": PUBLIC_MEETINGS_FOLDER,
                    "range_start": start_at.isoformat(),
                    "range_end": end_at.isoformat(),
                }
        if all_visible:
            folders = _iter_visible_calendar_folders(outlook, namespace, own_name)
            if not folders:
                folders = [(own_name or "Календарь", _own_calendar_folder(namespace), True)]
            _log_progress(f"step=visible_calendars count={len(folders)}")
            for label, folder, is_own in folders:
                remaining_results = max_results - len(events)
                remaining_scan = max_scan_items - checked_count
                if remaining_results <= 0 or remaining_scan <= 0:
                    break
                try:
                    items = _prepare_calendar_items(folder)
                except Exception as exc:
                    calendars.append({"person": label, "status": f"items:{exc}", "count": 0})
                    continue
                try:
                    chunk, scanned = _collect_calendar_range(
                        items,
                        start_at,
                        end_at,
                        max_results=remaining_results,
                        max_scan_items=remaining_scan,
                        include_body=include_body,
                        calendar_owner=label,
                        own_calendar=is_own,
                    )
                except Exception as exc:
                    _log_progress(f"step=calendar_skip folder={label}: {exc}")
                    calendars.append({"person": label, "status": f"skip:{exc}", "count": 0})
                    continue
                checked_count += scanned
                events.extend(chunk)
                calendars.append(
                    {
                        "person": label,
                        "status": "own" if is_own else "visible",
                        "count": len(chunk),
                    }
                )
                _log_progress(
                    f"step=calendar_ok folder={label} own={int(is_own)} "
                    f"events={len(chunk)} scanned={scanned}"
                )
            events = _dedupe_calendar_events(events)
            if filter_user:
                before = len(events)
                events = [item for item in events if event_involves_person(item, filter_user)]
                _log_progress(
                    f"step=filter_user name={filter_user} before={before} after={len(events)}"
                )
            events.sort(key=lambda item: str(item.get("start") or ""))
            _log_progress("step=done ok")
            return {
                "events": events,
                "count": len(events),
                "free_slots": _compute_free_slots(events, start_at, end_at),
                "calendars": calendars,
                "scanned_count": checked_count,
                "source": "outlook_com",
                "folder": "visible",
                "filter_user": filter_user,
                "range_start": start_at.isoformat(),
                "range_end": end_at.isoformat(),
            }
        targets = people or [own_name or ""]
        for person in targets:
            remaining_results = max_results - len(events)
            remaining_scan = max_scan_items - checked_count
            if remaining_results <= 0 or remaining_scan <= 0:
                break
            folder = None
            status = "own"
            owner = person or own_name
            if not person or _same_calendar_person(person, own_name):
                folder = _own_calendar_folder(namespace)
                status = "own"
            else:
                _log_progress(f"step=resolve_calendar person={person}")
                folder, status = _resolve_person_calendar_folder(
                    outlook, namespace, person, own_name
                )
                _log_progress(
                    f"step=resolve_calendar_done person={person} status={status} "
                    f"found={int(folder is not None)}"
                )
            if folder is None:
                entry = {"person": owner, "status": status, "count": 0}
                hint = _calendar_access_hint(status)
                if hint:
                    entry["hint"] = hint
                calendars.append(entry)
                continue
            try:
                items = _prepare_calendar_items(folder)
            except Exception as exc:
                _log_progress(f"step=prepare_items_failed person={owner}: {exc}")
                if status == "own":
                    raise OutlookAccessError(
                        "Не удалось открыть календарь текущего профиля Outlook. "
                        "Нужен классический Outlook с загруженным почтовым профилем. "
                        f"({exc})"
                    ) from exc
                calendars.append(
                    {
                        "person": owner,
                        "status": f"items:{exc}",
                        "count": 0,
                        "hint": _calendar_access_hint("denied"),
                    }
                )
                continue
            chunk, scanned = _collect_calendar_range(
                items,
                start_at,
                end_at,
                max_results=remaining_results,
                max_scan_items=remaining_scan,
                include_body=include_body,
                calendar_owner=owner,
                own_calendar=status == "own",
            )
            if not chunk and status != "own":
                _log_progress(f"step=retry_without_recurrences person={owner}")
                try:
                    plain_items = _prepare_calendar_items(folder, include_recurrences=False)
                    retry_chunk, retry_scanned = _collect_calendar_range(
                        plain_items,
                        start_at,
                        end_at,
                        max_results=remaining_results,
                        max_scan_items=remaining_scan,
                        include_body=include_body,
                        calendar_owner=owner,
                        own_calendar=False,
                    )
                except Exception as exc:
                    _log_progress(f"step=retry_without_recurrences_failed: {exc}")
                    retry_chunk, retry_scanned = [], 0
                if retry_chunk:
                    chunk, scanned = retry_chunk, retry_scanned
                elif scanned == 0 and retry_scanned == 0:
                    status = "unreadable"
            checked_count += scanned
            events.extend(chunk)
            entry = {"person": owner, "status": status, "count": len(chunk)}
            hint = _calendar_access_hint(status)
            if hint:
                entry["hint"] = hint
            calendars.append(entry)
            _log_progress(
                f"step=calendar_ok person={owner} status={status} events={len(chunk)}"
            )

        events.sort(key=lambda item: str(item.get("start") or ""))
        _log_progress("step=done ok")
        return {
            "events": events,
            "count": len(events),
            "free_slots": _compute_free_slots(events, start_at, end_at),
            "calendars": calendars,
            "scanned_count": checked_count,
            "source": "outlook_com",
            "folder": CALENDAR_FOLDER,
            "range_start": start_at.isoformat(),
            "range_end": end_at.isoformat(),
        }

    return _run_com_read(_read, "Ошибка доступа к Outlook Calendar")


AI_AGENT_SUBJECT_PREFIX = "[ИИ-агент] "
AI_AGENT_BODY_FOOTER = "Создано ИИ-агентом Constructor."
AI_AGENT_CATEGORY = "ИИ-агент"
DEFAULT_MEETING_MINUTES = 60


def stamp_ai_agent_meeting(subject: str, body: str = "") -> tuple[str, str]:
    """Пометить тему и текст, что встречу создал ИИ-агент."""
    title = (subject or "").strip() or "Совещание"
    if not title.casefold().startswith("[ии-агент]"):
        title = f"{AI_AGENT_SUBJECT_PREFIX}{title}"
    text = (body or "").strip()
    if AI_AGENT_BODY_FOOTER.casefold() not in text.casefold():
        text = f"{text}\n\n{AI_AGENT_BODY_FOOTER}".strip()
    return title, text


def create_event(input_data: dict) -> dict:
    """Создать встречи Outlook. С attendees — совещание с участниками; organizer — чей календарь."""
    items = _meeting_specs(input_data)
    if not items:
        raise OutlookComError("Нужны subject и start или массив events")

    def _write(win32com_client: Any) -> dict:
        _log_progress("step=dispatch_outlook start")
        outlook = _dispatch_outlook(win32com_client)
        _log_progress("step=dispatch_outlook ok")
        namespace = _mapi_namespace(outlook)
        own_name = _current_calendar_owner(namespace)
        created: list[dict] = []
        for spec in items:
            organizer = spec["organizer"]
            attendees = spec["attendees"]
            folder = None
            organizer_status = "own"
            if organizer and (not own_name or organizer.casefold() != own_name.casefold()):
                folder, organizer_status = _open_shared_calendar(namespace, organizer)
                if folder is None:
                    _log_progress(
                        f"step=organizer_fallback person={organizer} status={organizer_status}"
                    )
                    folder = _own_calendar_folder(namespace)
                    organizer_status = f"fallback_own:{organizer_status}"
            else:
                folder = _own_calendar_folder(namespace)
            appt = _new_appointment(outlook, folder)
            appt.Subject = spec["subject"]
            _set_appointment_times(appt, spec["start"], spec["end"])
            try:
                appt.ReminderSet = False
            except Exception:
                pass
            added = _attach_attendees(appt, attendees)
            appt.Save()
            entry_id = _verify_saved_appointment(outlook, appt)
            if spec["body"]:
                try:
                    appt.Body = spec["body"]
                    appt.Save()
                except Exception:
                    _log_progress("step=body skipped")
            if spec["location"]:
                try:
                    appt.Location = spec["location"]
                    appt.Save()
                except Exception:
                    _log_progress("step=location skipped")
            try:
                appt.Categories = AI_AGENT_CATEGORY
                appt.Save()
            except Exception:
                _log_progress("step=category skipped")
            invites_sent = False
            if added and spec["send_invites"]:
                try:
                    appt.Send()
                    invites_sent = True
                    _log_progress("step=send_invites ok")
                except Exception as exc:
                    _log_progress(f"step=send_invites failed: {exc}")
            created.append(
                {
                    "entry_id": entry_id,
                    "subject": spec["subject"],
                    "start": spec["start"].isoformat(timespec="minutes"),
                    "end": spec["end"].isoformat(timespec="minutes"),
                    "location": spec["location"],
                    "organizer": organizer or own_name,
                    "organizer_status": organizer_status,
                    "attendees": added,
                    "invites_sent": invites_sent,
                    "ai_agent": True,
                }
            )
        _log_progress(f"step=create_event ok count={len(created)}")
        return {
            "ok": True,
            "event": created[0] if created else {},
            "events": created,
            "count": len(created),
            "source": "outlook_com",
        }

    return _run_com_read(_write, "Ошибка записи встречи в Outlook Calendar")


def _dispatch_outlook(win32com_client: Any) -> Any:
    """Взять уже открытый Outlook, иначе создать COM-сессию и залогинить профиль."""
    _log_progress("step=dispatch_outlook start")
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            outlook = win32com_client.GetActiveObject("Outlook.Application")
            _ensure_mapi_logon(outlook.GetNamespace("MAPI"))
            _log_progress(f"step=dispatch_active ok attempt={attempt}")
            return outlook
        except Exception as exc:
            last_exc = exc
            _log_progress(f"step=dispatch_active failed attempt={attempt}: {exc}")
            time.sleep(0.35 * attempt)
    outlook = win32com_client.Dispatch("Outlook.Application")
    try:
        _ensure_mapi_logon(outlook.GetNamespace("MAPI"))
    except Exception as exc:
        _log_progress(f"step=dispatch_new_logon skipped: {exc}")
    if last_exc is not None:
        _log_progress(f"step=dispatch_new after_active_fail: {last_exc}")
    return outlook


def _mapi_namespace(outlook: Any) -> Any:
    """MAPI без диалога пароля — профиль уже открыт в Outlook (как read_calendar)."""
    namespace = outlook.GetNamespace("MAPI")
    try:
        namespace.Logon("", "", False, False)
    except Exception as exc:  # noqa: BLE001
        _log_progress(f"step=mapi_logon noop: {exc}")
    return namespace


def _verify_saved_appointment(outlook: Any, appt: Any) -> str:
    """Save без ошибки ещё не значит, что встреча в календаре. Перечитываем."""
    entry_id = _safe_str(getattr(appt, "EntryID", ""))
    if not entry_id:
        raise OutlookAccessError(
            "Ошибка записи встречи: Outlook не вернул идентификатор после Save. "
            "Встреча в календарь не попала. Нужен классический Outlook и свой календарь для записи."
        )
    try:
        namespace = _mapi_namespace(outlook)
        found = namespace.GetItemFromID(entry_id)
    except Exception as exc:
        raise OutlookAccessError(
            "Ошибка записи встречи: после Save элемент не читается из календаря. "
            f"{exc}"
        ) from exc
    if found is None:
        raise OutlookAccessError(
            "Ошибка записи встречи: после Save элемент в календаре не найден."
        )
    subject = _safe_str(getattr(found, "Subject", ""))
    if not subject:
        raise OutlookAccessError(
            "Ошибка записи встречи: сохранённый элемент без темы, запись не подтверждена."
        )
    _log_progress(f"step=verify_save ok entry_id={entry_id[:12]}")
    return entry_id


def _new_appointment(outlook: Any, folder: Any = None) -> Any:
    """Создать встречу в указанном календаре, иначе в календаре профиля."""
    calendar = folder
    if calendar is None:
        try:
            calendar = _own_calendar_folder(_mapi_namespace(outlook))
        except Exception:
            calendar = None
    if calendar is not None:
        try:
            return calendar.Items.Add()
        except Exception:
            try:
                return calendar.Items.Add(1)
            except Exception:
                pass
    return outlook.CreateItem(1)


def _set_appointment_times(appt: Any, start: datetime, end: datetime) -> None:
    """Start/End: pywintypes, затем datetime, затем строка — Outlook капризен к типу."""
    try:
        pywintypes = importlib.import_module("pywintypes")
        appt.Start = pywintypes.Time(start)
        appt.End = pywintypes.Time(end)
        return
    except Exception:
        _log_progress("step=pywintypes_time_failed")
    try:
        appt.Start = start
        appt.End = end
        return
    except Exception:
        _log_progress("step=datetime_assign_failed")
    start_text = start.strftime("%Y-%m-%d %H:%M:%S")
    end_text = end.strftime("%Y-%m-%d %H:%M:%S")
    try:
        appt.Start = start_text
        appt.End = end_text
        return
    except Exception:
        _log_progress("step=start_iso_failed try_locale")
    appt.Start = start.strftime("%d.%m.%Y %H:%M:%S")
    appt.End = end.strftime("%d.%m.%Y %H:%M:%S")


def _meeting_specs(input_data: dict) -> list[dict]:
    raw_events = input_data.get("events")
    rows: list[dict]
    if isinstance(raw_events, list) and raw_events:
        rows = [item for item in raw_events if isinstance(item, dict)]
    else:
        rows = [input_data]
    specs: list[dict] = []
    for row in rows:
        subject, body = stamp_ai_agent_meeting(
            str(row.get("subject") or row.get("title") or ""),
            str(row.get("body") or row.get("text") or ""),
        )
        start = _coerce_datetime(row.get("start") or row.get("start_at"))
        if start is None:
            continue
        end = _coerce_datetime(row.get("end") or row.get("end_at"))
        if end is None:
            minutes = _clamp_int(
                row.get("duration_minutes") or input_data.get("duration_minutes"),
                DEFAULT_MEETING_MINUTES,
                15,
                24 * 60,
            )
            end = start + timedelta(minutes=minutes)
        if end <= start:
            end = start + timedelta(minutes=DEFAULT_MEETING_MINUTES)
        attendees = _people_from_input(row) or _people_from_input(input_data)
        organizer = _organizer_from_input(row) or _organizer_from_input(input_data)
        send_raw = row.get("send_invites", input_data.get("send_invites"))
        if send_raw is None:
            send_invites = bool(attendees)
        else:
            send_invites = _truthy(send_raw)
        specs.append(
            {
                "subject": subject,
                "body": body,
                "start": start,
                "end": end,
                "location": _safe_str(row.get("location") or "").strip(),
                "attendees": attendees,
                "organizer": organizer,
                "send_invites": send_invites,
            }
        )
    return specs


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = _safe_str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 else text, fmt)
        except ValueError:
            continue
    return None


def _compute_free_slots(
    events: list[dict],
    range_start: datetime,
    range_end: datetime,
    *,
    work_start_hour: int = 9,
    work_end_hour: int = 18,
    min_minutes: int = 30,
) -> list[dict]:
    """Рабочие окна без занятых встреч Outlook — свободные ячейки календаря."""
    busy: list[tuple[datetime, datetime]] = []
    for event in events:
        start = _coerce_datetime(event.get("start"))
        end = _coerce_datetime(event.get("end"))
        if start is None:
            continue
        if end is None:
            end = start + timedelta(minutes=30)
        if end <= range_start or start >= range_end:
            continue
        busy.append((max(start, range_start), min(end, range_end)))
    busy.sort()
    merged: list[list[datetime]] = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    slots: list[dict] = []
    day = range_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < range_end:
        if day.weekday() < 5:
            win_s = max(day.replace(hour=work_start_hour), range_start)
            win_e = min(day.replace(hour=work_end_hour), range_end)
            if win_e > win_s:
                cursor = win_s
                for b_s, b_e in merged:
                    if b_e <= cursor or b_s >= win_e:
                        continue
                    gap_end = min(b_s, win_e)
                    minutes = int((gap_end - cursor).total_seconds() // 60)
                    if minutes >= min_minutes:
                        slots.append(
                            {
                                "start": cursor.isoformat(timespec="minutes"),
                                "end": gap_end.isoformat(timespec="minutes"),
                                "minutes": minutes,
                            }
                        )
                    cursor = max(cursor, b_e)
                    if cursor >= win_e:
                        break
                minutes = int((win_e - cursor).total_seconds() // 60)
                if minutes >= min_minutes:
                    slots.append(
                        {
                            "start": cursor.isoformat(timespec="minutes"),
                            "end": win_e.isoformat(timespec="minutes"),
                            "minutes": minutes,
                        }
                    )
        day += timedelta(days=1)
    return slots


def send_mail_disabled(input_data: dict) -> dict:
    """Всегда заблокировать отправку писем в безопасном режиме."""
    raise DangerousOutlookActionBlockedError(
        "Отправка писем через Outlook COM отключена в безопасном режиме"
    )


def create_draft_disabled(input_data: dict) -> dict:
    """Всегда заблокировать создание черновиков в безопасном режиме."""
    raise DangerousOutlookActionBlockedError(
        "Создание черновиков через Outlook COM пока отключено в безопасном режиме"
    )


def _calendar_range_start(input_data: dict) -> datetime:
    """Вернуть начало диапазона календаря.

    По умолчанию читаем весь текущий день с 00:00, а не только события после
    текущего времени. Иначе запрос "что у меня сегодня" пропускает уже
    начавшиеся или прошедшие утром совещания.
    """
    date_value = input_data.get("date") or input_data.get("date_from")
    if isinstance(date_value, str) and date_value.strip():
        try:
            parsed = datetime.fromisoformat(date_value.strip())
            return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            pass
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _resolve_date_range(
    input_data: dict,
    *,
    default_days: int,
    forward: bool,
) -> tuple[datetime, datetime]:
    """Разобрать date/date_from/date_to или построить относительный диапазон.

    - date=YYYY-MM-DD читает конкретный день целиком;
    - date_from/date_to читают включительный диапазон дат;
    - если дат нет, календарь читает с начала сегодняшнего дня вперёд, почта —
      последние N дней до текущего момента.
    """
    now = datetime.now()
    if date_value := _safe_str(input_data.get("date")).strip():
        start = _parse_date_boundary(date_value, is_end=False)
        return start, start + timedelta(days=1)

    date_from = _safe_str(input_data.get("date_from")).strip()
    date_to = _safe_str(input_data.get("date_to")).strip()
    if date_from or date_to:
        if date_from:
            start = _parse_date_boundary(date_from, is_end=False)
        elif forward:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            end_for_start = _parse_date_boundary(date_to, is_end=True)
            start = end_for_start - timedelta(days=default_days)

        if date_to:
            end = _parse_date_boundary(date_to, is_end=True)
        else:
            end = start + timedelta(days=default_days)
        if end <= start:
            end = start + timedelta(days=1)
        return start, end

    if forward:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=default_days)
    return now - timedelta(days=default_days), now


def _parse_date_boundary(value: str, *, is_end: bool) -> datetime:
    """Распарсить ISO/natural дату или дату-время в границу диапазона."""
    stripped = value.strip()
    natural = _parse_natural_date(stripped)
    if natural is not None:
        start_of_day = natural.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day + timedelta(days=1) if is_end else start_of_day
    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        try:
            parsed = datetime.strptime(stripped, "%Y-%m-%d")
        except ValueError as exc:
            raise OutlookComError(
                "INVALID_DATE_RANGE: дата должна быть YYYY-MM-DD, ISO datetime "
                "или today/сегодня/tomorrow/завтра/yesterday/вчера"
            ) from exc
    if "T" in stripped or re.search(r"\d{1,2}:\d{2}", stripped):
        return parsed.replace(tzinfo=None)
    start_of_day = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_of_day + timedelta(days=1) if is_end else start_of_day


def _parse_natural_date(value: str) -> datetime | None:
    """Распарсить простые естественные даты, которые часто возвращает LLM."""
    normalized = value.strip().casefold()
    today_aliases = {"today", "сегодня", "now", "сейчас"}
    tomorrow_aliases = {"tomorrow", "завтра"}
    yesterday_aliases = {"yesterday", "вчера"}
    now = datetime.now()
    if normalized in today_aliases:
        return now
    if normalized in tomorrow_aliases:
        return now + timedelta(days=1)
    if normalized in yesterday_aliases:
        return now - timedelta(days=1)
    return None


def _iter_outlook_items(items: Any):
    """Обойти Outlook Items через GetFirst/GetNext, не трогая Count.

    win32com ``for item in items`` для коллекций с IncludeRecurrences часто
    вызывает Count, а Count на годе повторяющихся встреч может висеть минутами.
    """
    getter = getattr(items, "GetFirst", None)
    nxt = getattr(items, "GetNext", None)
    if callable(getter) and callable(nxt):
        try:
            item = getter()
        except Exception as exc:
            if _is_mapi_not_found(exc):
                _log_progress(f"step=getfirst_not_found: {exc}")
                return
            raise
        while item is not None:
            yield item
            try:
                item = nxt()
            except Exception as exc:
                if _is_mapi_not_found(exc):
                    _log_progress(f"step=getnext_not_found: {exc}")
                    return
                raise
        return
    for item in items:
        yield item


def _month_windows(start_at: datetime, end_at: datetime) -> list[tuple[datetime, datetime]]:
    """Разрезать длинный период на месячные окна для Restrict."""
    windows: list[tuple[datetime, datetime]] = []
    cursor = start_at
    while cursor < end_at:
        if cursor.month == 12:
            nxt = cursor.replace(
                year=cursor.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        else:
            nxt = cursor.replace(
                month=cursor.month + 1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        windows.append((cursor, min(nxt, end_at)))
        cursor = nxt
    return windows


def _collect_calendar_range(
    items: Any,
    start_at: datetime,
    end_at: datetime,
    *,
    max_results: int,
    max_scan_items: int,
    include_body: bool,
    calendar_owner: str = "",
    own_calendar: bool = False,
) -> tuple[list[dict], int]:
    """Прочитать календарь окнами по месяцу, без годового Restrict и без Count."""
    events: list[dict] = []
    checked_count = 0
    for win_start, win_end in _month_windows(start_at, end_at):
        remaining_results = max_results - len(events)
        remaining_scan = max_scan_items - checked_count
        if remaining_results <= 0 or remaining_scan <= 0:
            break
        _log_progress(
            f"step=restrict_window start={win_start.date()} end={win_end.date()}"
        )
        chunk: list[dict] = []
        scanned = 0
        tried_restrict = False
        for restriction, window_items in _iter_restricted_calendar_items(items, win_start, win_end):
            tried_restrict = True
            _log_progress(f"step=restrict_try filter={restriction}")
            try:
                chunk, scanned = _collect_calendar_events(
                    window_items,
                    start_at,
                    end_at,
                    remaining_results,
                    remaining_scan,
                    include_body=include_body,
                    calendar_owner=calendar_owner,
                    own_calendar=own_calendar,
                )
            except Exception as exc:
                if _is_mapi_not_found(exc):
                    _log_progress(f"step=restrict_not_found filter={restriction}")
                    continue
                raise
            if chunk:
                break
        if not tried_restrict:
            _log_progress("step=restrict_window fallback_getfirst")
            chunk, scanned = _collect_calendar_events(
                items,
                start_at,
                end_at,
                remaining_results,
                remaining_scan,
                include_body=include_body,
                calendar_owner=calendar_owner,
                own_calendar=own_calendar,
            )
            return chunk, scanned
        checked_count += scanned
        events.extend(chunk)
        _log_progress(
            f"step=restrict_window ok scanned={scanned} events={len(events)}"
        )
    return events, checked_count


def _collect_calendar_events(
    items: Any,
    start_at: datetime,
    end_at: datetime,
    max_results: int,
    max_scan_items: int,
    include_body: bool = False,
    calendar_owner: str = "",
    own_calendar: bool = False,
) -> tuple[list[dict], int]:
    """Собрать события календаря из COM collection в указанном диапазоне."""
    events = []
    checked_count = 0
    for event in _iter_outlook_items(items):
        checked_count += 1
        if checked_count > max_scan_items:
            break
        if checked_count == 1 or checked_count % 50 == 0:
            _log_progress(f"step=iterate_items progress={checked_count}")

        try:
            event_start = getattr(event, "Start", None)
            event_end = getattr(event, "End", None)
        except Exception as exc:
            if _is_mapi_not_found(exc):
                _log_progress(f"step=item_not_found progress={checked_count}")
                continue
            raise
        if not _is_within_range(event_start, start_at, end_at):
            continue

        body = ""
        if include_body:
            try:
                body = _safe_str(getattr(event, "Body", ""))[:CALENDAR_BODY_PREVIEW_LIMIT]
            except Exception:
                body = ""
        try:
            entry_id = _safe_str(getattr(event, "EntryID", ""))
        except Exception:
            entry_id = ""
        try:
            subject = _safe_str(getattr(event, "Subject", ""))
            location = _safe_str(getattr(event, "Location", ""))
        except Exception as exc:
            _log_progress(f"step=item_skip progress={checked_count}: {exc}")
            continue
        events.append(
            {
                "entry_id": entry_id,
                "subject": subject,
                "start": _iso_com_datetime(event_start),
                "end": _iso_com_datetime(event_end),
                "location": location,
                "calendar_owner": calendar_owner,
                "own_calendar": bool(own_calendar),
                "organizer": _read_guarded_property(event, PR_SENT_REPRESENTING_NAME_W),
                "required_attendees": _read_guarded_property(event, PR_DISPLAY_TO_W),
                "optional_attendees": _read_guarded_property(event, PR_DISPLAY_CC_W),
                "body_preview": body,
            }
        )
        if len(events) >= max_results:
            break
    return events, checked_count


def _collect_mail_messages(
    messages: Any,
    *,
    folder_name: str,
    date_attr: str,
    direction: str,
    query: str | None,
    start_at: datetime,
    end_at: datetime,
    max_results: int,
    max_scan_items: int,
) -> tuple[list[dict], int]:
    """Собрать письма Outlook из папки в указанном диапазоне."""
    results = []
    scanned_count = 0
    _log_progress(f"step=iterate_items start folder={folder_name}")
    for message in messages:
        scanned_count += 1
        if scanned_count > max_scan_items or len(results) >= max_results:
            break

        subject = _decode_mime_header(getattr(message, "Subject", ""))
        body = _safe_str(getattr(message, "Body", ""))
        message_time = getattr(message, date_attr, None)
        if not _is_within_range(message_time, start_at, end_at):
            continue
        if not _matches_query(subject, body, query):
            continue

        sender = _decode_mime_header(_read_guarded_property(message, PR_SENDER_NAME_W))
        recipients = _decode_mime_header(_read_guarded_property(message, PR_DISPLAY_TO_W))
        sent_representing = _decode_mime_header(
            _read_guarded_property(message, PR_SENT_REPRESENTING_NAME_W)
        )
        # Same as calendar: keep Outlook wall-clock, do not leak a fake +00:00.
        timestamp = _iso_com_datetime(message_time)
        item = {
            "entry_id": _safe_str(getattr(message, "EntryID", "")),
            "subject": subject,
            "sender": sender or sent_representing,
            "sender_email": _read_sender_smtp(message),
            "to": recipients,
            "received_at": timestamp if direction == "inbox" else "",
            "sent_at": timestamp if direction == "sent" else "",
            "datetime": timestamp,
            "direction": direction,
            "folder": folder_name,
            "body_preview": body[:BODY_PREVIEW_LIMIT],
            "unread": bool(getattr(message, "UnRead", False)),
            "attachments": _mail_attachment_names(message),
            "datetime_sort": _datetime_sort_key(message_time),
        }
        results.append(item)
    return results, scanned_count


def _mail_attachment_names(message: Any) -> list[dict[str, str]]:
    """Имена вложений письма без встроенных картинок подписи."""
    names: list[dict[str, str]] = []
    try:
        attachments = getattr(message, "Attachments", None)
        count = int(getattr(attachments, "Count", 0) or 0)
    except Exception:
        return names
    for index in range(1, count + 1):
        try:
            item = attachments.Item(index)
            name = _safe_str(getattr(item, "FileName", ""))
            att_type = int(getattr(item, "Type", 1) or 1)
            if not name or att_type != 1:
                continue
            if re.match(r"image\d+\.(png|jpe?g|gif|bmp)$", name, re.I):
                continue
            names.append({"name": name})
        except Exception:
            continue
    return names


def _resolve_mail_item(namespace: Any, entry_id: str) -> Any:
    """Найти письмо Outlook по EntryID и дать понятную ошибку, если оно недоступно."""
    if not entry_id:
        raise OutlookComError("ENTRY_ID_REQUIRED: нужен entry_id письма")
    try:
        item = namespace.GetItemFromID(entry_id)
    except Exception as exc:
        raise OutlookAccessError(f"Не удалось открыть письмо по entry_id: {exc}") from exc
    if item is None:
        raise OutlookAccessError("Письмо по entry_id не найдено")
    return item


def _mail_detail_payload(message: Any, *, include_body: bool = True) -> dict[str, Any]:
    """Собрать безопасный payload письма для UI."""
    body = _safe_str(getattr(message, "Body", ""))
    sender = _decode_mime_header(_read_guarded_property(message, PR_SENDER_NAME_W))
    sent_by = _decode_mime_header(_read_guarded_property(message, PR_SENT_REPRESENTING_NAME_W))
    unread = bool(getattr(message, "UnRead", False))
    attachments = []
    try:
        raw_attachments = getattr(message, "Attachments", None)
        count = int(getattr(raw_attachments, "Count", 0) or 0)
    except Exception:
        count = 0
        raw_attachments = None
    for index in range(1, count + 1):
        try:
            att = raw_attachments.Item(index)
            file_name = _safe_str(getattr(att, "FileName", ""))
            if not file_name or re.match(r"image\d+\.(png|jpe?g|gif|bmp)$", file_name, re.I):
                continue
            attachments.append(
                {
                    "index": index,
                    "file_name": file_name,
                    "display_name": file_name,
                    "size": int(getattr(att, "Size", 0) or 0) or None,
                }
            )
        except Exception:
            continue
    return {
        "entry_id": _safe_str(getattr(message, "EntryID", "")),
        "subject": _decode_mime_header(getattr(message, "Subject", "")),
        "sender": sender or sent_by,
        "sender_email": _read_sender_smtp(message),
        "body": body if include_body else "",
        "body_preview": body[:BODY_PREVIEW_LIMIT],
        "unread": unread,
        "attachments": attachments,
    }


def fetch_mail_message(input_data: dict) -> dict:
    """Прочитать письмо Outlook по EntryID."""
    def _read(win32com_client: Any) -> dict:
        outlook = _dispatch_outlook(win32com_client)
        namespace = _mapi_namespace(outlook)
        entry_id = _safe_str(input_data.get("entry_id") or "").strip()
        message = _resolve_mail_item(namespace, entry_id)
        payload = _mail_detail_payload(message, include_body=True)
        payload["source"] = "outlook_com"
        return payload

    return _run_com_read(_read, "Ошибка чтения письма Outlook")


def mark_mail_read(input_data: dict) -> dict:
    """Изменить статус прочтения письма Outlook."""
    unread = bool(input_data.get("unread"))

    def _write(win32com_client: Any) -> dict:
        outlook = _dispatch_outlook(win32com_client)
        namespace = _mapi_namespace(outlook)
        entry_id = _safe_str(input_data.get("entry_id") or "").strip()
        message = _resolve_mail_item(namespace, entry_id)
        try:
            message.UnRead = unread
            message.Save()
        except Exception as exc:
            raise OutlookAccessError(f"Не удалось изменить статус письма: {exc}") from exc
        return {
            "ok": True,
            "entry_id": entry_id,
            "unread": unread,
            "source": "outlook_com",
        }

    return _run_com_read(_write, "Ошибка изменения статуса письма Outlook")


def _focus_outlook_window(caption: str) -> bool:
    """Вытащить окно классического Outlook поверх Оркестратора.

    Sidecar — фоновый процесс, поэтому обычный SetForegroundWindow Windows глушит.
    Цепляемся к потоку текущего переднего окна и только потом активируем Outlook.
    """
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_bool
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
    user32.AttachThreadInput.restype = ctypes.c_bool

    found: list[int] = []
    hint = (caption or "").strip().casefold()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if not str(class_name.value).startswith("rctrl_renwnd32"):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd))
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = str(title_buf.value or "")
        if hint and hint.casefold() in title.casefold():
            found.insert(0, hwnd)
        else:
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        _log_progress("step=focus_outlook no window")
        return False
    hwnd = found[0]
    user32.ShowWindow(hwnd, 9)
    foreground = user32.GetForegroundWindow()
    pid = ctypes.c_ulong()
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid)) or 0)
    this_thread = int(kernel32.GetCurrentThreadId())
    attached = False
    if foreground_thread and foreground_thread != this_thread:
        attached = bool(user32.AttachThreadInput(this_thread, foreground_thread, True))
    user32.BringWindowToTop(hwnd)
    brought = bool(user32.SetForegroundWindow(hwnd))
    if attached:
        user32.AttachThreadInput(this_thread, foreground_thread, False)
    _log_progress(f"step=focus_outlook brought={brought}")
    return brought


def _present_outlook_item(item: Any, *, title_hint: str = "") -> None:
    """Показать письмо или черновик и переключить фокус на Outlook."""
    item.Display(False)
    inspector = None
    try:
        inspector = item.GetInspector
        inspector.Activate()
    except Exception as exc:  # noqa: BLE001
        _log_progress("step=inspector_activate " + repr(exc))
    caption = title_hint
    if inspector is not None:
        try:
            caption = _safe_str(getattr(inspector, "Caption", "")) or title_hint
        except Exception:  # noqa: BLE001
            caption = title_hint
    try:
        import pythoncom

        pythoncom.PumpWaitingMessages()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.15)
    _focus_outlook_window(caption)


def display_mail_message(input_data: dict) -> dict:
    """Открыть письмо или черновик ответа в Outlook.

    mode=forward, to=адрес, send=true — переслать и отправить без окна.
    """
    mode = _safe_str(input_data.get("mode") or "open").strip().casefold()
    send = bool(input_data.get("send"))
    to_addr = _safe_str(input_data.get("to") or "").strip()

    def _write(win32com_client: Any) -> dict:
        outlook = _dispatch_outlook(win32com_client)
        namespace = _mapi_namespace(outlook)
        entry_id = _safe_str(input_data.get("entry_id") or "").strip()
        message = _resolve_mail_item(namespace, entry_id)
        if mode == "reply":
            draft = message.Reply()
        elif mode == "reply_all":
            draft = message.ReplyAll()
        elif mode == "forward":
            draft = message.Forward()
        else:
            _present_outlook_item(message, title_hint=_safe_str(getattr(message, "Subject", "")))
            return {"ok": True, "entry_id": entry_id, "mode": "open", "source": "outlook_com"}
        if to_addr:
            try:
                draft.To = to_addr
            except Exception as exc:
                raise OutlookAccessError(f"Не удалось указать получателя: {exc}") from exc
        if send:
            if not to_addr:
                raise OutlookAccessError("Для отправки укажите получателя")
            try:
                draft.Send()
            except Exception as exc:
                raise OutlookAccessError(f"Не удалось отправить письмо: {exc}") from exc
            return {
                "ok": True,
                "entry_id": entry_id,
                "mode": mode,
                "sent": True,
                "to": to_addr,
                "source": "outlook_com",
            }
        _present_outlook_item(draft, title_hint=_safe_str(getattr(draft, "Subject", "")))
        return {
            "ok": True,
            "entry_id": entry_id,
            "mode": mode,
            "source": "outlook_com",
        }

    return _run_com_read(_write, "Ошибка открытия письма Outlook")


OL_SAVEAS_MSG = 3


def _safe_mail_file_stem(subject: str, entry_id: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (subject or "").strip())[:80]
    if not stem:
        stem = "message"
    suffix = (entry_id or "")[:8].replace("{", "").replace("}", "")
    return f"{stem}-{suffix}" if suffix else stem


def save_mail_message(input_data: dict) -> dict:
    """Сохранить письмо Outlook как .msg для прикрепления в 1С."""
    save_dir = _safe_str(input_data.get("save_dir") or "").strip()

    def _write(win32com_client: Any) -> dict:
        outlook = _dispatch_outlook(win32com_client)
        namespace = _mapi_namespace(outlook)
        entry_id = _safe_str(input_data.get("entry_id") or "").strip()
        message = _resolve_mail_item(namespace, entry_id)
        subject = _decode_mime_header(getattr(message, "Subject", ""))
        base_dir = Path(save_dir) if save_dir else Path(tempfile.gettempdir()) / "Constructor" / "outlook" / "messages"
        base_dir.mkdir(parents=True, exist_ok=True)
        target = base_dir / f"{_safe_mail_file_stem(subject, entry_id)}.msg"
        try:
            message.SaveAs(str(target.resolve()), OL_SAVEAS_MSG)
        except Exception as exc:
            raise OutlookAccessError(f"Не удалось сохранить письмо как .msg: {exc}") from exc
        out = {
            "ok": True,
            "entry_id": entry_id,
            "saved_path": str(target),
            "file_name": target.name,
            "subject": subject,
            "source": "outlook_com",
        }
        if _truthy(input_data.get("stage_for_incoming")):
            from app.tools.ac.workers.mail_incoming_onec import stage_incoming_msg_file

            staged = stage_incoming_msg_file(
                str(target),
                entry_id=entry_id,
                file_name=target.name,
            )
            out["staged_path"] = str(staged)
            try:
                raw = staged.read_bytes()
                if len(raw) <= 12 * 1024 * 1024:
                    import base64

                    out["msg_base64"] = base64.b64encode(raw).decode("ascii")
                    out["msg_filename"] = staged.name
            except OSError:
                pass
        return out

    return _run_com_read(_write, "Ошибка сохранения письма Outlook")


def save_mail_attachment(input_data: dict) -> dict:
    """Сохранить вложение письма Outlook на диск."""
    attachment_index = _clamp_int(
        input_data.get("attachment_index") or input_data.get("index"),
        1,
        1,
        100,
    )
    save_dir = _safe_str(input_data.get("save_dir") or "").strip()

    def _write(win32com_client: Any) -> dict:
        outlook = _dispatch_outlook(win32com_client)
        namespace = _mapi_namespace(outlook)
        entry_id = _safe_str(input_data.get("entry_id") or "").strip()
        message = _resolve_mail_item(namespace, entry_id)
        attachments = getattr(message, "Attachments", None)
        if attachments is None:
            raise OutlookAccessError("У письма нет вложений")
        try:
            attachment = attachments.Item(attachment_index)
        except Exception as exc:
            raise OutlookAccessError(f"Вложение #{attachment_index} не найдено: {exc}") from exc
        file_name = _safe_str(getattr(attachment, "FileName", "")).strip() or f"attachment-{attachment_index}"
        base_dir = Path(save_dir) if save_dir else Path(tempfile.gettempdir()) / "Constructor" / "outlook"
        base_dir.mkdir(parents=True, exist_ok=True)
        target = base_dir / file_name
        try:
            attachment.SaveAsFile(str(target))
        except Exception as exc:
            raise OutlookAccessError(f"Не удалось сохранить вложение: {exc}") from exc
        return {
            "ok": True,
            "entry_id": entry_id,
            "attachment_index": attachment_index,
            "saved_path": str(target),
            "file_name": file_name,
            "source": "outlook_com",
        }

    return _run_com_read(_write, "Ошибка сохранения вложения Outlook")


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Привести числовой параметр к безопасному диапазону."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    return max(minimum, min(maximum, parsed_value))


def _is_older_than_cutoff(received_time: Any, cutoff: datetime) -> bool:
    """Проверить дату письма, не падая на нестандартных COM-типах времени."""
    if received_time is None:
        return False

    try:
        if hasattr(received_time, "replace"):
            comparable_time = received_time.replace(tzinfo=None)
        else:
            comparable_time = received_time
        return comparable_time < cutoff
    except Exception:
        return False


def _is_within_range(value: Any, start_at: datetime, end_at: datetime) -> bool:
    """Проверить, что COM-дата попадает в безопасный диапазон чтения."""
    if value is None:
        return False
    try:
        if hasattr(value, "replace"):
            comparable_value = value.replace(tzinfo=None)
        else:
            comparable_value = value
        return start_at <= comparable_value <= end_at
    except Exception:
        return False


def _datetime_sort_key(value: Any) -> str:
    """Вернуть ISO-ключ сортировки COM datetime."""
    if value is None:
        return ""
    try:
        comparable_value = value.replace(tzinfo=None) if hasattr(value, "replace") else value
        if hasattr(comparable_value, "isoformat"):
            return comparable_value.isoformat()
        return str(comparable_value)
    except Exception:
        return ""


# Jet/Outlook Restrict is locale-sensitive. US `08/31/2026` is invalid on a
# Russian profile (there is no 31st month) and often returns an empty set
# without raising — so we try RU formats first, then US.
_RESTRICT_DATE_FORMATS = (
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%Y-%m-%d %H:%M",
)


def restrict_filter_strings(start_at: datetime, end_at: datetime) -> list[str]:
    """Date filters for Outlook Restrict, RU locale first."""
    seen: set[str] = set()
    out: list[str] = []
    for fmt in _RESTRICT_DATE_FORMATS:
        restriction = (
            "[Start] >= '"
            + start_at.strftime(fmt)
            + "' AND [Start] <= '"
            + end_at.strftime(fmt)
            + "'"
        )
        if restriction in seen:
            continue
        seen.add(restriction)
        out.append(restriction)
    return out


def _iter_restricted_calendar_items(
    items: Any, start_at: datetime, end_at: datetime
):
    """Yield (filter, restricted items) for each locale that Outlook accepts."""
    for restriction in restrict_filter_strings(start_at, end_at):
        try:
            yield restriction, items.Restrict(restriction)
        except Exception:
            continue


def _restrict_calendar_items(
    items: Any, start_at: datetime, end_at: datetime
) -> tuple[Any, bool]:
    """Ограничить календарь через Restrict. False = Restrict не сработал."""
    for _restriction, restricted in _iter_restricted_calendar_items(items, start_at, end_at):
        return restricted, True
    return items, False


def _iso_com_datetime(value: Any) -> str:
    """Normalize a COM/Outlook datetime to an ISO string the UI can parse."""
    if value is None:
        return ""
    try:
        comparable = value.replace(tzinfo=None) if hasattr(value, "replace") else value
        if hasattr(comparable, "isoformat"):
            return comparable.isoformat(sep="T", timespec="seconds")
    except Exception:
        pass
    text = _safe_str(value).strip()
    if not text:
        return ""
    return text.replace(" ", "T", 1)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)

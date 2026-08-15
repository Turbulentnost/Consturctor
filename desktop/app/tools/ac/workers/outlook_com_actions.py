"""Низкоуровневые безопасные действия Outlook через COM."""

from __future__ import annotations

import importlib
import re
import sys
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
DEFAULT_DAYS_FORWARD = 7
DEFAULT_MAX_RESULTS = 50
DEFAULT_CALENDAR_MAX_RESULTS = 20
MAX_DAYS = 365
MAX_RESULTS = 50

# Транзиентные COM/RPC HRESULT-ы: Outlook занят или сервер ещё поднимается.
# При них имеет смысл короткий повтор вместо провала всего запуска.
TRANSIENT_COM_HRESULTS = {
    -2147467259,  # E_FAIL — "Неопознанная ошибка"
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
OUTLOOK_NOT_REGISTERED_MESSAGE = (
    "Классический Outlook не найден или COM-автоматизация не зарегистрирована на "
    "этом компьютере. Установите классический Microsoft Outlook (desktop) и хотя бы "
    "раз запустите его с настроенным профилем. «Новый Outlook» и веб-версия COM не "
    "поддерживают."
)
DEFAULT_MAIL_MAX_SCAN_ITEMS = 200
DEFAULT_CALENDAR_MAX_SCAN_ITEMS = 1000
MAX_SCAN_ITEMS = 2000
BODY_PREVIEW_LIMIT = 500
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


def _log_progress(message: str) -> None:
    """Записать COM progress-сообщение в stderr, не загрязняя stdout JSON."""
    print(f"[COM_DIAG] {message}", file=sys.stderr, flush=True)


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
    if args and isinstance(args[0], int):
        return args[0] in TRANSIENT_COM_HRESULTS
    return False


def _is_class_not_registered_error(exc: Exception) -> bool:
    """Определить, что COM-класс Outlook не зарегистрирован (нет classic Outlook)."""
    args = getattr(exc, "args", None)
    if args and isinstance(args[0], int) and args[0] in CLASS_NOT_REGISTERED_HRESULTS:
        return True
    text = str(exc).casefold()
    return "80040154" in text or "class not registered" in text or (
        "недопустимая строка класса" in text
    )


def _run_com_read(operation: Callable[[Any], dict], access_error_prefix: str) -> dict:
    """Выполнить read-only COM-операцию с CoInitialize и повтором транзиентных ошибок.

    ``operation`` получает модуль ``win32com.client`` и возвращает готовый payload.
    ComUnavailableError из загрузки pywin32 пробрасывается как есть (нужно тестам).
    """
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
            raise OutlookAccessError(f"{access_error_prefix}: {exc}") from exc
        finally:
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
    raise OutlookAccessError(f"{access_error_prefix}: {last_exc}")


def _safe_str(value: Any) -> str:
    """Безопасно привести COM-значение к строке."""
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


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
        outlook = win32com_client.Dispatch("Outlook.Application")
        _log_progress("step=dispatch_outlook ok")
        _log_progress("step=get_namespace start")
        namespace = outlook.GetNamespace("MAPI")
        _log_progress("step=get_namespace ok")

        results = []
        scanned_count = 0
        for folder_name, folder_id, sort_field, date_attr, direction in folder_specs:
            _log_progress(f"step=get_mail_folder start folder={folder_name}")
            folder_obj = namespace.GetDefaultFolder(folder_id)
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
        return {
            "messages": results,
            "count": len(results),
            "scanned_count": scanned_count,
            "source": "outlook_com",
            "folder": _safe_str(input_data.get("folder") or DEFAULT_FOLDER),
            "folders": [item[0] for item in folder_specs],
            "range_start": start_at.isoformat(),
            "range_end": end_at.isoformat(),
        }

    return _run_com_read(_read, "Ошибка доступа к Outlook или MAPI")


def read_calendar(input_data: dict) -> dict:
    """Безопасно прочитать ближайшие события Outlook Calendar без изменений."""
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
        MAX_RESULTS,
    )
    max_scan_items = _clamp_int(
        input_data.get("max_scan_items"),
        DEFAULT_CALENDAR_MAX_SCAN_ITEMS,
        1,
        MAX_SCAN_ITEMS,
    )

    def _read(win32com_client: Any) -> dict:
        _log_progress("step=dispatch_outlook start")
        outlook = win32com_client.Dispatch("Outlook.Application")
        _log_progress("step=dispatch_outlook ok")
        _log_progress("step=get_namespace start")
        namespace = outlook.GetNamespace("MAPI")
        _log_progress("step=get_namespace ok")
        _log_progress("step=get_calendar start")
        calendar = namespace.GetDefaultFolder(CALENDAR_FOLDER_ID)
        _log_progress("step=get_calendar ok")
        _log_progress("step=get_items start")
        items = calendar.Items
        _log_progress("step=get_items ok")
        _log_progress("step=include_recurrences start")
        items.IncludeRecurrences = True
        _log_progress("step=include_recurrences ok")
        _log_progress("step=sort_items start")
        items.Sort("[Start]")
        _log_progress("step=sort_items ok")

        start_at, end_at = _resolve_date_range(
            input_data,
            default_days=days_forward,
            forward=True,
        )
        restricted_items = _restrict_calendar_items(items, start_at, end_at)

        _log_progress("step=iterate_items start")
        events, checked_count = _collect_calendar_events(
            restricted_items,
            start_at,
            end_at,
            max_results,
            max_scan_items,
        )
        if not events:
            _log_progress("step=iterate_items fallback_raw_items start")
            events, checked_count = _collect_calendar_events(
                items,
                start_at,
                end_at,
                max_results,
                max(MAX_SCAN_ITEMS, max_scan_items),
            )

        _log_progress("step=done ok")
        return {
            "events": events,
            "count": len(events),
            "scanned_count": checked_count,
            "source": "outlook_com",
            "folder": CALENDAR_FOLDER,
            "range_start": start_at.isoformat(),
            "range_end": end_at.isoformat(),
        }

    return _run_com_read(_read, "Ошибка доступа к Outlook Calendar")


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


def _collect_calendar_events(
    items: Any,
    start_at: datetime,
    end_at: datetime,
    max_results: int,
    max_scan_items: int,
) -> tuple[list[dict], int]:
    """Собрать события календаря из COM collection в указанном диапазоне."""
    events = []
    checked_count = 0
    for event in items:
        checked_count += 1
        if checked_count > max_scan_items:
            break

        event_start = getattr(event, "Start", None)
        event_end = getattr(event, "End", None)
        if not _is_within_range(event_start, start_at, end_at):
            continue

        body = _safe_str(getattr(event, "Body", ""))
        events.append(
            {
                "entry_id": _safe_str(getattr(event, "EntryID", "")),
                "subject": _safe_str(getattr(event, "Subject", "")),
                "start": _safe_str(event_start),
                "end": _safe_str(event_end),
                "location": _safe_str(getattr(event, "Location", "")),
                "organizer": _read_guarded_property(event, PR_SENT_REPRESENTING_NAME_W),
                "required_attendees": _read_guarded_property(event, PR_DISPLAY_TO_W),
                "optional_attendees": _read_guarded_property(event, PR_DISPLAY_CC_W),
                "body_preview": body[:CALENDAR_BODY_PREVIEW_LIMIT],
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

        subject = _safe_str(getattr(message, "Subject", ""))
        body = _safe_str(getattr(message, "Body", ""))
        message_time = getattr(message, date_attr, None)
        if not _is_within_range(message_time, start_at, end_at):
            continue
        if not _matches_query(subject, body, query):
            continue

        sender = _read_guarded_property(message, PR_SENDER_NAME_W)
        recipients = _read_guarded_property(message, PR_DISPLAY_TO_W)
        sent_representing = _read_guarded_property(message, PR_SENT_REPRESENTING_NAME_W)
        timestamp = _safe_str(message_time)
        item = {
            "entry_id": _safe_str(getattr(message, "EntryID", "")),
            "subject": subject,
            "sender": sender or sent_representing,
            "to": recipients,
            "received_at": timestamp if direction == "inbox" else "",
            "sent_at": timestamp if direction == "sent" else "",
            "datetime": timestamp,
            "direction": direction,
            "folder": folder_name,
            "body_preview": body[:BODY_PREVIEW_LIMIT],
            "datetime_sort": _datetime_sort_key(message_time),
        }
        results.append(item)
    return results, scanned_count


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


def _restrict_calendar_items(items: Any, start_at: datetime, end_at: datetime) -> Any:
    """Безопасно ограничить календарные элементы через Restrict или fallback."""
    restriction = (
        "[Start] >= '"
        + start_at.strftime("%m/%d/%Y %I:%M %p")
        + "' AND [Start] <= '"
        + end_at.strftime("%m/%d/%Y %I:%M %p")
        + "'"
    )
    try:
        return items.Restrict(restriction)
    except Exception:
        return items

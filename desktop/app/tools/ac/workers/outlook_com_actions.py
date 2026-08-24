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
    if args and isinstance(args[0], int) and args[0] in TRANSIENT_COM_HRESULTS:
        return True
    nested = args[2] if args and len(args) > 2 and isinstance(args[2], tuple) else ()
    if nested and isinstance(nested[-1], int) and nested[-1] in TRANSIENT_COM_HRESULTS:
        return True
    text = str(exc).casefold()
    return "не выполнено" in text or "rpc_e_servercall_retrylater" in text


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
            raise OutlookAccessError(
                f"{access_error_prefix}: {exc}. "
                "Классический Outlook должен быть открыт, календарь — свой (не только чтение). "
                "Файл → Параметры → центр управления безопасностью → программный доступ: "
                "не блокировать автоматизацию."
            ) from exc
        finally:
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
    raise OutlookAccessError(
        f"{access_error_prefix}: {last_exc}. "
        "Классический Outlook должен быть открыт, календарь — свой (не только чтение). "
        "Файл → Параметры → центр управления безопасностью → программный доступ: "
        "не блокировать автоматизацию."
    )


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
        MAX_CALENDAR_RESULTS,
    )
    max_scan_items = _clamp_int(
        input_data.get("max_scan_items"),
        DEFAULT_CALENDAR_MAX_SCAN_ITEMS,
        1,
        MAX_SCAN_ITEMS,
    )
    include_body = _truthy(input_data.get("include_body"))

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
        events, checked_count = _collect_calendar_range(
            items,
            start_at,
            end_at,
            max_results=max_results,
            max_scan_items=max_scan_items,
            include_body=include_body,
        )

        _log_progress("step=done ok")
        return {
            "events": events,
            "count": len(events),
            "free_slots": _compute_free_slots(events, start_at, end_at),
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
    """Создать одну или несколько встреч в календаре Outlook. Письма не отправляет."""
    items = _meeting_specs(input_data)
    if not items:
        raise OutlookComError("Нужны subject и start или массив events")

    def _write(win32com_client: Any) -> dict:
        _log_progress("step=dispatch_outlook start")
        outlook = _dispatch_outlook(win32com_client)
        _log_progress("step=dispatch_outlook ok")
        created: list[dict] = []
        for spec in items:
            appt = _new_appointment(outlook)
            appt.Subject = spec["subject"]
            _set_appointment_times(appt, spec["start"], spec["end"])
            try:
                appt.ReminderSet = False
            except Exception:
                pass
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
            created.append(
                {
                    "entry_id": entry_id,
                    "subject": spec["subject"],
                    "start": spec["start"].isoformat(timespec="minutes"),
                    "end": spec["end"].isoformat(timespec="minutes"),
                    "location": spec["location"],
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
    """Взять уже открытый Outlook, иначе создать COM-сессию."""
    _log_progress("step=dispatch_outlook start")
    try:
        return win32com_client.GetActiveObject("Outlook.Application")
    except Exception:
        return win32com_client.Dispatch("Outlook.Application")


def _verify_saved_appointment(outlook: Any, appt: Any) -> str:
    """Save без ошибки ещё не значит, что встреча в календаре. Перечитываем."""
    entry_id = _safe_str(getattr(appt, "EntryID", ""))
    if not entry_id:
        raise OutlookAccessError(
            "Ошибка записи встречи: Outlook не вернул идентификатор после Save. "
            "Встреча в календарь не попала. Нужен классический Outlook и свой календарь для записи."
        )
    try:
        namespace = outlook.GetNamespace("MAPI")
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


def _new_appointment(outlook: Any) -> Any:
    """Создать встречу в календаре профиля, не «висящий» CreateItem."""
    try:
        namespace = outlook.GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(CALENDAR_FOLDER_ID)
        try:
            return calendar.Items.Add()
        except Exception:
            return calendar.Items.Add(1)
    except Exception:
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
        specs.append(
            {
                "subject": subject,
                "body": body,
                "start": start,
                "end": end,
                "location": _safe_str(row.get("location") or "").strip(),
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
        item = getter()
        while item is not None:
            yield item
            item = nxt()
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
        window_items, restricted = _restrict_calendar_items(items, win_start, win_end)
        if not restricted:
            _log_progress("step=restrict_window fallback_getfirst")
            chunk, scanned = _collect_calendar_events(
                items,
                start_at,
                end_at,
                remaining_results,
                remaining_scan,
                include_body=include_body,
            )
            return chunk, scanned
        chunk, scanned = _collect_calendar_events(
            window_items,
            start_at,
            end_at,
            remaining_results,
            remaining_scan,
            include_body=include_body,
        )
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

        event_start = getattr(event, "Start", None)
        event_end = getattr(event, "End", None)
        if not _is_within_range(event_start, start_at, end_at):
            continue

        body = ""
        if include_body:
            body = _safe_str(getattr(event, "Body", ""))[:CALENDAR_BODY_PREVIEW_LIMIT]
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


def _restrict_calendar_items(
    items: Any, start_at: datetime, end_at: datetime
) -> tuple[Any, bool]:
    """Ограничить календарь через Restrict. False = Restrict не сработал."""
    restriction = (
        "[Start] >= '"
        + start_at.strftime("%m/%d/%Y %I:%M %p")
        + "' AND [Start] <= '"
        + end_at.strftime("%m/%d/%Y %I:%M %p")
        + "'"
    )
    try:
        return items.Restrict(restriction), True
    except Exception:
        return items, False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)

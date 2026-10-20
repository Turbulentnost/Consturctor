"""Переменные окружения инструментов: значения из .env Constructor, правки — в backend/.env.

Значение переменной берётся по цепочке:
1. backend/.env TurboTester (то, что пользователь поправил во вкладке «Настройки»);
2. desktop/.env Constructor (CONSTRUCTOR_DESKTOP_DIR), затем backend/.env рядом с ним —
   под тем же именем или под именем Constructor (aliases);
3. значение по умолчанию реализации (здесь только для подсказки, в окружение не пишется).

apply() кладёт итог в os.environ и обновляет объекты настроек, которые инструменты уже
прочитали при импорте: app.config.settings и settings AIAgentBack. Процессы конфигураций
(раннер, MCP-сервер) наследуют os.environ при следующем запуске.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

from app.config import BACKEND_ROOT, Settings, settings
from app.vendors.constructor.envfile import read_env_text

logger = logging.getLogger(__name__)

LOCAL_ENV = BACKEND_ROOT / ".env"


@dataclass(frozen=True)
class EnvField:
    key: str
    label: str
    hint: str = ""
    secret: bool = False
    # Имена той же переменной в .env Constructor, если они отличаются.
    aliases: tuple[str, ...] = ()
    default: str = ""


@dataclass(frozen=True)
class EnvGroup:
    id: str
    title: str
    summary: str
    fields: tuple[EnvField, ...]


GROUPS: tuple[EnvGroup, ...] = (
    EnvGroup(
        "constructor",
        "Сервер Constructor",
        "Серверные инструменты (users.*, 1С через сервер, IMAP, TurboProject) выполняются на нём "
        "под пользователем агентов.",
        (
            EnvField(
                "CONSTRUCTOR_API_URL",
                "Адрес сервера",
                # BACKEND_URL из desktop/.env Constructor не берём: там адрес машины разработчика.
                default="http://192.168.1.157:7812",
            ),
            EnvField(
                "CONSTRUCTOR_API_TOKEN",
                "Готовый JWT",
                "Если задан, вход по логину и паролю не нужен",
                secret=True,
            ),
            EnvField(
                "CONSTRUCTOR_DESKTOP_DIR",
                "Папка desktop Constructor",
                "Из неё MCP-серверы конфигураций берут инструменты, рядом лежат .env Constructor",
            ),
            EnvField(
                "TOOLS_WORKSPACES_ROOT",
                "Рабочие папки агентов",
                "Пусто — %LOCALAPPDATA%\\TurboTest\\agent_workspaces",
            ),
        ),
    ),
    EnvGroup(
        "cursor",
        "Cursor",
        "Ключ Cursor SDK для конфигураций платформы.",
        (EnvField("CURSOR_API_KEY", "API-ключ", secret=True),),
    ),
    EnvGroup(
        "outlook",
        "Exchange и Outlook",
        "Встречи, переговорные, поиск слотов и письма через EWS и SMTP.",
        (
            EnvField("OUTLOOK_EMAIL", "Учётная запись (e-mail)"),
            EnvField("OUTLOOK_PASSWORD", "Пароль", secret=True),
            EnvField("OUTLOOK_SERVER", "Сервер EWS", "Пусто — автообнаружение"),
            EnvField("OUTLOOK_MAILBOX", "Ящик", "Если календарь в другом (общем) ящике"),
            EnvField("OUTLOOK_WEB_APP_URL", "Адрес Outlook Web App"),
            EnvField(
                "OUTLOOK_COMPANY_CALENDAR", "Общий календарь", default="calendar@turbo-don.ru"
            ),
            EnvField("OUTLOOK_TIMEZONE", "Часовой пояс", default="Europe/Moscow"),
            EnvField("OUTLOOK_SMTP_HOST", "SMTP-сервер"),
            EnvField("OUTLOOK_SMTP_PORT", "SMTP-порт", default="587"),
            EnvField("OUTLOOK_SMTP_TLS", "SMTP TLS", "true или false", default="true"),
            EnvField("OUTLOOK_SMTP_FROM", "Отправитель SMTP", "Пусто — учётная запись"),
        ),
    ),
    EnvGroup(
        "onec_odata",
        "1С: OData",
        "Совещания, служебные записки, протоколы и чтение данных ERP.",
        (
            EnvField("ONEC_ODATA_URL", "Адрес OData", aliases=("ODATA_BASE_URL",)),
            EnvField("ONEC_ODATA_USER", "Пользователь", aliases=("ODATA_USERNAME", "ODATA_USER")),
            EnvField("ONEC_ODATA_PASSWORD", "Пароль", secret=True, aliases=("ODATA_PASSWORD",)),
            EnvField("ONEC_ODATA_TIMEOUT", "Таймаут, с", default="120"),
        ),
    ),
    EnvGroup(
        "onec_com",
        "1С: COM на этом компьютере",
        "Карточки документов и задач, открытие форм 1С. Пустой логин — пользователь агентов.",
        (
            EnvField("ONEC_COM_SERVER", "Сервер 1С"),
            EnvField("ONEC_COM_REF", "База", default="erp_pm"),
            EnvField("ONEC_COM_PROGID", "COM-коннектор", default="V83.COMConnector"),
            EnvField(
                "ONEC_COM_CONNECTION_STRING",
                "Строка подключения",
                "Вместо сервера и базы, если нужна особая",
            ),
            EnvField("ERP_LOGIN", "Логин 1С (ФИО)"),
            EnvField("ERP_PASSWORD", "Пароль 1С", secret=True),
        ),
    ),
    EnvGroup(
        "onec_notify",
        "1С: уведомления и адреса",
        "Уведомления 1С о встречах и подбор корпоративных адресов.",
        (
            EnvField("ONEC_CORPORATE_EMAIL_DOMAIN", "Почтовый домен", default="turbo-don.ru"),
            EnvField("ONEC_NOTIFICATION_SOURCE_USER_FIO", "От чьего имени уведомления"),
            EnvField(
                "ONEC_NOTIFICATION_DEFAULT_RECIPIENT_FIOS",
                "Получатели по умолчанию",
                "ФИО через запятую",
            ),
            EnvField("ONEC_MEETING_MEMO_THEME", "Тема служебной записки о совещании"),
        ),
    ),
    EnvGroup(
        "docflow",
        "1С: Документооборот (HTTP)",
        "Задачи и исполнения документов через HTTP-сервис Документооборота.",
        (
            EnvField("DOK_HTTP_SERVER", "Сервер"),
            EnvField("DOK_HTTP_PORT", "Порт", default="81"),
            EnvField("DOK_HTTP_USER", "Пользователь"),
            EnvField("DOK_HTTP_PASSWORD", "Пароль", secret=True),
            EnvField("DOK_HTTP_BASE_PATH", "Публикация", default="/doc"),
            EnvField("DOK_HTTP_SERVICE", "Сервис", default="dterp"),
            EnvField("DOK_HTTP_TEMPLATE", "Шаблон", default="Tasks"),
            EnvField("DOK_HTTP_SUFFIX", "Суффикс"),
            EnvField("DOK_HTTP_TIMEOUT", "Таймаут, с", default="30"),
        ),
    ),
    EnvGroup(
        "files",
        "Сетевые папки",
        "Корни, которые инструмент filesystem может читать.",
        (
            EnvField(
                "FS_ALLOWED_ROOTS",
                "Разрешённые корни",
                "Через запятую, например \\\\host\\share",
                default="\\\\192.168.1.198\\Files",
            ),
        ),
    ),
)

# Пользователь агентов: под ним инструменты входят в Constructor, users.current возвращает его.
USER_FIO = "CONSTRUCTOR_USER_FIO"
USER_PASSWORD = "CONSTRUCTOR_USER_PASSWORD"
USER_FIELDS = (
    EnvField(USER_FIO, "ФИО"),
    EnvField(USER_PASSWORD, "Пароль", secret=True),
)

FIELDS: dict[str, EnvField] = {
    field.key: field for group in GROUPS for field in group.fields
} | {field.key: field for field in USER_FIELDS}

_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
# Оркестратор передаёт пользователя, адрес сервера и папку desktop окружением процесса;
# apply() переписывает os.environ, поэтому исходные значения запоминаются до первого применения.
PROCESS_SOURCE = "Оркестратор"
_PROCESS_ENV: dict[str, str] = {
    key: os.environ[key].strip() for key in FIELDS if os.environ.get(key, "").strip()
}
_lock = threading.RLock()
_applied = False
_applied_stamp: tuple[float, ...] = ()


class SettingsError(ValueError):
    pass


def _read(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = dotenv_values(stream=StringIO(read_env_text(path)))
    except OSError as exc:
        logger.warning("не прочитан %s: %s", path, exc)
        return {}
    return {key: (value or "").strip() for key, value in raw.items() if key}


def constructor_sources(local: dict[str, str] | None = None) -> list[tuple[str, Path]]:
    """Файлы .env Constructor по порядку приоритета: desktop, затем backend."""
    local = _read(LOCAL_ENV) if local is None else local
    raw = (
        local.get("CONSTRUCTOR_DESKTOP_DIR")
        or _PROCESS_ENV.get("CONSTRUCTOR_DESKTOP_DIR")
        or os.environ.get("CONSTRUCTOR_DESKTOP_DIR", "")
    )
    if not raw.strip():
        return []
    desktop = Path(raw.strip())
    return [
        ("Constructor desktop", desktop / ".env"),
        ("Constructor backend", desktop.parent / "backend" / ".env"),
    ]


def _resolve(
    field: EnvField, local: dict[str, str], sources: list[tuple[str, dict[str, str]]]
) -> tuple[str, str]:
    """(значение, источник). Источник пустой, если значение не задано нигде."""
    value = local.get(field.key, "")
    if value:
        return value, "TurboTester"
    value = _PROCESS_ENV.get(field.key, "")
    if value:
        return value, PROCESS_SOURCE
    if field.key in (USER_FIO, USER_PASSWORD):
        return "", ""
    for label, values in sources:
        for name in (field.key, *field.aliases):
            value = values.get(name, "")
            if value:
                return value, label
    return "", ""


def _state() -> tuple[dict[str, str], list[tuple[str, Path, dict[str, str]]]]:
    local = _read(LOCAL_ENV)
    loaded = [(label, path, _read(path)) for label, path in constructor_sources(local)]
    return local, loaded


def effective() -> dict[str, tuple[str, str]]:
    local, loaded = _state()
    sources = [(label, values) for label, _path, values in loaded]
    return {key: _resolve(field, local, sources) for key, field in FIELDS.items()}


def _stamp() -> tuple[float, ...]:
    paths = [LOCAL_ENV, *(path for _label, path in constructor_sources())]
    return tuple(path.stat().st_mtime if path.is_file() else 0.0 for path in paths)


def apply() -> None:
    """Положить значения в os.environ и обновить настройки, прочитанные при импорте."""
    global _applied, _applied_stamp
    with _lock:
        _applied_stamp = _stamp()
        values = effective()
        for key, (value, _source) in values.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        # Прочие строки backend/.env (PLATFORM_*, API_* …) — как раньше, без перезаписи.
        for key, value in _read(LOCAL_ENV).items():
            if key not in FIELDS and value and key not in os.environ:
                os.environ[key] = value
        # 1С COM входит под пользователем агентов, если свой логин 1С не задан.
        if not os.environ.get("ERP_LOGIN"):
            fio = os.environ.get(USER_FIO, "").strip()
            password = os.environ.get(USER_PASSWORD, "")
            if not fio:
                fio = settings.constructor_login_fio.strip()
                password = settings.constructor_login_password
            if fio:
                os.environ["ERP_LOGIN"] = fio
                if password and not os.environ.get("ERP_PASSWORD"):
                    os.environ["ERP_PASSWORD"] = password
        _refresh_settings()
        _reset_caches()
        _applied = True


def ensure_applied() -> None:
    """Применить при первом обращении и после правки .env вручную (по времени изменения файлов)."""
    if not _applied or _stamp() != _applied_stamp:
        apply()


def _refresh_settings() -> None:
    fresh = Settings()
    for key in FIELDS:
        name = key.lower()
        if name in Settings.model_fields:
            setattr(settings, name, getattr(fresh, name))
    module = sys.modules.get("app.vendors.aiagentback.core.config")
    if module is None:
        return
    try:
        vendor = module.Settings()
    except Exception:  # noqa: BLE001
        logger.exception("настройки AIAgentBack не перечитаны")
        return
    for key in FIELDS:
        if key in type(vendor).model_fields:
            setattr(module.settings, key, getattr(vendor, key))


def _reset_caches() -> None:
    from app.tools.constructor_session import reset_session

    reset_session()
    outlook = sys.modules.get("app.vendors.aiagentback.tools.Outlook.send_meeting_invite")
    if outlook is not None:
        outlook.clear_service_account_cache()
    com = sys.modules.get("app.vendors.constructor.tools.ac.workers.com_availability")
    if com is not None:
        com.reset_onec_com_availability_cache()


def _quote(value: str) -> str:
    # Без кавычек python-dotenv не трогает обратные слэши (\\host\share), в кавычках — раскрывает.
    if value == value.strip() and "#" not in value and value[:1] not in ("'", '"'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_local(changes: dict[str, str | None]) -> None:
    """Обновить строки backend/.env: None или пустое значение — убрать строку."""
    lines = read_env_text(LOCAL_ENV).splitlines() if LOCAL_ENV.is_file() else []
    pending = dict(changes)
    out: list[str] = []
    for line in lines:
        match = _KEY_RE.match(line)
        key = match.group(1) if match else ""
        if key not in changes:
            out.append(line)
            continue
        value = pending.pop(key, None)
        if value:
            out.append(f"{key}={_quote(value)}")
    for key, value in pending.items():
        if value:
            out.append(f"{key}={_quote(value)}")
    # Без BOM: pydantic-settings читает backend/.env как utf-8, и BOM испортил бы первый ключ.
    LOCAL_ENV.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def _clean(key: str, value: str) -> str:
    if key not in FIELDS:
        raise SettingsError(f"Неизвестная переменная: {key}")
    if "\n" in value or "\r" in value:
        raise SettingsError(f"{key}: значение должно быть в одну строку")
    return value.strip()


def update(values: dict[str, str], reset: list[str]) -> None:
    """values — новые значения (пустое — убрать свою правку), reset — вернуть к Constructor."""
    changes: dict[str, str | None] = {key: _clean(key, value) for key, value in values.items()}
    for key in reset:
        _clean(key, "")
        changes[key] = None
    if not changes:
        return
    with _lock:
        _write_local(changes)
        apply()
    logger.info("настройки инструментов изменены: %s", ", ".join(sorted(changes)))


def snapshot() -> dict[str, object]:
    """Состояние для вкладки «Настройки». Секреты не отдаются — только признак, что заданы."""
    local, loaded = _state()
    sources = [(label, values) for label, _path, values in loaded]
    groups = []
    for group in GROUPS:
        items = []
        for field in group.fields:
            value, source = _resolve(field, local, sources)
            inherited, inherited_source = _resolve(field, {}, sources)
            items.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "hint": field.hint,
                    "secret": field.secret,
                    "default": field.default,
                    "value": "" if field.secret else value,
                    "is_set": bool(value),
                    "source": source,
                    "overridden": bool(local.get(field.key)),
                    "constructor_value": "" if field.secret else inherited,
                    "constructor_set": bool(inherited),
                    "constructor_source": inherited_source,
                }
            )
        groups.append(
            {"id": group.id, "title": group.title, "summary": group.summary, "fields": items}
        )
    return {
        "env_file": str(LOCAL_ENV),
        "sources": [
            {"label": label, "path": str(path), "found": path.is_file()}
            for label, path, _values in loaded
        ],
        "groups": groups,
    }

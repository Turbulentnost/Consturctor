"""Реестр источников данных для калькуляторов KPI.

Сгенерированный модуль не ходит за данными сам: он объявляет
SOURCE = {"source": "<имя из реестра>", "params": {...}}, а строки
загружает бэкенд. Так модуль одинаково работает на любом компьютере
и для любого сотрудника должности.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.position_kpi.daily import SourceBundle

logger = logging.getLogger(__name__)

Loader = Callable[["SourceBundle", dict[str, Any]], list[dict[str, Any]]]

TEMPLATE_VARS: dict[str, str] = {
    "employee_fio": "ФИО сотрудника, для которого считается KPI",
    "employee_position": "Должность сотрудника",
    "period_from": "Начало периода, ГГГГ-ММ-ДД",
    "period_to": "Конец периода, ГГГГ-ММ-ДД",
    "period_from_dt": "Начало периода для OData, ГГГГ-ММ-ДДT00:00:00",
    "period_to_dt": "Конец периода для OData, ГГГГ-ММ-ДДT23:59:59",
    "as_of": "Дата расчёта, ГГГГ-ММ-ДД",
}

_TEMPLATE_RE = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class KpiDataSource:
    name: str
    title: str
    description: str
    kind: str
    loader: Loader
    params: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    per_employee: bool = False
    shared: bool = True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "params": dict(self.params),
            "required": list(self.required),
            "fields": list(self.fields),
            "per_employee": self.per_employee,
            "shared": self.shared,
        }


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _in_period(value: Any, ctx: SourceBundle) -> bool:
    day = _day(value)
    if day is None:
        return False
    return ctx.date_from <= day <= ctx.date_to


def _person_key(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _load_outlook(ctx: SourceBundle, _params: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(ctx.events)


def _load_protocols(ctx: SourceBundle, _params: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(ctx.protocols)


def _load_cards(ctx: SourceBundle, _params: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(ctx.cards)


def _load_odata(ctx: SourceBundle, params: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(ctx.load_odata(params))


def _load_xlsx(ctx: SourceBundle, params: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(ctx.load_files(params))


def _load_assignments(ctx: SourceBundle, params: dict[str, Any]) -> list[dict[str, Any]]:
    fio = str(params.get("customer") or ctx.subject_fio or "").strip()
    if not fio:
        return []
    from app.services.erp_assignments import handle_assignments

    result = handle_assignments(
        {
            "action": "list",
            "customer": fio,
            "date_from": ctx.date_from.isoformat(),
            "date_to": ctx.date_to.isoformat(),
            "only_open": False,
            "include_lines": True,
            "limit": int(params.get("top") or 100),
        },
        actor_fio=fio,
    )
    return _rows(result.get("assignments"))


def _load_docflow(ctx: SourceBundle, params: dict[str, Any]) -> list[dict[str, Any]]:
    fio = str(params.get("fio") or ctx.subject_fio or "").strip()
    if not fio:
        return []
    from app.tools.onec.dok_soap import fetch_user_inbox_tasks

    only_open = str(params.get("only_open") or "").strip().lower() in {"1", "true", "yes", "да"}
    payload = fetch_user_inbox_tasks(fio, since_days=int(params.get("since_days") or 90), only_open=only_open)
    rows = _rows(payload.get("rows"))
    if str(params.get("in_period") or "true").strip().lower() in {"0", "false", "no", "нет"}:
        return rows
    return [row for row in rows if _in_period(row.get("due") or row.get("begin"), ctx)]


def _load_platform_tasks(ctx: SourceBundle, params: dict[str, Any]) -> list[dict[str, Any]]:
    fio = str(params.get("fio") or ctx.subject_fio or "").strip()
    if not fio:
        return []
    from sqlalchemy import select

    from app.models.platform_task import PlatformTask

    role = str(params.get("role") or "assignee").strip().lower()
    column = PlatformTask.author_fio if role == "author" else PlatformTask.assignee_fio
    start = datetime.combine(ctx.date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(ctx.date_to, time.max, tzinfo=timezone.utc)
    db = ctx.db
    owned = db is None
    if owned:
        from app.db.session import SessionLocal

        db = SessionLocal()
    try:
        candidates = db.execute(
            select(PlatformTask).where(PlatformTask.due_at >= start, PlatformTask.due_at <= end)
        ).scalars()
        wanted = _person_key(fio)
        rows: list[dict[str, Any]] = []
        for task in candidates:
            if _person_key(getattr(task, column.key)) != wanted:
                continue
            rows.append(
                {
                    "id": task.id,
                    "description": task.description,
                    "priority": task.priority,
                    "status": task.status,
                    "posted_at": task.posted_at.isoformat() if task.posted_at else "",
                    "due_at": task.due_at.isoformat() if task.due_at else "",
                    "status_at": task.status_at.isoformat() if task.status_at else "",
                    "done": task.status == "done",
                    "overdue": bool(
                        task.status == "done"
                        and task.status_at is not None
                        and task.due_at is not None
                        and task.status_at > task.due_at
                    ),
                    "author_fio": task.author_fio,
                    "assignee_fio": task.assignee_fio,
                }
            )
        return rows
    finally:
        if owned:
            db.close()


SOURCES: dict[str, KpiDataSource] = {
    source.name: source
    for source in (
        KpiDataSource(
            name="docflow.tasks",
            title="Задачи 1С:Документооборот сотрудника",
            description=(
                "Задачи сотрудника из ДО: исполнитель, автор, срок, исполнено. "
                "Полная выгрузка кэшируется на 30 минут, первый расчёт медленный."
            ),
            kind="onec",
            loader=_load_docflow,
            params={
                "fio": "ФИО исполнителя, по умолчанию {employee_fio}",
                "only_open": "true — только открытые",
                "since_days": "Глубина выгрузки в днях, по умолчанию 90",
                "in_period": "false — не резать по периоду KPI",
            },
            fields=("id", "title", "step", "performer", "author", "begin", "due", "executed", "done"),
            per_employee=True,
        ),
        KpiDataSource(
            name="onec.assignments",
            title="Поручения АСТ00 (руководитель — сотрудник)",
            description="Журнал поручений 1С, где сотрудник — руководитель (заказчик), за период KPI.",
            kind="onec",
            loader=_load_assignments,
            params={
                "customer": "ФИО руководителя, по умолчанию {employee_fio}",
                "top": "Сколько поручений взять, по умолчанию 100",
            },
            fields=("number", "date", "topic", "status", "due", "executors", "lines", "overdue"),
            per_employee=True,
        ),
        KpiDataSource(
            name="onec.odata",
            title="Произвольный документ 1С через OData",
            description=(
                "Строки документа или справочника 1С. entity — точное имя из каталога OData, "
                "filter — выражение OData с подстановками {period_from_dt}, {period_to_dt}, {employee_fio}."
            ),
            kind="onec",
            loader=_load_odata,
            params={
                "entity": "Имя EntitySet, например Document_ТД_Поручения",
                "filter": "OData $filter, можно с подстановками",
                "top": "Не больше 200",
            },
            required=("entity",),
        ),
        KpiDataSource(
            name="onec.protocols",
            title="Протоколы совещаний (1С)",
            description="Протоколы ТД за период KPI плюс месяц до него.",
            kind="onec",
            loader=_load_protocols,
            fields=("number", "date", "status", "meeting", "decisions"),
        ),
        KpiDataSource(
            name="onec.assignment_cards",
            title="Карточки поручений Совета директоров",
            description="Карточки поручений, которые ведёт трекер поручений СД.",
            kind="onec",
            loader=_load_cards,
        ),
        KpiDataSource(
            name="outlook.calendar",
            title="Календарь Outlook",
            description=(
                "Темы и время встреч за период из Outlook компьютера, где запущен бэкенд "
                "(обычно — самого сотрудника)."
            ),
            kind="outlook",
            loader=_load_outlook,
            fields=("subject", "start", "end"),
        ),
        KpiDataSource(
            name="platform.tasks",
            title="Задачи платформы Оркестратора",
            description="Задачи, поставленные в платформе: срок, приоритет, статус, дата исполнения.",
            kind="platform",
            loader=_load_platform_tasks,
            params={
                "role": "assignee — задачи сотруднику (по умолчанию), author — поставленные им",
                "fio": "ФИО, по умолчанию {employee_fio}",
            },
            fields=("description", "priority", "status", "posted_at", "due_at", "status_at", "done", "overdue"),
            per_employee=True,
        ),
        KpiDataSource(
            name="files.xlsx",
            title="Таблица Excel",
            description=(
                "Строки трекера Excel. Путь должен быть сетевым (\\\\сервер\\папка\\файл.xlsx), "
                "иначе на других компьютерах файла не будет."
            ),
            kind="files",
            loader=_load_xlsx,
            params={"file": "Путь к .xlsx, лучше UNC"},
            required=("file",),
        ),
    )
}


def catalog() -> list[dict[str, Any]]:
    return [source.describe() for source in SOURCES.values()]


def template_values(ctx: SourceBundle) -> dict[str, str]:
    return {
        "employee_fio": ctx.subject_fio,
        "employee_position": ctx.subject_position,
        "period_from": ctx.date_from.isoformat(),
        "period_to": ctx.date_to.isoformat(),
        "period_from_dt": f"{ctx.date_from.isoformat()}T00:00:00",
        "period_to_dt": f"{ctx.date_to.isoformat()}T23:59:59",
        "as_of": ctx.as_of.isoformat(),
    }


def render_params(params: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    def render(value: Any) -> Any:
        if isinstance(value, str):
            return _TEMPLATE_RE.sub(lambda m: values.get(m.group(1), m.group(0)), value)
        if isinstance(value, dict):
            return {key: render(item) for key, item in value.items()}
        if isinstance(value, list):
            return [render(item) for item in value]
        return value

    return {key: render(value) for key, value in (params or {}).items()}


def spec_params(spec: dict[str, Any]) -> dict[str, Any]:
    params = spec.get("params")
    return dict(params) if isinstance(params, dict) else {}


def load(spec: dict[str, Any], ctx: SourceBundle) -> list[dict[str, Any]]:
    source = SOURCES.get(str(spec.get("source") or "").strip())
    if source is None:
        return []
    params = render_params(spec_params(spec), template_values(ctx))
    try:
        return _rows(source.loader(ctx, params))
    except Exception as exc:  # noqa: BLE001 — нет данных лучше, чем падение всей плитки
        logger.warning("kpi source %s failed: %s", source.name, exc)
        return []


LEGACY_LOADERS = frozenset({"outlook", "protocols", "cards", "odata", "files"})


def validate_spec(spec: dict[str, Any] | None) -> dict[str, list[str]]:
    """Ошибки блокируют подключение модуля, предупреждения показываются в карточке KPI."""
    data = spec if isinstance(spec, dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    name = str(data.get("source") or "").strip()
    if not name:
        loader = str(data.get("loader") or "").strip().lower()
        if loader in LEGACY_LOADERS or data.get("entity") or data.get("file") or isinstance(data.get("rows"), list):
            warnings.append("Источник в старом формате. Лучше SOURCE = {'source': ..., 'params': ...}.")
        else:
            errors.append("Модуль не объявил SOURCE из реестра источников — непонятно, откуда брать данные.")
        return {"errors": errors, "warnings": warnings}
    source = SOURCES.get(name)
    if source is None:
        errors.append(f"Источника «{name}» нет в реестре. Доступны: {', '.join(sorted(SOURCES))}.")
        return {"errors": errors, "warnings": warnings}
    params = spec_params(data)
    for key in source.required:
        if not str(params.get(key) or "").strip():
            errors.append(f"{name}: не задан обязательный параметр «{key}».")
    unknown = sorted(set(params) - set(source.params))
    if unknown:
        warnings.append(f"{name}: неизвестные параметры {', '.join(unknown)}.")
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        for var in _TEMPLATE_RE.findall(value):
            if var not in TEMPLATE_VARS:
                errors.append(f"{name}.{key}: подстановки {{{var}}} нет. Есть: {', '.join(TEMPLATE_VARS)}.")
    if name == "onec.odata" and str(params.get("entity") or "").strip():
        entity = str(params["entity"]).strip()
        try:
            from app.services.odata_local_catalog import get_structure

            structure = get_structure(entity)
        except Exception:  # noqa: BLE001
            structure = None
            warnings.append("Каталог OData недоступен, имя документа не проверено.")
        else:
            if structure is None:
                errors.append(f"onec.odata: документа «{entity}» нет в каталоге OData 1С.")
    if name == "files.xlsx":
        path = str(params.get("file") or "").strip()
        if path and not path.startswith("\\\\") and "{" not in path:
            warnings.append("Путь к файлу локальный — на других компьютерах его не будет. Нужен UNC \\\\сервер\\папка.")
        elif path and "{" not in path and not Path(path).exists():
            warnings.append("Файл по этому пути сейчас не открывается.")
    return {"errors": errors, "warnings": warnings}


def describe_for_prompt() -> str:
    lines = [
        "Реестр источников данных KPI. Данные берутся ТОЛЬКО отсюда.",
        "В модуле объяви SOURCE = {'source': '<имя>', 'params': {...}}.",
        "load_<slug>_rows(ctx) должен вернуть ctx.load_for(SOURCE) — сам в сеть и файлы не ходи.",
        "Подстановки в params: " + ", ".join(f"{{{key}}}" for key in TEMPLATE_VARS) + ".",
        "Модуль один на должность и считается для каждого сотрудника: не зашивай ФИО, используй {employee_fio}.",
        "",
    ]
    for source in SOURCES.values():
        lines.append(f"- {source.name}: {source.title}. {source.description}")
        if source.params:
            lines.append("  params: " + "; ".join(f"{k} — {v}" for k, v in source.params.items()))
        if source.fields:
            lines.append("  поля строк: " + ", ".join(source.fields))
    return "\n".join(lines)

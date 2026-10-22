"""Журналы заявок 1С.

Служба 1С и IT — документ Document_ТД_ЗаявкаВСлужбуСопровождения, разные папки
видов. Эксплуатационная служба — Document_ТД_ЗаявкаВ_АХО: отдельной заявки АХО нет.
Служба развития — Document_ТД_ЗаявкаВСлужбуРазвития. Создание номенклатуры,
потребность рынка и сектор рекламы и PR — свои документы.

Человек заполняет вид заявки, место, телефон, срок и текст.
Робот (здесь — запись сервисной учёткой, в 1С это сеанс пользователя) ставит
номер, дату, статус «Подготовлен» и подразделение-исполнитель: его реквизит
у вида заявки, а у заявок АХО, где подразделение в виде пустое, — АХО.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

KIND_CATALOG = "Catalog_ТД_ВидыЗаявокВТехническиеСлужбы"
TECHNICAL_ENTITY = "Document_ТД_ЗаявкаВ_АХО"
SUPPORT_ENTITY = "Document_ТД_ЗаявкаВСлужбуСопровождения"
DEVELOPMENT_ENTITY = "Document_ТД_ЗаявкаВСлужбуРазвития"
TECHNICAL_FILES = "Catalog_ТД_ЗаявкаВ_АХОПрисоединенныеФайлы"
SUPPORT_FILES = "Catalog_ТД_ЗаявкаВСлужбуСопровожденияПрисоединенныеФайлы"
DEVELOPMENT_FILES = "Catalog_ТД_ЗаявкаВСлужбуРазвитияПрисоединенныеФайлы"
NOMENCLATURE_ENTITY = "Document_ТД_ЗаявкаНаСозданиеНоменклатуры"
MARKET_ENTITY = "Document_ТД_ЗаявкаОПотребностиРынка"
PR_ENTITY = "Document_ТД_ЗаявкаВСекторРекламыИPR"
NOMENCLATURE_FILES = "Catalog_ТД_ЗаявкаНаСозданиеНоменклатурыПрисоединенныеФайлы"
MARKET_FILES = "Catalog_ТД_ЗаявкаОПотребностиРынкаПрисоединенныеФайлы"
PR_FILES = "Catalog_ТД_ЗаявкаВСекторРекламыИPRПрисоединенныеФайлы"

EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
IT_DEPARTMENT = "bafd0e4c-1f39-11e2-855f-001e67112509"
SUPPORT_DEPARTMENT = "4668a58d-6eb1-11e2-afce-001e67112509"
AHO_DEPARTMENT = "3a9ac2db-214f-11e0-b91c-00248c26ee57"
DEVELOPMENT_DEPARTMENT = "4668a58b-6eb1-11e2-afce-001e67112509"

# Корни дерева видов. department — чтобы захватить виды прямо в корне справочника
# (ВКС, выдача оргтехники, ЭДО), у которых исполнитель уже проставлен.
SERVICES: dict[str, dict[str, Any]] = {
    "service_1c": {
        "title": "Заявки в службу сопровождения 1С",
        "entity": SUPPORT_ENTITY,
        "files": SUPPORT_FILES,
        "roots": ["Отдел сопровождения 1С"],
        "department": SUPPORT_DEPARTMENT,
        "form_kind": "service_1c",
    },
    "service_it": {
        # В списке 1С «Заявки в службу IT» это тот же документ, что и сопровождение:
        # вид «Замена картриджа» и остальные из папки «Отдел IT».
        "title": "Заявки в службу IT",
        "entity": SUPPORT_ENTITY,
        "files": SUPPORT_FILES,
        "roots": ["Отдел IT"],
        "department": IT_DEPARTMENT,
        "form_kind": "service_it",
    },
    "service_exploitation": {
        "title": "Заявки в Эксплуатационную службу",
        "entity": TECHNICAL_ENTITY,
        "files": TECHNICAL_FILES,
        "roots": [
            "Заявки в Эксплуатационную службу",
            "Энергетик/электрик (Эксплутационная служба)",
        ],
        "form_kind": "service_exploitation",
    },
    "service_development": {
        "title": "Заявки в службу развития",
        "entity": DEVELOPMENT_ENTITY,
        "files": DEVELOPMENT_FILES,
        "roots": ["Служба развития"],
        "department": DEVELOPMENT_DEPARTMENT,
        "form_kind": "service_development",
        # Весь документ — этот журнал, отдельный фильтр по папке видов не нужен.
        "all_documents": True,
    },
    "service_nomenclature": {
        "title": "Заявки на создание номенклатуры",
        "entity": NOMENCLATURE_ENTITY,
        "files": NOMENCLATURE_FILES,
        "roots": ["Заявки на создание / корректировку номенклатуры"],
        "form_kind": "service_nomenclature",
        "all_documents": True,
    },
    "service_market": {
        "title": "Заявки о потребности рынка",
        "entity": MARKET_ENTITY,
        "files": MARKET_FILES,
        "form_kind": "service_market",
        "all_documents": True,
    },
    "service_pr": {
        "title": "Заявки в сектор рекламы и PR",
        "entity": PR_ENTITY,
        "files": PR_FILES,
        "roots": ["Заявки в сектор рекламы и PR"],
        "form_kind": "service_pr",
        "all_documents": True,
    },
    "service_aho": {
        "title": "Журнал заявок в АХО и технические службы",
        "entity": TECHNICAL_ENTITY,
        "files": TECHNICAL_FILES,
        "roots": ["Разнорабочий (Эксплутационная служба)"],
        "executor_fallback": AHO_DEPARTMENT,
        "form_kind": "service_aho",
        "journal": True,
    },
}

STATUSES = {
    "Подготовлен": "Подготовлен",
    "НаСогласовании": "На согласовании",
    "НаИсполнении": "На исполнении",
    "Исполнен": "Исполнен",
    "Отклонено": "Отклонено",
    "Отменен": "Отменён",
    "Аннулирован": "Аннулирован",
}

MARKET_STATUSES = {
    "ПоставленаВПлан": "Поставлена в план",
    "Приостановлена": "Приостановлена",
    "Закрыта": "Закрыта",
    "Аннулирована": "Аннулирована",
}

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DEFAULT_PAGE = 40
_MAX_PAGE = 100
_CACHE_TTL = 600.0
_cache: dict[str, Any] = {"at": 0.0, "rows": []}

_TECH_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "ВидЗаявкиСтрокой",
    "Содержание",
    "Помещение",
    "ТелефонОбратнойСвязи",
    "ЖелаемыйСрокИсполнения",
    "РезолюцияИсполнителя",
    "ВремяВыполнения",
    "ПринятоВОбработку",
    "СрокИсполненияПлановый",
    "СрокИсполненияФактический",
    "ПодтверждениеАвтораОбИсполнении",
)
_TECH_NAVS = (
    "ВидЗаявки",
    "Здание",
    "Организация",
    "Ответственный",
    "Подразделение",
    "ПодразделениеИсполнитель",
    "ФактическийИсполнитель",
)
_SUPPORT_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "Содержание",
    "ТелефонОбратнойСвязи",
    "ЖелаемыйСрокИсполнения",
    "ФизическоеЛицо",
    "Должность",
    "РезолюцияИсполнителя",
    "Приоритет",
    "ВремяВыполнения",
    "ПринятоВОбработку",
    "СрокИсполненияПлановый",
    "СрокИсполненияФактический",
    "ПодтверждениеАвтораОбИсполнении",
    "СоздатьУчетнуюЗаписьERP",
    "СоздатьУчетнуюЗаписьWeb",
    "СоздатьУчетнуюЗаписьPM",
    "СоздатьУчетнуюЗаписьPLM",
    "СоздатьУчетнуюЗаписьЗУП",
    "СоздатьУчетнуюЗаписьУПП",
    "СоздатьУчетнуюЗаписьАЛ",
)
_SUPPORT_NAVS = (
    "ВидЗаявки",
    "Организация",
    "Ответственный",
    "Подразделение",
    "ПодразделениеИсполнитель",
    "ФактическийИсполнитель",
)
_DEV_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "Содержание",
    "ТелефонОбратнойСвязи",
    "СрокИсполненияЖелаемый",
    "РезолюцияИсполнителя",
    "ВремяВыполнения",
    "ПринятоВОбработку",
    "СрокИсполненияПлановый",
    "СрокИсполненияФактический",
    "ПодтверждениеАвтораОбИсполнении",
)
_DEV_NAVS = (
    "ВидЗаявки",
    "Организация",
    "Ответственный",
    "Подразделение",
    "ПодразделениеИсполнитель",
    "ФактическийИсполнитель",
)
_NOM_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "Содержание",
    "ТелефонОбратнойСвязи",
    "ЖелаемыйСрокИсполнения",
    "РезолюцияИсполнителя",
    "РезолюцияДиректораОрганизации",
    "Комментарий",
    "ВремяВыполнения",
    "ПринятоВОбработку",
    "СрокИсполненияФактический",
    "ПодтверждениеАвтораОбИсполнении",
    "СуммаДокумента",
)
_NOM_NAVS = (
    "ВидЗаявки",
    "Организация",
    "Ответственный",
    "Подразделение",
    "ПодразделениеИсполнитель",
)
_MARKET_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "Наименование",
    "ОписаниеПроблемы",
    "ДополнительнаяИнформация",
    "Комментарий",
    "КонтактнаяИнформация",
    "СрокОтработки",
    "СрокОтработкиФакт",
    "ПринятыеМеры",
)
_MARKET_NAVS = (
    "Категория",
    "Партнер",
    "Менеджер",
    "МенеджерПринявшийЗаявку",
    "Подразделение",
    "КонтактноеЛицо",
)
_PR_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "Содержание",
    "Примечание",
    "Задача",
    "ТелефонОбратнойСвязи",
    "СрокИсполненияЖелаемый",
    "РезолюцияИсполнителя",
    "ВремяВыполнения",
    "ПринятоВОбработку",
    "СрокИсполненияПлановый",
    "СрокИсполненияФактический",
    "ПодтверждениеАвтораОбИсполнении",
    "СсылкаНаСайт",
    "ТекстДляСайта",
)
_PR_NAVS = (
    "ВидЗаявки",
    "Организация",
    "Ответственный",
    "Подразделение",
    "ПодразделениеИсполнитель",
    "ФактическийИсполнитель",
)
_ACCOUNT_FLAGS = (
    ("erp", "СоздатьУчетнуюЗаписьERP", "ERP"),
    ("web", "СоздатьУчетнуюЗаписьWeb", "Web"),
    ("pm", "СоздатьУчетнуюЗаписьPM", "PM"),
    ("plm", "СоздатьУчетнуюЗаписьPLM", "PLM"),
    ("zup", "СоздатьУчетнуюЗаписьЗУП", "ЗУП"),
    ("upp", "СоздатьУчетнуюЗаписьУПП", "УПП"),
    ("al", "СоздатьУчетнуюЗаписьАЛ", "АЛ"),
)


class ServiceRequestError(RuntimeError):
    pass


def service_spec(service: str) -> dict[str, Any]:
    spec = SERVICES.get(service)
    if not spec:
        raise ServiceRequestError(
            "Служба: service_1c, service_it, service_exploitation, service_development, "
            "service_nomenclature, service_market или service_pr"
        )
    return spec


def _q(expression: str) -> str:
    return quote(expression, safe="=,'():")


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        raise ServiceRequestError(str(exc)) from exc
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = " ".join(str(value).split())
    if not text or text.startswith("0001-01-01T00:00:00") or text == EMPTY_GUID:
        return ""
    return text


def _nav(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return _text(value.get("Description")) if isinstance(value, dict) else ""


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _label(value: str) -> str:
    return STATUSES.get(value, value)


def _day(raw: Any, *, end: bool) -> str:
    text = str(raw or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    return f"{text}T23:59:59" if end else f"{text}T00:00:00"


def catalog_rows(*, force: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force and _cache["rows"] and now - float(_cache["at"]) < _CACHE_TTL:
        return _cache["rows"]
    rows: list[dict[str, Any]] = []
    skip = 0
    while skip <= 2000:
        data = _odata(
            f"{KIND_CATALOG}?$format=json&$top=200&$skip={skip}"
            "&$select=Ref_Key,Description,Parent_Key,IsFolder,Подразделение_Key,DeletionMark"
        )
        batch = [row for row in (data.get("value") or []) if isinstance(row, dict)]
        rows.extend(batch)
        if len(batch) < 200:
            break
        skip += 200
    _cache["rows"] = rows
    _cache["at"] = now
    return rows


def _root_and_path(row: dict[str, Any], by_key: dict[str, dict[str, Any]]) -> tuple[str, str]:
    chain = [row]
    seen = {str(row.get("Ref_Key") or "")}
    current = row
    while True:
        parent_key = str(current.get("Parent_Key") or "")
        if not parent_key or parent_key == EMPTY_GUID or parent_key in seen:
            break
        parent = by_key.get(parent_key)
        if not parent:
            break
        seen.add(parent_key)
        chain.append(parent)
        current = parent
    names = [str(item.get("Description") or "").strip() for item in reversed(chain)]
    names = [name for name in names if name]
    root = names[0] if names else ""
    path = " → ".join(names[1:]) if len(names) > 1 else root
    return root, path


def leaves_for(service: str, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Виды заявок службы: value — Ref_Key листа, label — путь без корня меню."""
    spec = service_spec(service)
    by_key = {str(row.get("Ref_Key") or ""): row for row in rows if row.get("Ref_Key")}
    roots = set(spec.get("roots") or [])
    department = str(spec.get("department") or "")
    items: list[dict[str, str]] = []
    for row in rows:
        if row.get("IsFolder") or row.get("DeletionMark"):
            continue
        key = str(row.get("Ref_Key") or "")
        if not _GUID_RE.match(key):
            continue
        root, path = _root_and_path(row, by_key)
        own_name = str(row.get("Description") or "").strip()
        in_root = root in roots
        top_level_of_department = bool(department) and str(row.get("Подразделение_Key") or "") == department and root == own_name
        if not in_root and not top_level_of_department:
            continue
        items.append({"value": key, "label": path or own_name})
    items.sort(key=lambda item: item["label"].casefold())
    return items


def kind_options(service: str) -> list[dict[str, str]]:
    return leaves_for(service, catalog_rows())


def kind_keys(service: str) -> list[str]:
    return [item["value"] for item in kind_options(service)]


def kind_path(client: Any, kind_key: str) -> str:
    """Путь вида так, как 1С пишет его в ВидЗаявкиСтрокой: «Корень -> … -> Лист»."""
    names: list[str] = []
    seen: set[str] = set()
    current = kind_key
    while current and current not in seen and _GUID_RE.match(current) and current != EMPTY_GUID:
        seen.add(current)
        try:
            rows = client.get(KIND_CATALOG, ref_key=current)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Путь вида заявки %s не прочитан: %s", current, exc)
            break
        if not rows:
            break
        name = str(rows[0].get("Description") or "").strip()
        if name:
            names.append(name)
        current = str(rows[0].get("Parent_Key") or "")
    return " -> ".join(reversed(names))


def _journal_filter(service: str) -> str:
    """Короткий фильтр: путь в ВидЗаявкиСтрокой, а не сотня guid в URL (1С отвечает 414)."""
    spec = service_spec(service)
    leaves = kind_options(service)
    if spec["entity"] != TECHNICAL_ENTITY:
        return _kind_filter([item["value"] for item in leaves])
    parts = [f"substringof('{_quote(root)}',ВидЗаявкиСтрокой)" for root in spec.get("roots") or []]
    # Виды прямо в корне справочника (ВКС, выдача оргтехники) в путь папки не входят.
    root_names = set(spec.get("roots") or [])
    for item in leaves:
        if item["label"] in root_names or " → " in item["label"]:
            continue
        parts.append(f"ВидЗаявки_Key eq guid'{item['value']}'")
    if not parts:
        raise ServiceRequestError(f"В 1С нет видов заявок для «{spec['title']}»")
    return "(" + " or ".join(parts) + ")"


def _quote(text: str) -> str:
    return text.replace("'", "''")


def executor_for(client: Any, kind_key: str, fallback: str = "") -> str:
    """Подразделение-исполнитель из вида заявки. Пустое в справочнике — запасное (АХО)."""
    dept = ""
    if _GUID_RE.match(kind_key or ""):
        try:
            rows = client.get(KIND_CATALOG, ref_key=kind_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Вид заявки %s не прочитан: %s", kind_key, exc)
            rows = []
        if rows:
            dept = str(rows[0].get("Подразделение_Key") or "")
    if not dept or dept == EMPTY_GUID:
        dept = fallback
    return dept if dept and dept != EMPTY_GUID else ""


def _kind_filter(keys: list[str]) -> str:
    return "(" + " or ".join(f"ВидЗаявки_Key eq guid'{key}'" for key in keys) + ")"


def _entity_shape(entity: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if entity == TECHNICAL_ENTITY:
        return _TECH_FIELDS, _TECH_NAVS
    if entity == DEVELOPMENT_ENTITY:
        return _DEV_FIELDS, _DEV_NAVS
    if entity == NOMENCLATURE_ENTITY:
        return _NOM_FIELDS, _NOM_NAVS
    if entity == MARKET_ENTITY:
        return _MARKET_FIELDS, _MARKET_NAVS
    if entity == PR_ENTITY:
        return _PR_FIELDS, _PR_NAVS
    return _SUPPORT_FIELDS, _SUPPORT_NAVS


def _status_labels(service: str) -> dict[str, str]:
    if service == "service_market":
        return MARKET_STATUSES
    return STATUSES


def _list_path(entity: str, filters: list[str], *, top: int, skip: int) -> str:
    fields, navs = _entity_shape(entity)
    select = quote(",".join([*fields, *(f"{nav}/Description" for nav in navs)]), safe=",/")
    return (
        f"{entity}?$format=json&$top={top}&$skip={skip}&$orderby=Date desc"
        f"&$filter={_q(' and '.join(filters))}&$select={select}&$expand={','.join(navs)}"
    )


def _hours(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if number == 0:
        return ""
    return str(int(number)) if number.is_integer() else str(number)


def _row_view(row: dict[str, Any], *, technical: bool, form_kind: str) -> dict[str, Any]:
    status = _text(row.get("Статус"))
    leaf = _nav(row, "ВидЗаявки")
    path = _text(row.get("ВидЗаявкиСтрокой"))
    # В эксплуатации 1С показывает путь («Заявки в …»), в IT и 1С — лист («Замена картриджа»).
    kind = path if form_kind == "service_exploitation" else (leaf or path)
    accounts = [
        label
        for _key, field, label in _ACCOUNT_FLAGS
        if _flag(row.get(field))
    ]
    view = {
        "id": _text(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": _text(row.get("Date")),
        "status": _label(status),
        "status_code": status,
        "kind": kind,
        "kind_path": path or leaf,
        "document_type": {
            "service_development": "Заявка в службу развития",
            "service_nomenclature": "Заявка на создание номенклатуры",
            "service_market": "Заявка о потребности рынка",
            "service_pr": "Заявка в сектор рекламы и PR",
        }.get(form_kind, "Заявка в АХО" if technical else "Заявка в службу сопровождения"),
        "form_kind": form_kind,
        "text": _text(row.get("Содержание")),
        "room": _text(row.get("Помещение")),
        "building": _nav(row, "Здание"),
        "phone": _text(row.get("ТелефонОбратнойСвязи")),
        "due": (
            _text(row.get("ЖелаемыйСрокИсполнения"))
            or _text(row.get("СрокИсполненияЖелаемый"))
            or _text(row.get("СрокОтработки"))
        ),
        "organization": _nav(row, "Организация"),
        "responsible": _nav(row, "Ответственный"),
        "department": _nav(row, "Подразделение"),
        "executor_department": _nav(row, "ПодразделениеИсполнитель"),
        "executor": _nav(row, "ФактическийИсполнитель"),
        "resolution": _text(row.get("РезолюцияИсполнителя")),
        "hours": _hours(row.get("ВремяВыполнения")),
        "accepted_at": _text(row.get("ПринятоВОбработку")),
        "planned_at": _text(row.get("СрокИсполненияПлановый")),
        "done_at": _text(row.get("СрокИсполненияФактический")) or _text(row.get("СрокОтработкиФакт")),
        "confirmed": bool(_text(row.get("ПодтверждениеАвтораОбИсполнении"))),
        "confirmed_at": _text(row.get("ПодтверждениеАвтораОбИсполнении")),
        "person": _text(row.get("ФизическоеЛицо")),
        "position": _text(row.get("Должность")),
        "priority": _text(row.get("Приоритет")),
        "accounts": ", ".join(accounts),
        "posted": _flag(row.get("Posted")),
        "technical": technical,
    }
    if form_kind == "service_market":
        view["kind"] = _nav(row, "Категория")
        view["text"] = _text(row.get("Наименование"))
        view["organization"] = _nav(row, "Партнер")
        view["responsible"] = _nav(row, "Менеджер")
        view["executor"] = _nav(row, "МенеджерПринявшийЗаявку")
        view["resolution"] = _text(row.get("ОписаниеПроблемы")) or _text(row.get("ДополнительнаяИнформация"))
        view["phone"] = _text(row.get("КонтактнаяИнформация"))
        view["status"] = MARKET_STATUSES.get(status, view["status"])
    elif form_kind == "service_pr":
        note = _text(row.get("Примечание"))
        task = _text(row.get("Задача"))
        view["text"] = " ".join(part for part in (view["text"], task, note) if part)
    return view


def _period_filters(args: dict[str, Any], allowed: dict[str, str]) -> list[str]:
    filters = ["DeletionMark eq false"]
    start = _day(args.get("date_from"), end=False)
    finish = _day(args.get("date_to"), end=True)
    if start:
        filters.append(f"Date ge datetime'{start}'")
    if finish:
        filters.append(f"Date le datetime'{finish}'")
    status = str(args.get("status") or "").strip()
    if status:
        if status not in allowed:
            raise ServiceRequestError("Неизвестный статус заявки")
        filters.append(f"Статус eq '{status}'")
    return filters


def _fetch_rows(entity: str, filters: list[str], *, top: int, skip: int, form_kind: str) -> list[dict[str, Any]]:
    technical = entity == TECHNICAL_ENTITY
    raw = [
        row
        for row in (_odata(_list_path(entity, filters, top=top, skip=skip)).get("value") or [])
        if isinstance(row, dict)
    ]
    return [_row_view(row, technical=technical, form_kind=form_kind) for row in raw]


def _page(
    service: str,
    title: str,
    rows: list[dict[str, Any]],
    *,
    skip: int,
    top: int,
    fetched: int,
    statuses: dict[str, str],
) -> dict[str, Any]:
    return {
        "summary": f"{title}: {len(rows)}",
        "service": service,
        "title": title,
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(rows),
        "has_more": fetched >= top,
        "statuses": [{"code": code, "label": label} for code, label in statuses.items()],
    }


def _journal_form(row: dict[str, Any]) -> dict[str, Any]:
    """В общем журнале форма открытия следует пути вида, а не одному ярлыку на документ."""
    if not row.get("technical"):
        return row
    path = str(row.get("kind_path") or "")
    for prefix, kind in (
        ("Служба развития", "service_development"),
        ("Заявки в Эксплуатационную службу", "service_exploitation"),
        ("Энергетик/электрик", "service_exploitation"),
        ("Разнорабочий", "service_aho"),
    ):
        if path.startswith(prefix):
            row["form_kind"] = kind
            break
    return row


def list_requests(args: dict[str, Any]) -> dict[str, Any]:
    service = str(args.get("service") or "").strip()
    spec = service_spec(service)
    top = max(1, min(int(args.get("top") or _DEFAULT_PAGE), _MAX_PAGE))
    skip = max(0, int(args.get("skip") or 0))
    labels = _status_labels(service)
    filters = _period_filters(args, labels)
    if spec.get("journal"):
        # Журнал 1С собирает заявки в службы и заявки в АХО. Отдельного OData-журнала нет.
        window = min(_MAX_PAGE, top + skip)
        technical = _fetch_rows(TECHNICAL_ENTITY, filters, top=window, skip=0, form_kind="service_exploitation")
        support = _fetch_rows(SUPPORT_ENTITY, filters, top=window, skip=0, form_kind="service_1c")
        merged = sorted(
            (_journal_form(row) for row in (*technical, *support)),
            key=lambda row: row.get("date") or "",
            reverse=True,
        )
        page = merged[skip: skip + top]
        return _page(service, spec["title"], page, skip=skip, top=top, fetched=len(merged[skip:]), statuses=labels)
    if not spec.get("all_documents"):
        if not kind_keys(service):
            raise ServiceRequestError(f"В 1С нет видов заявок для «{spec['title']}»")
        filters.append(_journal_filter(service))
    rows = _fetch_rows(
        spec["entity"],
        filters,
        top=top,
        skip=skip,
        form_kind=str(spec.get("form_kind") or service),
    )
    return _page(service, spec["title"], rows, skip=skip, top=top, fetched=len(rows), statuses=labels)


def handle_docflow_service_requests(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return list_requests(args)
    except ServiceRequestError as exc:
        raise OnecToolError(str(exc)) from exc

"""Журнал заявок на расходование ДС 1С (Document_ЗаявкаНаРасходованиеДенежныхСредств)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.services import docflow_refs

logger = logging.getLogger(__name__)

ENTITY = "Document_ЗаявкаНаРасходованиеДенежныхСредств"
_NAVS = (
    "Организация",
    "Контрагент",
    "Валюта",
    "Подразделение",
    "КтоЗаявил",
    "КтоРешил",
    "Автор",
    "ТД_ЦФО",
    "ПодотчетноеЛицо",
    "ОрганизацияПолучатель",
    "СтатьяДвиженияДенежныхСредств",
    "ПриоритетОплаты",
)
_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "ХозяйственнаяОперация",
    "СуммаДокумента",
    "ФормаОплатыЗаявки",
    "НазначениеПлатежа",
    "ЖелательнаяДатаПлатежа",
    "ДатаПлатежа",
    "Комментарий",
    "СверхЛимита",
    "Закрыта",
    "ТД_ДляПроизводства",
    "ТекстПлательщика",
)
# Строки расшифровки платежа приходят без навигаций — только ключи справочников.
_PART_REFS = {
    "Партнер": "Catalog_Партнеры",
    "Контрагент": "Catalog_Контрагенты",
    "Подразделение": "Catalog_СтруктураПредприятия",
    "СтатьяДвиженияДенежныхСредств": "Catalog_СтатьиДвиженияДенежныхСредств",
    "НаправлениеДеятельности": "Catalog_НаправленияДеятельности",
    "СтавкаНДС": "Catalog_СтавкиНДС",
}
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_PAGE = 40
_MAX_PAGE = 100

STATUSES = {
    "НеСогласована": "Не согласована",
    "Согласована": "Согласована",
    "КОплате": "К оплате",
    "Отклонена": "Отклонена",
}
OPERATIONS = {
    "ОплатаПоставщику": "Оплата поставщику",
    "ВыплатаЗарплаты": "Выплата зарплаты",
    "ВыдачаДенежныхСредствПодотчетнику": "Выдача под отчёт",
    "ПеречислениеВБюджет": "Перечисление в бюджет",
    "ПрочаяВыдачаДенежныхСредств": "Прочая выдача ДС",
    "ОплатаАрендодателю": "Оплата арендодателю",
    "ПеречислениеТаможне": "Перечисление таможне",
    "ВозвратОплатыКлиенту": "Возврат оплаты клиенту",
    "ПрочееСписаниеБезналичныхДенежныхСредств": "Прочее списание безналичных",
    "ПереводНаДругойСчетОрганизации": "Перевод на другой счёт",
}
PAYMENT_FORMS = {
    "Безналичная": "Безналичная",
    "Наличная": "Наличная",
    "ПлатежнаяКарта": "Платёжная карта",
}


class DocflowPaymentRequestError(RuntimeError):
    pass


def _q(expression: str) -> str:
    return quote(expression, safe="=,'():")


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        raise DocflowPaymentRequestError(str(exc)) from exc
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = " ".join(str(value).split())
    if not text or text.startswith("0001-01-01T00:00:00") or text == _EMPTY_GUID:
        return ""
    return text


def _nav(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return _text(value.get("Description")) if isinstance(value, dict) else ""


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _amount(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _label(value: str, table: dict[str, str]) -> str:
    if value in table:
        return table[value]
    spaced = re.sub(r"(?<=[а-яё])(?=[А-ЯЁ])", " ", value)
    return spaced[:1].upper() + spaced[1:].lower() if spaced else ""


def _recipient(row: dict[str, Any]) -> str:
    """Получателем может быть контрагент, подотчётник или другая организация группы."""
    for key in ("Контрагент", "ПодотчетноеЛицо", "ОрганизацияПолучатель"):
        name = _nav(row, key)
        if name:
            return name
    return ""


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    status = _text(row.get("Статус"))
    operation = _text(row.get("ХозяйственнаяОперация"))
    form = _text(row.get("ФормаОплатыЗаявки"))
    return {
        "id": _text(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": _text(row.get("Date")),
        "status": _label(status, STATUSES),
        "status_code": status,
        "operation": _label(operation, OPERATIONS),
        "operation_code": operation,
        "amount": _amount(row.get("СуммаДокумента")),
        "currency": _nav(row, "Валюта"),
        "payment_form": _label(form, PAYMENT_FORMS),
        "payment_form_code": form,
        "recipient": _recipient(row),
        "counterparty": _nav(row, "Контрагент"),
        "organization": _nav(row, "Организация"),
        "department": _nav(row, "Подразделение"),
        "requested_by": _nav(row, "КтоЗаявил"),
        "decided_by": _nav(row, "КтоРешил"),
        "author": _nav(row, "Автор"),
        "cfo": _nav(row, "ТД_ЦФО"),
        "cash_flow_item": _nav(row, "СтатьяДвиженияДенежныхСредств"),
        "priority": _nav(row, "ПриоритетОплаты"),
        "purpose": _text(row.get("НазначениеПлатежа")),
        "wanted_date": _text(row.get("ЖелательнаяДатаПлатежа")),
        "payment_date": _text(row.get("ДатаПлатежа")),
        "comment": _text(row.get("Комментарий")),
        "over_limit": _flag(row.get("СверхЛимита")),
        "closed": _flag(row.get("Закрыта")),
        "for_production": _flag(row.get("ТД_ДляПроизводства")),
        "posted": _flag(row.get("Posted")),
    }


def _day(raw: Any, *, end: bool) -> str:
    text = str(raw or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    return f"{text}T23:59:59" if end else f"{text}T00:00:00"


def _clean_code(value: Any) -> str:
    return re.sub(r"[^A-Za-zА-Яа-яЁё0-9]", "", str(value or ""))


def _list_path(filters: list[str], *, top: int, skip: int, with_parts: bool) -> str:
    """Табличные части приходят сами, когда нет $select: расширять их 1С не даёт (HTTP 501)."""
    select = f"&$select={quote(','.join([*_FIELDS, *(f'{nav}/Description' for nav in _NAVS)]), safe=',/')}"
    return (
        f"{ENTITY}?$format=json&$top={top}&$skip={skip}&$orderby=Date desc"
        f"&$filter={_q(' and '.join(filters))}{'' if with_parts else select}&$expand={','.join(_NAVS)}"
    )


def list_payment_requests(args: dict[str, Any]) -> dict[str, Any]:
    top = max(1, min(int(args.get("top") or _DEFAULT_PAGE), _MAX_PAGE))
    skip = max(0, int(args.get("skip") or 0))
    filters = ["DeletionMark eq false"]
    start = _day(args.get("date_from"), end=False)
    finish = _day(args.get("date_to"), end=True)
    if start:
        filters.append(f"Date ge datetime'{start}'")
    if finish:
        filters.append(f"Date le datetime'{finish}'")
    status = _clean_code(args.get("status"))
    if status:
        filters.append(f"Статус eq '{status}'")
    operation = _clean_code(args.get("operation"))
    if operation:
        filters.append(f"ХозяйственнаяОперация eq '{operation}'")
    form = _clean_code(args.get("payment_form"))
    if form:
        filters.append(f"ФормаОплатыЗаявки eq '{form}'")
    raw = [
        row
        for row in (_odata(_list_path(filters, top=top, skip=skip, with_parts=False)).get("value") or [])
        if isinstance(row, dict)
    ]
    rows = [_row_view(row) for row in raw]
    return {
        "summary": f"Заявки на расходование ДС: {len(rows)}",
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(raw),
        "has_more": len(raw) >= top,
        "total_amount": round(sum(row["amount"] for row in rows), 2),
        "statuses": [{"code": code, "label": label} for code, label in STATUSES.items()],
        "operations": [{"code": code, "label": label} for code, label in OPERATIONS.items()],
        "payment_forms": [{"code": code, "label": label} for code, label in PAYMENT_FORMS.items()],
    }


def _part(row: dict[str, Any], name: str) -> list[dict[str, Any]]:
    items = [item for item in (row.get(name) or []) if isinstance(item, dict)]
    items.sort(key=lambda item: int(item.get("LineNumber") or 0))
    return items


def payment_request_card(args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowPaymentRequestError("Нужен Ref_Key заявки")
    # $expand табличных частей работает только в списке: одиночный GET по guid его не принимает.
    found = _odata(_list_path([f"Ref_Key eq guid'{ref}'"], top=1, skip=0, with_parts=True)).get("value") or []
    row = found[0] if found and isinstance(found[0], dict) else {}
    if not row:
        raise DocflowPaymentRequestError("1С не вернула заявку")
    view = _row_view(row)
    breakdown_rows = _part(row, "РасшифровкаПлатежа")
    document_rows = _part(row, "ПодтверждающиеДокументы")
    employee_rows = _part(row, "ЛицевыеСчетаСотрудников")
    refs: defaultdict[str, set[str]] = defaultdict(set)
    for item in breakdown_rows:
        for field, entity in _PART_REFS.items():
            refs[entity].add(_text(item.get(f"{field}_Key")))
        refs[docflow_refs.entity_of(item, "СтатьяРасходов")].add(_text(item.get("СтатьяРасходов")))
    for item in document_rows:
        refs["Catalog_ВидыПодтверждающихДокументов"].add(_text(item.get("ВидДокумента_Key")))
    for item in employee_rows:
        refs["Catalog_ФизическиеЛица"].add(_text(item.get("ФизическоеЛицо_Key")))
        refs["Catalog_БанковскиеСчетаКонтрагентов"].add(_text(item.get("ЛицевойСчет_Key")))
    docflow_refs.resolve(refs)

    def ref(item: dict[str, Any], field: str, entity: str) -> str:
        return docflow_refs.name(entity, item.get(f"{field}_Key"))

    breakdown = [
        {
            "n": int(item.get("LineNumber") or 0),
            "amount": _amount(item.get("Сумма")),
            "vat": _amount(item.get("СуммаНДС")),
            "partner": ref(item, "Партнер", "Catalog_Партнеры"),
            "counterparty": ref(item, "Контрагент", "Catalog_Контрагенты"),
            "department": ref(item, "Подразделение", "Catalog_СтруктураПредприятия"),
            "cash_flow_item": ref(item, "СтатьяДвиженияДенежныхСредств", "Catalog_СтатьиДвиженияДенежныхСредств"),
            "activity": ref(item, "НаправлениеДеятельности", "Catalog_НаправленияДеятельности"),
            "vat_rate": ref(item, "СтавкаНДС", "Catalog_СтавкиНДС"),
            "expense_item": docflow_refs.typed_name(item, "СтатьяРасходов"),
            "comment": _text(item.get("Комментарий")),
        }
        for item in breakdown_rows
    ]
    accounts = [
        {
            "n": int(item.get("LineNumber") or 0),
            "amount": _amount(item.get("Сумма")),
            "date": _text(item.get("ДатаПлатежа")),
        }
        for item in _part(row, "РаспределениеПоСчетам")
    ]
    documents = [
        {
            "n": int(item.get("LineNumber") or 0),
            "kind": ref(item, "ВидДокумента", "Catalog_ВидыПодтверждающихДокументов"),
            "number": _text(item.get("Номер")),
            "date": _text(item.get("Дата")),
            "amount": _amount(item.get("Сумма")),
        }
        for item in document_rows
    ]
    employees = [
        {
            "n": int(item.get("LineNumber") or 0),
            "person": ref(item, "ФизическоеЛицо", "Catalog_ФизическиеЛица"),
            "account": ref(item, "ЛицевойСчет", "Catalog_БанковскиеСчетаКонтрагентов"),
            "amount": _amount(item.get("Сумма")),
        }
        for item in employee_rows
    ]
    return {
        "summary": f"Заявка на расходование ДС {view['number']}",
        "request": view,
        "breakdown": breakdown,
        "accounts": accounts,
        "documents": documents,
        "employees": employees,
        "stats": {
            "breakdown": len(breakdown),
            "breakdown_amount": round(sum(item["amount"] for item in breakdown), 2),
            "vat_amount": round(sum(item["vat"] for item in breakdown), 2),
            "documents": len(documents),
        },
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def handle_docflow_payment_requests(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return list_payment_requests(args)
    except DocflowPaymentRequestError as exc:
        raise OnecToolError(str(exc)) from exc


def handle_docflow_payment_request_card(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return payment_request_card(args)
    except DocflowPaymentRequestError as exc:
        raise OnecToolError(str(exc)) from exc

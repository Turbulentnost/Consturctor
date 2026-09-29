"""Журнал поручений экспедитору 1С (Document_ПоручениеЭкспедитору)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.services import docflow_refs

logger = logging.getLogger(__name__)

ENTITY = "Document_ПоручениеЭкспедитору"
_NAVS = (
    "Склад",
    "Ответственный",
    "Подразделение",
    "Грузоотправитель",
    "Грузополучатель",
    "ГрузополучательКонтрагент",
    "Плательщик",
    "ЗонаДоставки",
    "ТипТранспортногоСредства",
    "КонтактноеЛицо",
    "ТД_Контрагент",
    "ТД_КонтрагентГрузополучателя",
    "ТД_КонтрагентПлательщика",
    "ТД_Город",
    "ТД_Терминал",
)
_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "ТД_Статус",
    "ТипыЗаявок",
    "СпособДоставки",
    "ХарактерПогрузки",
    "ДатаВыполнения",
    "ВремяДоставкиС",
    "ВремяДоставкиПо",
    "АдресДоставки",
    "АдресГрузополучателя",
    "КонтактноеЛицоГрузополучателя",
    "ТелефонКонтактногоЛица",
    "ТД_ТелефонГрузополучателя",
    "КоличествоМест",
    "Вес",
    "Объем",
    "Длина",
    "Ширина",
    "Высота",
    "ТД_ПлательщикНаправление",
    "ТД_СтоимостьГруза",
    "ТД_КомплектностьОтгрузки",
    "ТД_БизнесПроцессЗапущен",
    "ТД_НеобходимоСогласованиеИсполнительногоДиректора",
    "ТД_Откуда",
    "ТД_Куда",
    "ТД_Пассажир",
    "ТД_ТелефонПассажира",
    "ТД_ЦельПоездки",
    "ДополнительнаяИнформацияПоДоставке",
    "ОсобыеУсловияПеревозкиОписание",
    "Комментарий",
)
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_PAGE = 40
_MAX_PAGE = 100

STATUSES = {
    "Подготовлен": "Подготовлен",
    "НаСогласовании": "На согласовании",
    "Согласовано": "Согласовано",
    "Отклонено": "Отклонено",
}
KINDS = {
    "ЗаявкаНаПеревозГрузовНаТерриторииБазыЛибоГРП": "Грузы на территории базы / ГРП",
    "ЗаявкаНаПеревозТМЦ": "Перевозка ТМЦ",
    "ЗаявкиНаПеревозкуГрузовВЛогистическиеКомпании": "Грузы в логистические компании",
    "ПассажирскиеПеревозкиКорпоративныйТранспорт": "Пассажирские, корпоративный транспорт",
    "Такси": "Такси",
    "ЗаявкаНаПеревозДокументов": "Перевозка документов",
}
DELIVERY_WAYS = {
    "ПоручениеЭкспедиторуСоСклада": "Со склада",
    "ПоручениеЭкспедиторуНаСклад": "На склад",
    "ПоручениеЭкспедиторуВПункте": "В пункте",
}
LOADING = {"Верхняя": "Верхняя", "Задняя": "Задняя", "Боковая": "Боковая"}


class DocflowForwardingError(RuntimeError):
    pass


def _q(expression: str) -> str:
    return quote(expression, safe="=,'():")


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        raise DocflowForwardingError(str(exc)) from exc
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


def _number(value: Any) -> float:
    try:
        return round(float(value or 0), 3)
    except (TypeError, ValueError):
        return 0.0


def _time(value: Any) -> str:
    """Время доставки хранится как 0001-01-01T09:00:00."""
    match = re.search(r"T(\d{2}:\d{2})", str(value or ""))
    return match.group(1) if match and match.group(1) != "00:00" else ""


def _label(value: str, table: dict[str, str]) -> str:
    if value in table:
        return table[value]
    spaced = re.sub(r"(?<=[а-яё])(?=[А-ЯЁ])", " ", value)
    return spaced[:1].upper() + spaced[1:].lower() if spaced else ""


def _consignee(row: dict[str, Any]) -> str:
    for key in ("ТД_КонтрагентГрузополучателя", "ГрузополучательКонтрагент", "Грузополучатель"):
        name = _nav(row, key)
        if name:
            return name
    return _text(row.get("КонтактноеЛицоГрузополучателя"))


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    status = _text(row.get("ТД_Статус"))
    kind = _text(row.get("ТипыЗаявок"))
    way = _text(row.get("СпособДоставки"))
    loading = _text(row.get("ХарактерПогрузки"))
    start, finish = _time(row.get("ВремяДоставкиС")), _time(row.get("ВремяДоставкиПо"))
    return {
        "id": _text(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": _text(row.get("Date")),
        "status": _label(status, STATUSES),
        "status_code": status,
        "kind": _label(kind, KINDS),
        "kind_code": kind,
        "way": _label(way, DELIVERY_WAYS),
        "way_code": way,
        "loading": _label(loading, LOADING),
        "done_at": _text(row.get("ДатаВыполнения")),
        "window": f"{start}–{finish}" if start and finish else start,
        "address": _text(row.get("АдресДоставки")),
        "consignee_address": _text(row.get("АдресГрузополучателя")),
        "warehouse": _nav(row, "Склад"),
        "responsible": _nav(row, "Ответственный"),
        "department": _nav(row, "Подразделение"),
        "shipper": _nav(row, "Грузоотправитель"),
        "consignee": _consignee(row),
        "counterparty": _nav(row, "ТД_Контрагент"),
        "payer": _nav(row, "ТД_КонтрагентПлательщика") or _nav(row, "Плательщик"),
        "payer_direction": _text(row.get("ТД_ПлательщикНаправление")),
        "zone": _nav(row, "ЗонаДоставки"),
        "city": _nav(row, "ТД_Город"),
        "terminal": _nav(row, "ТД_Терминал"),
        "transport": _nav(row, "ТипТранспортногоСредства"),
        "contact": _nav(row, "КонтактноеЛицо") or _text(row.get("КонтактноеЛицоГрузополучателя")),
        "phone": _text(row.get("ТелефонКонтактногоЛица")) or _text(row.get("ТД_ТелефонГрузополучателя")),
        "places": int(_number(row.get("КоличествоМест"))),
        "weight": _number(row.get("Вес")),
        "volume": _number(row.get("Объем")),
        "size": "×".join(
            part
            for part in (
                _text(row.get("Длина")),
                _text(row.get("Ширина")),
                _text(row.get("Высота")),
            )
            if part and part != "0"
        ),
        "cargo_cost": _number(row.get("ТД_СтоимостьГруза")),
        "complete": _flag(row.get("ТД_КомплектностьОтгрузки")),
        "process_started": _flag(row.get("ТД_БизнесПроцессЗапущен")),
        "needs_director": _flag(row.get("ТД_НеобходимоСогласованиеИсполнительногоДиректора")),
        "route_from": _text(row.get("ТД_Откуда")),
        "route_to": _text(row.get("ТД_Куда")),
        "passenger": _text(row.get("ТД_Пассажир")),
        "passenger_phone": _text(row.get("ТД_ТелефонПассажира")),
        "trip_purpose": _text(row.get("ТД_ЦельПоездки")),
        "delivery_note": _text(row.get("ДополнительнаяИнформацияПоДоставке")),
        "special_terms": _text(row.get("ОсобыеУсловияПеревозкиОписание")),
        "comment": _text(row.get("Комментарий")),
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


def list_forwarding(args: dict[str, Any]) -> dict[str, Any]:
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
        filters.append(f"ТД_Статус eq '{status}'")
    kind = _clean_code(args.get("kind"))
    if kind:
        filters.append(f"ТипыЗаявок eq '{kind}'")
    way = _clean_code(args.get("way"))
    if way:
        filters.append(f"СпособДоставки eq '{way}'")
    raw = [
        row
        for row in (_odata(_list_path(filters, top=top, skip=skip, with_parts=False)).get("value") or [])
        if isinstance(row, dict)
    ]
    rows = [_row_view(row) for row in raw]
    return {
        "summary": f"Поручения экспедитору: {len(rows)}",
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(raw),
        "has_more": len(raw) >= top,
        "statuses": [{"code": code, "label": label} for code, label in STATUSES.items()],
        "kinds": [{"code": code, "label": label} for code, label in KINDS.items()],
        "ways": [{"code": code, "label": label} for code, label in DELIVERY_WAYS.items()],
    }


def _part(row: dict[str, Any], name: str) -> list[dict[str, Any]]:
    items = [item for item in (row.get(name) or []) if isinstance(item, dict)]
    items.sort(key=lambda item: int(item.get("LineNumber") or 0))
    return items


def forwarding_card(args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowForwardingError("Нужен Ref_Key поручения")
    # $expand табличных частей работает только в списке: одиночный GET по guid его не принимает.
    found = _odata(_list_path([f"Ref_Key eq guid'{ref}'"], top=1, skip=0, with_parts=True)).get("value") or []
    row = found[0] if found and isinstance(found[0], dict) else {}
    if not row:
        raise DocflowForwardingError("1С не вернула поручение")
    view = _row_view(row)
    cargo_rows = _part(row, "ТД_ГабаритыГруза")
    device_rows = _part(row, "ТД_Приборы")
    base_rows = _part(row, "Основания")
    refs: defaultdict[str, set[str]] = defaultdict(set)
    for item in [*cargo_rows, *device_rows]:
        for field in ("Номенклатура", "ЗаказКлиента", "ОпросныйЛист", "НомерПрибора"):
            refs[docflow_refs.entity_of(item, field)].add(_text(item.get(field)))
    for item in device_rows:
        refs["Document_УпаковочныйЛист"].add(_text(item.get("УпаковочныйЛист_Key")))
    for item in base_rows:
        refs[docflow_refs.entity_of(item, "Основание")].add(_text(item.get("Основание")))
    docflow_refs.resolve(refs)

    cargo = [
        {
            "n": int(item.get("LineNumber") or 0),
            "name": docflow_refs.typed_name(item, "Номенклатура"),
            "feature": _text(item.get("Характеристика")),
            "serial": docflow_refs.typed_name(item, "НомерПрибора"),
            "order": docflow_refs.typed_name(item, "ЗаказКлиента"),
            "length": _number(item.get("Длина")),
            "width": _number(item.get("Ширина")),
            "height": _number(item.get("Высота")),
            "weight": _number(item.get("Вес")),
            "volume": _number(item.get("Объем")),
            "module": _text(item.get("НазваниеМодуля")),
        }
        for item in cargo_rows
    ]
    devices = [
        {
            "n": int(item.get("LineNumber") or 0),
            "name": docflow_refs.typed_name(item, "Номенклатура"),
            "feature": _text(item.get("Характеристика")),
            "serial": docflow_refs.typed_name(item, "НомерПрибора"),
            "order": docflow_refs.typed_name(item, "ЗаказКлиента"),
            "places": int(_number(item.get("КоличествоМест"))),
            "delivery": _text(item.get("Доставка")),
            "delivery_amount": _number(item.get("СуммаДоставки")),
            "module": _text(item.get("НазваниеМодуля")),
            "packing_list": docflow_refs.name("Document_УпаковочныйЛист", item.get("УпаковочныйЛист_Key")),
        }
        for item in device_rows
    ]
    orders = [
        {"n": int(item.get("LineNumber") or 0), "order": _text(item.get("Заказ")), "uid": _text(item.get("УИД"))}
        for item in _part(row, "ТД_ЗаказыНаДоставку")
    ]
    bases = [
        {
            "n": int(item.get("LineNumber") or 0),
            "kind": _label(docflow_refs.entity_of(item, "Основание").split("_", 1)[-1], {}),
            "title": docflow_refs.typed_name(item, "Основание"),
        }
        for item in base_rows
    ]
    return {
        "summary": f"Поручение экспедитору {view['number']}",
        "order": view,
        "cargo": cargo,
        "devices": devices,
        "orders": orders,
        "bases": bases,
        "stats": {
            "cargo": len(cargo),
            "cargo_weight": round(sum(item["weight"] for item in cargo), 3),
            "cargo_volume": round(sum(item["volume"] for item in cargo), 3),
            "devices": len(devices),
        },
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def handle_docflow_forwarding(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return list_forwarding(args)
    except DocflowForwardingError as exc:
        raise OnecToolError(str(exc)) from exc


def handle_docflow_forwarding_card(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return forwarding_card(args)
    except DocflowForwardingError as exc:
        raise OnecToolError(str(exc)) from exc

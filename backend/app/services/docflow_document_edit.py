"""Карточка уже записанного документа: открыть, изменить, «Создать на основании», файлы.

Изменяется только черновик (не проведён). Запись проведённого документа через
OData перепроводит его, а у документов ТД проведение запускает согласование —
такие правки делают в самой 1С. Меняются только реквизиты, которые человек
тронул в форме (changed): неизменённые ссылки не пересобираются по
наименованию и не могут «уехать» на однофамильца.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import docflow_document_create as dc
from app.services.docflow_document_create import (
    _GUID_RE,
    _PROPERTY_CATALOG,
    BASIS_LINK,
    BASIS_TARGETS,
    EMPTY_GUID,
    FILE_CATALOGS,
    KINDS,
    STRING_TYPE,
    UNDEFINED_TYPE,
    DocumentCreateError,
    _convert,
    _decode_files,
    _kind,
    _ODataClient,
    _property_rows,
    _table_rows,
    _web_url,
    attach_files,
    edit_fields,
    ensure_probe,
    files_summary,
    put_value,
)

_ODATA_PREFIX = "StandardODATA."
_EMPTY_DATE = "0001-01-01T00:00:00"

THEME_KEY = {
    "incoming": "ТемаСлужебнойЗаписки",
    "outgoing": "ТемаСлужебнойЗаписки",
    "memo": "ТемаСлужебнойЗаписки",
    "order": "ТемаСлужебнойЗаписки",
    "directive": "ТемаСлужебнойЗаписки",
    "assignment": "ОЧем",
    "payment": "НазначениеПлатежа",
    "forwarding": "ОсобыеУсловияПеревозкиОписание",
    "incentive": "Заголовок",
}
TEXT_KEY = {
    "incoming": "Содержание",
    "outgoing": "Содержание",
    "memo": "ТекстСлужебнойЗаписки",
    "order": "Содержание",
    "directive": "Содержание",
    "incentive": "Содержание",
}


class _Names:
    """Наименования ссылок карточки: один GET на объект, повторы из памяти."""

    def __init__(self, client: _ODataClient) -> None:
        self.client = client
        self.cache: dict[tuple[str, str], str] = {}

    def __call__(self, catalog: str, ref_key: Any) -> str:
        key = str(ref_key or "")
        if not _GUID_RE.match(key) or key == EMPTY_GUID:
            return ""
        if (catalog, key) not in self.cache:
            try:
                rows = self.client.get(catalog, ref_key=key)
                self.cache[(catalog, key)] = str(rows[0].get("Description") or "") if rows else ""
            except Exception:  # noqa: BLE001
                self.cache[(catalog, key)] = ""
        return self.cache[(catalog, key)]


def _catalog_of(type_name: Any) -> str:
    text = str(type_name or "")
    if text.startswith(f"{_ODATA_PREFIX}Catalog_"):
        return text[len(_ODATA_PREFIX):]
    return ""


def _display(field: dict[str, Any], row: dict[str, Any], names: _Names) -> tuple[str, str]:
    """Значение для формы и GUID ссылки (если это ссылка)."""
    key = field["key"]
    raw = row.get(key)
    type_name = row.get(f"{key}_Type")
    kind = field["type"]
    if kind == "ref":
        if field.get("composite"):
            catalog = _catalog_of(type_name)
            if catalog:
                return names(catalog, raw), str(raw or "")
            return ("" if type_name == UNDEFINED_TYPE else str(raw or "")), ""
        if _GUID_RE.match(str(raw or "")) and raw != EMPTY_GUID:
            return names(field["catalog"], raw), str(raw)
        return "", ""
    if field.get("composite"):
        catalog = _catalog_of(type_name)
        if catalog:
            return names(catalog, raw), ""
        if type_name and type_name != STRING_TYPE:
            return "", ""
    if kind == "date":
        text = str(raw or "")
        return ("" if not text or text.startswith("0001") else text[:10]), ""
    if kind == "number":
        return ("" if raw in (None, "") else str(raw)), ""
    if kind == "bool":
        return ("true" if raw else ""), ""
    return str(raw or ""), ""


def _number_of(row: dict[str, Any]) -> str:
    return str(row.get("Number") or row.get("РегистрационныйНомер") or row.get("Code") or "").strip()


def _date_of(row: dict[str, Any]) -> str:
    text = str(row.get("Date") or row.get("ДатаРегистрации") or "")
    return "" if text.startswith("0001") else text


def _doc_label(kind_id: str, row: dict[str, Any]) -> str:
    number = _number_of(row)
    date = _date_of(row)[:10]
    day = f"{date[8:10]}.{date[5:7]}.{date[0:4]}" if len(date) == 10 else ""
    return f"{KINDS[kind_id]['title']}" + (f" № {number}" if number else "") + (f" от {day}" if day else "")


def _load(kind_id: str, ref_key: str, args: dict[str, Any]) -> tuple[dict[str, Any], _ODataClient, dict[str, Any]]:
    kind = _kind(kind_id)
    if not _GUID_RE.match(ref_key or ""):
        raise DocumentCreateError("У документа нет ссылки 1С")
    client = dc._client(kind, args)
    rows = client.get(kind["entity"], ref_key=ref_key)
    if not rows:
        raise DocumentCreateError("Документ в 1С не найден — возможно, удалён")
    return kind, client, rows[0]


def _files_of(client: _ODataClient, kind_id: str, ref_key: str) -> list[dict[str, str]]:
    entity = FILE_CATALOGS.get(kind_id)
    if not entity:
        return []
    try:
        rows = client.get(
            entity, filt=f"ВладелецФайла_Key eq guid'{ref_key}' and DeletionMark eq false", top=50
        )
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "id": str(row.get("Ref_Key") or ""),
            "name": str(row.get("Description") or ""),
            "extension": str(row.get("Расширение") or ""),
            "size": str(row.get("Размер") or ""),
        }
        for row in rows
        if _GUID_RE.match(str(row.get("Ref_Key") or ""))
    ]


def _basis_of(row: dict[str, Any], client: _ODataClient) -> str:
    for link_field in ("ДокументОснование", "Основание"):
        type_name = str(row.get(f"{link_field}_Type") or "")
        ref = str(row.get(link_field) or "")
        if not type_name.startswith(f"{_ODATA_PREFIX}Document_") or not _GUID_RE.match(ref):
            continue
        entity = type_name[len(_ODATA_PREFIX):]
        kind_id = next((key for key, kind in KINDS.items() if kind["entity"] == entity), "")
        if not kind_id:
            return entity.replace("Document_", "")
        try:
            rows = client.get(entity, ref_key=ref)
        except Exception:  # noqa: BLE001
            rows = []
        return _doc_label(kind_id, rows[0]) if rows else KINDS[kind_id]["title"]
    return ""


def read_document(kind_id: str, ref_key: str, args: dict[str, Any]) -> dict[str, Any]:
    kind, client, row = _load(kind_id, ref_key, args)
    names = _Names(client)
    values: dict[str, str] = {}
    keys: dict[str, str] = {}
    props: dict[str, dict[str, Any]] = {}
    if any(field.get("property") for field in edit_fields(kind)):
        for prop in row.get("ДополнительныеРеквизиты") or []:
            name = names(_PROPERTY_CATALOG, prop.get("Свойство_Key")).casefold()
            if name:
                props[name] = prop
    for field in edit_fields(kind):
        if field.get("property"):
            prop = props.get(str(field["property"]).casefold())
            if not prop:
                values[field["key"]] = ""
                continue
            shown, guid = _display({**field, "key": "Значение", "composite": field["type"] == "ref"}, prop, names)
            values[field["key"]], keys_value = shown, guid
            if keys_value:
                keys[field["key"]] = keys_value
            continue
        shown, guid = _display(field, row, names)
        values[field["key"]] = shown
        if guid:
            keys[field["key"]] = guid
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in kind.get("tables") or []:
        out_rows = []
        for line in row.get(table["key"]) or []:
            item: dict[str, Any] = {"__keys": {}}
            for column in table["columns"]:
                shown, guid = _display(column, line, names)
                item[column["key"]] = shown
                if guid:
                    item["__keys"][column["key"]] = guid
            out_rows.append(item)
        tables[table["key"]] = out_rows
    posted = bool(row.get("Posted"))
    deleted = bool(row.get("DeletionMark"))
    reason = ""
    if deleted:
        reason = "Документ помечен на удаление — изменить его можно только в 1С."
    elif posted:
        reason = (
            "Документ проведён. Изменение проведённого документа перепроводит его и может запустить "
            "согласование, поэтому правки — в 1С. Здесь доступны «Создать на основании», копия и файлы."
        )
    return {
        "ok": True,
        "summary": _doc_label(kind_id, row),
        "kind": kind_id,
        "ref_key": ref_key,
        "number": _number_of(row),
        "date": _date_of(row),
        "status": str(row.get("Статус") or row.get("ТД_Статус") or ""),
        "posted": posted,
        "deleted": deleted,
        "editable": not posted and not deleted,
        "readonly_reason": reason,
        "values": values,
        "keys": keys,
        "tables": tables,
        "files": _files_of(client, kind_id, ref_key),
        "basis_label": _basis_of(row, client),
        "web_url": _web_url(kind, ref_key),
    }


def _cleared(field: dict[str, Any]) -> dict[str, Any]:
    key = field["key"]
    kind = field["type"]
    if kind == "ref":
        out: dict[str, Any] = {key: "", f"{key}_Type": UNDEFINED_TYPE} if field.get("composite") else {key: EMPTY_GUID}
    elif kind == "date":
        out = {key: _EMPTY_DATE}
    elif kind == "number":
        out = {key: 0}
    elif kind == "bool":
        out = {key: False}
    else:
        out = {key: ""}
        if field.get("composite"):
            out[f"{key}_Type"] = STRING_TYPE
    if field.get("mirror"):
        out[field["mirror"]] = out[key] if kind != "ref" or not field.get("composite") else EMPTY_GUID
    return out


def _merge_properties(
    client: _ODataClient, existing: list[dict[str, Any]], changed: list[tuple[str, Any, dict[str, Any]]]
) -> list[dict[str, Any]]:
    fresh = _property_rows(client, changed)
    replaced = {row["Свойство_Key"] for row in fresh}
    kept = [
        {k: v for k, v in row.items() if k not in {"Ref_Key", "LineNumber"} and "@" not in k}
        for row in existing
        if row.get("Свойство_Key") not in replaced
    ]
    merged = kept + [{k: v for k, v in row.items() if k != "LineNumber"} for row in fresh]
    for index, row in enumerate(merged, start=1):
        row["LineNumber"] = str(index)
    return merged


def post_document(kind_id: str, ref_key: str, args: dict[str, Any]) -> dict[str, Any]:
    """Провести уже записанный документ ERP. Маршрут согласования не запускается."""
    kind, client, row = _load(kind_id, ref_key, args)
    if kind["base"] != "erp":
        raise DocumentCreateError("Этот документ не проводится из формы: отправьте его на согласование в 1С")
    if row.get("DeletionMark"):
        raise DocumentCreateError("Документ помечен на удаление — провести его можно только в 1С")
    number = _number_of(row)
    label = _doc_label(kind_id, row)
    if row.get("Posted"):
        return {
            "ok": True,
            "posted": True,
            "summary": f"{label} уже проведён",
            "ref_key": ref_key,
            "number": number,
        }
    client.patch(kind["entity"], ref_key, {"Posted": True})
    again = client.get(kind["entity"], ref_key=ref_key)
    if not again or not again[0].get("Posted"):
        raise DocumentCreateError(f"1С не провела {label} — проведите документ в 1С")
    return {
        "ok": True,
        "posted": True,
        "summary": f"{label} проведён в 1С",
        "ref_key": ref_key,
        "number": number,
    }


def update_document(kind_id: str, ref_key: str, args: dict[str, Any], *, actor_fio: str) -> dict[str, Any]:
    files = _decode_files(args.get("files"))
    if files and kind_id not in FILE_CATALOGS:
        raise DocumentCreateError("К этому виду документа файлы прикрепляются в самой 1С")
    ensure_probe(kind_id, args, actor_fio=actor_fio, files=bool(files), update=True)
    kind, client, row = _load(kind_id, ref_key, args)
    if row.get("DeletionMark"):
        raise DocumentCreateError("Документ помечен на удаление — изменить его можно только в 1С")
    if row.get("Posted"):
        raise DocumentCreateError(
            "Документ проведён — изменить его можно только в 1С: запись перепроведёт документ "
            "и может запустить согласование"
        )
    values = args.get("values") if isinstance(args.get("values"), dict) else {}
    changed = {str(item) for item in args.get("changed") or []}
    tables_in = args.get("tables") if isinstance(args.get("tables"), dict) else {}
    body: dict[str, Any] = {}
    properties: list[tuple[str, Any, dict[str, Any]]] = []
    missing: list[str] = []
    for field in edit_fields(kind):
        key = field["key"]
        if key not in changed:
            continue
        raw = values.get(key)
        if not str(raw if raw is not None else "").strip():
            if field.get("required"):
                missing.append(field["label"])
            elif not field.get("property"):
                body.update(_cleared(field))
            continue
        value = _convert(client, field, raw)
        if field.get("property"):
            properties.append((field["property"], value, field))
            continue
        put_value(body, field, value)
    if missing:
        raise DocumentCreateError("Заполните обязательные поля: " + ", ".join(missing))
    for table in kind.get("tables") or []:
        if table["key"] in changed:
            body[table["key"]] = _table_rows(client, table, tables_in.get(table["key"]) or [])
    if properties:
        body["ДополнительныеРеквизиты"] = _merge_properties(
            client, row.get("ДополнительныеРеквизиты") or [], properties
        )
    if kind_id == "payment" and "ЖелательнаяДатаПлатежа" in body:
        body["ДатаПлатежа"] = body["ЖелательнаяДатаПлатежа"]
    if kind_id == "payment" and "ФормаОплатыЗаявки" in body:
        body["ФормаОплатыБезналичная"] = body["ФормаОплатыЗаявки"] == "Безналичная"
        body["ФормаОплатыНаличная"] = body["ФормаОплатыЗаявки"] == "Наличная"
    if not body and not files:
        return {"ok": True, "summary": "Изменений нет", "ref_key": ref_key, "number": row.get("Number", "")}
    if body:
        client.patch(kind["entity"], ref_key, body)
    file_result: dict[str, Any] = {"attached": [], "failed": []}
    if files:
        file_result = attach_files(kind_id, ref_key, files, args=args, actor_fio=actor_fio)
    label = _doc_label(kind_id, row)
    return {
        "ok": True,
        "summary": (f"{label}: изменения записаны в 1С" if body else label) + files_summary(file_result),
        "kind": kind_id,
        "ref_key": ref_key,
        "number": _number_of(row),
        "changed": sorted(changed & {*(f["key"] for f in edit_fields(kind)), *(t["key"] for t in kind.get("tables") or [])}),
        **file_result,
    }


def attach_to_document(kind_id: str, ref_key: str, args: dict[str, Any], *, actor_fio: str) -> dict[str, Any]:
    """Файлы не меняют сам документ — их можно добавить и к проведённому, как в 1С."""
    files = _decode_files(args.get("files"))
    if not files:
        raise DocumentCreateError("Выберите файлы")
    ensure_probe(kind_id, args, actor_fio=actor_fio, files=True)
    _, _, row = _load(kind_id, ref_key, args)
    if row.get("DeletionMark"):
        raise DocumentCreateError("Документ помечен на удаление")
    result = attach_files(kind_id, ref_key, files, args=args, actor_fio=actor_fio)
    return {
        "ok": bool(result["attached"]),
        "summary": _doc_label(kind_id, row) + files_summary(result),
        "ref_key": ref_key,
        **result,
    }


def basis_values(
    source: str, ref_key: str, target: str, args: dict[str, Any], *, actor_fio: str
) -> dict[str, Any]:
    del actor_fio
    if target not in BASIS_TARGETS.get(source, []):
        raise DocumentCreateError(f"Из «{_kind(source)['title']}» нельзя создать «{_kind(target)['title']}»")
    src = read_document(source, ref_key, args)
    source_values: dict[str, str] = src["values"]
    source_keys: dict[str, str] = src["keys"]
    target_kind = _kind(target)
    label = _doc_label(source, {"Number": src["number"], "Date": src["date"]})
    values: dict[str, str] = {}
    keys: dict[str, str] = {}
    target_keys = {field["key"] for field in target_kind["fields"]}
    for field in target_kind["fields"]:
        key = field["key"]
        if field.get("default") == "me":
            continue
        shown = source_values.get(key, "")
        if shown:
            values[key] = shown
            if key in source_keys:
                keys[key] = source_keys[key]
    tables: dict[str, list[dict[str, Any]]] = {}
    if source == target:
        tables = {key: rows for key, rows in src["tables"].items()}
    else:
        theme = source_values.get(THEME_KEY.get(source, ""), "")
        theme_key = THEME_KEY.get(target, "")
        if theme and theme_key in target_keys and not values.get(theme_key):
            prefix = "Ответ: " if source == "incoming" and target == "outgoing" else ""
            values[theme_key] = prefix + theme
        text = source_values.get(TEXT_KEY.get(source, ""), "")
        text_key = TEXT_KEY.get(target, "")
        if text and text_key in target_keys and not values.get(text_key):
            values[text_key] = text
        if source == "incoming" and target == "outgoing":
            partner = source_values.get("Партнер", "")
            if partner:
                values["Партнер_Key"] = partner
                if source_keys.get("Партнер"):
                    keys["Партнер_Key"] = source_keys["Партнер"]
            values["НомерВходящий"] = source_values.get("НомерИсходящий") or src["number"]
            values["ДатаВходящая"] = source_values.get("ДатаИсходящая") or src["date"][:10]
            if source_values.get("EmailОтправителяПисьма"):
                values["EmailПолучателяПисьма"] = source_values["EmailОтправителяПисьма"]
        if target == "assignment":
            values["Основание"] = label
        if "Комментарий" in target_keys and not values.get("Комментарий"):
            values["Комментарий"] = f"Основание: {label}"
    link = None
    if source != target and target in BASIS_LINK and source in BASIS_LINK[target][1]:
        link = {"kind": source, "ref_key": ref_key}
    return {
        "ok": True,
        "summary": f"{_kind(target)['title']} на основании: {label}" if source != target else f"Копия: {label}",
        "target": target,
        "values": values,
        "keys": keys,
        "tables": tables,
        "basis": link,
        "basis_label": label if source != target else "",
        "copied_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


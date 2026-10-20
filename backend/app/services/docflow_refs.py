"""Наименования ссылок для табличных частей 1С.

В $expand 1С отдаёт навигации только для реквизитов самого документа: строки
табличных частей приходят с одними GUID. Здесь они пакетами превращаются в
читаемые названия.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_CHUNK = 25
_names: dict[tuple[str, str], str] = {}


def is_ref(value: Any) -> bool:
    text = str(value or "")
    return bool(_GUID_RE.match(text)) and text != _EMPTY_GUID


def entity_of(row: dict[str, Any], field: str) -> str:
    """Составные ссылки несут тип в соседнем поле «<Реквизит>_Type»."""
    raw = str(row.get(f"{field}_Type") or "").strip()
    name = raw.replace("StandardODATA.", "")
    return "" if name in {"", "Undefined", "Edm.String"} else name


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        logger.warning("ref names lookup failed: %s", str(exc)[:200])
        return {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return data if isinstance(data, dict) else {}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return "" if text.startswith("0001-01-01T00:00:00") or text == _EMPTY_GUID else text


def _document_label(row: dict[str, Any]) -> str:
    number, date = _clean(row.get("Number")), _clean(row.get("Date"))[:10]
    if number and date:
        return f"№ {number} от {date}"
    return number or date


def resolve(refs: dict[str, set[str]]) -> None:
    """Догружает названия для {сущность: {guid, ...}} в кеш процесса."""
    for entity, keys in refs.items():
        if not entity:
            continue
        documents = entity.startswith("Document_")
        select = "Ref_Key,Number,Date" if documents else "Ref_Key,Description"
        missing = sorted(key for key in keys if is_ref(key) and (entity, key) not in _names)
        for index in range(0, len(missing), _CHUNK):
            chunk = missing[index : index + _CHUNK]
            filt = quote(" or ".join(f"Ref_Key eq guid'{key}'" for key in chunk), safe="=,'():")
            data = _odata(f"{entity}?$format=json&$top={len(chunk)}&$filter={filt}&$select={select}")
            for row in data.get("value") or []:
                if not isinstance(row, dict):
                    continue
                key = _clean(row.get("Ref_Key"))
                label = _document_label(row) if documents else _clean(row.get("Description"))
                if key:
                    _names[(entity, key)] = label
            for key in chunk:
                _names.setdefault((entity, key), "")


def name(entity: str, key: Any) -> str:
    return _names.get((entity, str(key or "")), "")


def typed_name(row: dict[str, Any], field: str) -> str:
    """Название для составной ссылки: тип берётся из «<Реквизит>_Type» той же строки."""
    entity = entity_of(row, field)
    value = row.get(field)
    if not entity:
        return _clean(value) if not is_ref(value) else ""
    return name(entity, value) or _clean(value)

"""CSV: 2000 incoming-correspondence rows with department, sender, subject, text."""

from __future__ import annotations

import csv
import re
import sys

from app.clients.erp_sql import get_user_profile_by_fio
from app.services.onec_tools import _odata_get

TARGET = 2000
PAGE = 200
START_SKIP = 98000
OUT = r"c:\Users\mdj\Desktop\конструктор\входящие_2000.csv"
ENTITY = "Document_ТД_ВходящаяКорреспонденция"
EMPTY = "00000000-0000-0000-0000-000000000000"
_TAG = re.compile(r"<[^>]+>")

_dept_names: dict[str, str] = {}
_user_names: dict[str, str] = {}
_user_depts: dict[str, str] = {}


def _guid(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == EMPTY:
        return ""
    return text


def _text(value: object) -> str:
    raw = str(value or "")
    if "<" in raw and ">" in raw:
        raw = _TAG.sub(" ", raw)
    return " ".join(raw.replace("\xa0", " ").split())


def _description(entity: str, guid: str) -> str:
    data = _odata_get({"path": f"{entity}(guid'{guid}')", "select": "Description"})["data"]
    if isinstance(data, dict) and "value" in data:
        rows = data.get("value") or []
        data = rows[0] if rows else {}
    if not isinstance(data, dict):
        return ""
    return _text(data.get("Description") or data.get("Наименование") or "")


def _department_name(guid: str) -> str:
    key = _guid(guid)
    if not key:
        return ""
    cached = _dept_names.get(key.lower())
    if cached is not None:
        return cached
    try:
        name = _description("Catalog_СтруктураПредприятия", key)
    except Exception:
        name = ""
    _dept_names[key.lower()] = name
    return name


def _user_name(guid: str) -> str:
    key = _guid(guid)
    if not key:
        return ""
    cached = _user_names.get(key.lower())
    if cached is not None:
        return cached
    try:
        name = _description("Catalog_Пользователи", key)
    except Exception:
        name = ""
    _user_names[key.lower()] = name
    return name


def _department_of_user(guid: str) -> str:
    key = _guid(guid)
    if not key:
        return ""
    cached = _user_depts.get(key.lower())
    if cached is not None:
        return cached
    name = _user_name(key)
    department = ""
    if name:
        try:
            department = _text(get_user_profile_by_fio(name).department)
        except Exception:
            department = ""
    _user_depts[key.lower()] = department
    return department


def _final_executor_id(row: dict) -> str:
    executors = row.get("CRM_Исполнители") or []
    if isinstance(executors, list) and executors:
        last = executors[-1] or {}
        return _guid(last.get("Исполнитель_Key"))
    return ""


def _department(row: dict) -> str:
    person = _final_executor_id(row)
    if person:
        found = _department_of_user(person)
        if found:
            return found
    for field in ("КомуПодразделениеСсылка_Key", "ПодразделениеИсполнитель_Key"):
        found = _department_name(str(row.get(field) or ""))
        if found:
            return found
    return ""


def _content(row: dict) -> str:
    for field in ("Содержание", "ТекстHTML", "Комментарий"):
        text = _text(row.get(field))
        if text:
            return text
    return ""


def _sender(row: dict) -> str:
    return _text(row.get("EmailОтправителяПисьма") or row.get("Партнер") or "")


def main() -> int:
    written = 0
    seen: set[str] = set()
    with open(OUT, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Отдел", "отправитель", "тема", "содержимое"])
        skip = START_SKIP
        while written < TARGET:
            raw = _odata_get(
                {"path": ENTITY, "top": PAGE, "skip": skip}
            )
            rows = raw["data"].get("value") or []
            if not rows:
                break
            fresh = 0
            for row in rows:
                ref = str(row.get("Ref_Key") or "")
                if not ref or ref in seen or row.get("DeletionMark"):
                    continue
                seen.add(ref)
                fresh += 1
                writer.writerow(
                    [
                        _department(row),
                        _sender(row),
                        _text(row.get("ТемаСлужебнойЗаписки")),
                        _content(row),
                    ]
                )
                written += 1
                if written >= TARGET:
                    break
            print(f"written={written} skip={skip} fresh={fresh}", flush=True)
            if fresh == 0:
                break
            skip += PAGE
    print(f"done written={written}", flush=True)
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())

"""Кто сейчас занимает должность в подразделении: срез кадровой истории 1С.

Источник — InformationRegister_КадроваяИсторияСотрудников, виртуальная таблица
SliceLast на дату запроса. Подразделение берётся из Catalog_ПодразделенияОрганизаций,
должность — из Catalog_Должности, ФИО — из Catalog_Сотрудники.
Срез по должности возвращает и тех, кто уже ушёл с неё: у каждого дополнительно
проверяется его собственный последний кадровый приказ. Отпуск по уходу за ребёнком
берётся из InformationRegister_ДанныеСостоянийСотрудников: на время такого отпуска
ставка освобождается. Уволенные, неподтверждённые, с истёкшим «ДействуетДо» и
архивные карточки не возвращаются.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

EMPTY_KEY = "00000000-0000-0000-0000-000000000000"
EMPTY_DATE = "0001-01-01"
POSITIONS = "Catalog_Должности"
DEPARTMENTS = "Catalog_ПодразделенияОрганизаций"
EMPLOYEES = "Catalog_Сотрудники"
HR_RECORD = "InformationRegister_КадроваяИсторияСотрудников_RecordType"
STATES = "InformationRegister_ДанныеСостоянийСотрудников_RecordType"
CHILDCARE_LEAVE = "отпускпоуходузаребенком"
PAGE = 200
SEARCH_LIMIT = 400
QUERY_LIMIT = 6
MAX_PAIRS = 6
FAMILY_POSITION_LIMIT = 20
FAMILY_PAIR_LIMIT = 40
_CATEGORY_TAIL = re.compile(
    r"(?:\s+\d+(?:\s+й)?|\s+(?:первой|второй|третьей|четвертой|пятой|высшей))\s+категори[яи]$"
)
_CATEGORY_RAW = re.compile(
    r"\s+(?:\d+|первой|второй|третьей|четвертой|пятой|высшей)(?:\s*[-–]?\s*й)?\s+категори[яи]\s*$",
    re.IGNORECASE,
)
SLICE_LIMIT = 1000
CANDIDATES_SHOWN = 12
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class StaffSource(Protocol):
    def search(self, entity: str, text: str) -> list[dict[str, Any]]: ...

    def slice_last(
        self,
        period: str,
        position_key: str,
        department_key: str,
    ) -> tuple[list[dict[str, Any]], bool]: ...

    def employees(self, keys: list[str]) -> dict[str, dict[str, Any]]: ...

    def employee_slice(self, period: str, employee_keys: list[str]) -> dict[str, dict[str, Any]]: ...

    def employee_states(self, employee_keys: list[str], as_of: str) -> dict[str, list[dict[str, Any]]]: ...

    def get(self, entity: str, ref_key: str) -> dict[str, Any] | None: ...


def normalize_name(value: str | None) -> str:
    text = (value or "").lower().replace("ё", "е")
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


def leaf_name(value: str) -> str:
    parts = [part.strip() for part in (value or "").split("/") if part.strip()]
    return parts[-1] if parts else (value or "").strip()


def catalog_filter(text: str) -> str:
    escaped = text.replace("'", "''")
    return f"substringof('{escaped}', Description) and DeletionMark eq false"


def slice_url(base: str, period: str, condition: str, *, top: int, skip: int) -> str:
    argument = condition.replace("'", "''")
    return (
        f"{base.rstrip('/')}/{HR_RECORD}/SliceLast"
        f"(Period=datetime'{period}',Condition='{argument}')"
        f"?$format=json&$top={top}&$skip={skip}"
    )


def holds_queried_post(
    latest: dict[str, Any],
    position_key: str,
    department_key: str,
    as_of: str,
) -> bool:
    """Последний приказ сотрудника — всё ещё эта должность в этом подразделении."""
    if not is_current_assignment(latest, as_of):
        return False
    return (
        str(latest.get("Должность_Key") or "").strip().casefold() == position_key.casefold()
        and str(latest.get("Подразделение_Key") or "").strip().casefold() == department_key.casefold()
    )


def on_childcare_leave(states: list[dict[str, Any]], as_of: str) -> bool:
    """Актуальный интервал состояния — отпуск по уходу за ребёнком.

    В регистре предыдущие интервалы часто остаются с пустой датой окончания.
    Действующим считается интервал с самой поздней датой начала, который покрывает as_of.
    """
    covering: list[tuple[str, str]] = []
    for row in states:
        if row.get("Сторно") or row.get("Active") is False:
            continue
        start = str(row.get("Начало") or "")[:10]
        end = str(row.get("Окончание") or "")
        if not start or start > as_of:
            continue
        if end and not end.startswith(EMPTY_DATE) and end[:10] < as_of:
            continue
        covering.append((start, str(row.get("Состояние") or "")))
    if not covering:
        return False
    return normalize_name(max(covering)[1]) == CHILDCARE_LEAVE


def is_current_assignment(row: dict[str, Any], as_of: str) -> bool:
    event = normalize_name(str(row.get("ВидСобытия") or ""))
    if "увольн" in event or event == "неподтвержденныеданные":
        return False
    until = str(row.get("ДействуетДо") or "")
    if until and not until.startswith(EMPTY_DATE) and until[:10] < as_of:
        return False
    rates = _rates(row.get("КоличествоСтавок"))
    if rates is not None and rates <= 0:
        return False
    employee_key = str(row.get("Сотрудник_Key") or "").strip()
    return bool(employee_key) and employee_key != EMPTY_KEY


def select_named(rows: list[dict[str, Any]], query: str) -> tuple[str, list[dict[str, Any]], int]:
    """exact/partial — можно запрашивать людей; ambiguous/empty — нет."""
    needle = normalize_name(leaf_name(query))
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("Ref_Key") or "").strip()
        if not key or key in seen or row.get("DeletionMark"):
            continue
        name = normalize_name(str(row.get("Description") or ""))
        if not name:
            continue
        seen.add(key)
        if name == needle:
            exact.append(row)
        elif needle in name:
            partial.append(row)
    chosen = exact or partial
    kind = "exact" if exact else ("partial" if partial else "empty")
    if kind != "empty" and len(chosen) > QUERY_LIMIT:
        return "ambiguous", chosen[:CANDIDATES_SHOWN], len(chosen)
    return kind, chosen, len(chosen)


def position_base(value: str | None) -> str:
    """Название должности без «1 категории», «2-й категории» и т.п."""
    return _CATEGORY_TAIL.sub("", normalize_name(leaf_name(value or ""))).strip()


def position_search_text(value: str) -> str:
    text = _CATEGORY_RAW.sub("", leaf_name(value)).strip()
    return text or leaf_name(value)


def select_positions(rows: list[dict[str, Any]], query: str) -> tuple[str, list[dict[str, Any]], int]:
    """Категория не различает должности: «инженер» и «инженер 2 категории» — одна семья."""
    needle = position_base(query)
    if len(needle) < 2:
        return select_named(rows, query)
    family: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("Ref_Key") or "").strip()
        if not key or key in seen or row.get("DeletionMark"):
            continue
        if position_base(str(row.get("Description") or "")) != needle:
            continue
        seen.add(key)
        family.append(row)
    if not family:
        return select_named(rows, query)
    if len(family) > FAMILY_POSITION_LIMIT:
        return "ambiguous", family[:CANDIDATES_SHOWN], len(family)
    return "family", family, len(family)


def invoke_position_holders(
    args: dict[str, Any] | None = None,
    source: StaffSource | None = None,
) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    position = str(payload.get("position") or payload.get("должность") or "").strip()
    department = str(payload.get("department") or payload.get("подразделение") or "").strip()
    if not position or not department:
        raise ValueError("Укажите должность и подразделение.")
    if len(normalize_name(leaf_name(position))) < 2 or len(normalize_name(leaf_name(department))) < 2:
        raise ValueError("Укажите должность и подразделение как в 1С, не короче двух букв.")
    as_of = _as_of(payload.get("as_of"))
    staff = source or ODataStaffSource()

    position_rows = staff.search(POSITIONS, position_search_text(position))
    department_rows = staff.search(DEPARTMENTS, leaf_name(department))
    position_kind, positions, position_total = select_positions(position_rows, position)
    department_kind, departments, department_total = select_named(department_rows, department)
    departments = _narrow_departments(staff, departments, department)

    result = _envelope(position, department, as_of)
    result["position_matches"] = [_ref(row) for row in positions]
    result["department_matches"] = [
        {**_ref(row), "path": _department_path(staff, row)} for row in departments
    ]
    if position_kind == "ambiguous":
        result["position_matches"] = [_ref(row) for row in positions]
        result["message"] = _ambiguous_message("должность", position, position_total, positions)
    if department_kind == "ambiguous":
        result["message"] = _join_messages(
            result["message"],
            _ambiguous_message("подразделение", department, department_total, departments),
        )
    if position_kind == "empty" or department_kind == "empty":
        result["status"] = "not_found"
        result["message"] = _not_found_message(position, department, position_kind, department_kind)
        result["position_matches"] = [] if position_kind == "empty" else result["position_matches"]
        result["department_matches"] = [] if department_kind == "empty" else result["department_matches"]
        return result
    if position_kind == "ambiguous" or department_kind == "ambiguous":
        result["status"] = "ambiguous"
        return result
    pair_limit = FAMILY_PAIR_LIMIT if position_kind == "family" else MAX_PAIRS
    if len(positions) * len(departments) > pair_limit:
        result["status"] = "ambiguous"
        result["message"] = (
            "Слишком много сочетаний должности и подразделения. "
            "Уточните название, можно с путём через « / »."
        )
        return result

    groups: list[dict[str, Any]] = []
    period = f"{as_of}T23:59:59"
    for position_row in positions:
        for department_row in departments:
            groups.append(
                _group(staff, position_row, department_row, period=period, as_of=as_of)
            )
    people = [person for group in groups for person in group["people"]]
    people.sort(key=lambda item: (item["fio"].casefold(), item["code"], item["position"].casefold()))
    filled = [group for group in groups if group["count"]]
    result["groups"] = filled or groups
    result["people"] = people
    result["count"] = len(people)
    result["status"] = "found" if people else "empty"
    result["message"] = _found_message(position, department, groups, len(people))
    inactive = sum(int(group.get("inactive_skipped") or 0) for group in groups)
    if inactive:
        result["inactive_skipped"] = inactive
        if result["status"] == "empty":
            result["message"] += " В срезе есть только архивные карточки сотрудников."
    return result



def _odata_payload(path: str) -> Any:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        result = _odata_get({"path": path})
    except OnecToolError:
        raise
    except Exception as exc:
        raise OnecToolError(str(exc)) from exc
    return result.get("data") if isinstance(result, dict) else result


class ODataStaffSource:
    """Кадровая история 1С через OData оркестратора."""

    def __init__(self) -> None:
        self._cards: dict[tuple[str, str], dict[str, Any] | None] = {}

    def search(self, entity: str, text: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for variant in _search_variants(text):
            skip = 0
            filt = catalog_filter(variant)
            while skip < SEARCH_LIMIT:
                path = (
                    f"{entity}?$format=json&$filter={filt}&$top={PAGE}&$skip={skip}"
                )
                batch = _rows(_odata_payload(path))
                for row in batch:
                    key = str(row.get("Ref_Key") or "").strip()
                    if key:
                        found[key] = row
                        self._cards[(entity, key)] = row
                if len(batch) < PAGE:
                    break
                skip += PAGE
            if found:
                break
        return list(found.values())

    def slice_last(
        self,
        period: str,
        position_key: str,
        department_key: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        _require_guid(position_key)
        _require_guid(department_key)
        condition = (
            f"Должность_Key eq guid'{position_key}' and "
            f"Подразделение_Key eq guid'{department_key}'"
        )
        rows: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        skip = 0
        while len(rows) < SLICE_LIMIT:
            url = slice_url("http://odata.local", period, condition, top=PAGE, skip=skip)
            path = url.split("http://odata.local/", 1)[1]
            batch = _rows(_odata_payload(path))
            fresh = 0
            for row in batch:
                ident = (
                    row.get("Сотрудник_Key"),
                    row.get("Period"),
                    row.get("LineNumber"),
                    row.get("ВидСобытия"),
                )
                if ident in seen:
                    continue
                seen.add(ident)
                rows.append(row)
                fresh += 1
            if not batch or fresh == 0 or len(batch) < PAGE:
                return rows[:SLICE_LIMIT], False
            skip += len(batch)
        return rows[:SLICE_LIMIT], True

    def employees(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        unique = [key for key in dict.fromkeys(keys) if _GUID.match(key)]
        loaded: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(unique), 8):
            chunk = unique[offset : offset + 8]
            filt = " or ".join(f"Ref_Key eq guid'{key}'" for key in chunk)
            path = f"{EMPLOYEES}?$format=json&$filter={filt}&$top={len(chunk)}"
            for row in _rows(_odata_payload(path)):
                key = str(row.get("Ref_Key") or "").strip()
                if key:
                    loaded[key] = row
        return loaded

    def employee_slice(self, period: str, employee_keys: list[str]) -> dict[str, dict[str, Any]]:
        unique = [key for key in dict.fromkeys(employee_keys) if _GUID.match(key)]
        if not unique:
            return {}
        loaded: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(unique), 8):
            chunk = unique[offset : offset + 8]
            condition = " or ".join(f"Сотрудник_Key eq guid'{key}'" for key in chunk)
            url = slice_url("http://odata.local", period, condition, top=PAGE, skip=0)
            path = url.split("http://odata.local/", 1)[1]
            for row in _rows(_odata_payload(path)):
                key = str(row.get("Сотрудник_Key") or "").strip()
                if not key:
                    continue
                previous = loaded.get(key)
                if previous is None or str(row.get("Period") or "") >= str(previous.get("Period") or ""):
                    loaded[key] = row
        for key in [item for item in unique if item not in loaded]:
            url = slice_url(
                "http://odata.local",
                period,
                f"Сотрудник_Key eq guid'{key}'",
                top=5,
                skip=0,
            )
            path = url.split("http://odata.local/", 1)[1]
            rows = _rows(_odata_payload(path))
            if rows:
                loaded[key] = max(rows, key=lambda row: str(row.get("Period") or ""))
        return loaded

    def employee_states(self, employee_keys: list[str], as_of: str) -> dict[str, list[dict[str, Any]]]:
        from urllib.parse import quote

        from app.services.onec_tools import OnecToolError

        unique = [key for key in dict.fromkeys(employee_keys) if _GUID.match(key)]
        if not unique:
            return {}
        loaded: dict[str, list[dict[str, Any]]] = {}
        for key in unique:
            filt = quote(
                f"Сотрудник_Key eq guid'{key}' and Начало le datetime'{as_of}T23:59:59'",
                safe="=,' ",
            )
            ordered = f"{STATES}?$format=json&$top=20&$orderby=Начало desc&$filter={filt}"
            plain = f"{STATES}?$format=json&$top=40&$filter={filt}"
            try:
                loaded[key] = _rows(_odata_payload(ordered))
            except OnecToolError:
                loaded[key] = _rows(_odata_payload(plain))
        return loaded

    def get(self, entity: str, ref_key: str) -> dict[str, Any] | None:
        from app.services.onec_tools import OnecToolError

        if not _GUID.match(ref_key or ""):
            return None
        cache_key = (entity, ref_key)
        if cache_key in self._cards:
            return self._cards[cache_key]
        path = f"{entity}(guid'{ref_key}')?$format=json"
        try:
            batch = _rows(_odata_payload(path))
        except (OnecToolError, ValueError):
            self._cards[cache_key] = None
            return None
        row = batch[0] if batch else None
        self._cards[cache_key] = row
        return row


def _group(
    source: StaffSource,
    position_row: dict[str, Any],
    department_row: dict[str, Any],
    *,
    period: str,
    as_of: str,
) -> dict[str, Any]:
    position_key = str(position_row.get("Ref_Key") or "")
    department_key = str(department_row.get("Ref_Key") or "")
    assignments, truncated = source.slice_last(period, position_key, department_key)
    current = [row for row in assignments if is_current_assignment(row, as_of)]
    employee_keys = [str(row.get("Сотрудник_Key") or "") for row in current]
    latest_by_employee = source.employee_slice(period, employee_keys)
    states = source.employee_states(employee_keys, as_of)
    still_here: list[dict[str, Any]] = []
    left = 0
    on_leave = 0
    for row in current:
        employee_key = str(row.get("Сотрудник_Key") or "").strip()
        latest = latest_by_employee.get(employee_key)
        if latest is None or not holds_queried_post(latest, position_key, department_key, as_of):
            left += 1
            continue
        if on_childcare_leave(states.get(employee_key, []), as_of):
            on_leave += 1
            continue
        still_here.append(latest if str(latest.get("Period") or "") else row)
    cards = source.employees([str(row.get("Сотрудник_Key") or "") for row in still_here])
    people: list[dict[str, Any]] = []
    inactive = 0
    path = _department_path(source, department_row)
    position_name = str(position_row.get("Description") or "").strip()
    department_name = str(department_row.get("Description") or "").strip()
    for row in still_here:
        employee_key = str(row.get("Сотрудник_Key") or "").strip()
        card = cards.get(employee_key) or {}
        if card.get("ВАрхиве") or card.get("DeletionMark"):
            inactive += 1
            continue
        person: dict[str, Any] = {
            "fio": str(card.get("Description") or "").strip(),
            "code": str(card.get("Code") or "").strip(),
            "position": position_name,
            "position_key": position_key,
            "department": department_name,
            "department_key": department_key,
            "department_path": path,
            "since": str(row.get("Period") or "")[:10],
            "rates": _rates(row.get("КоличествоСтавок")),
            "event": str(row.get("ВидСобытия") or "").strip(),
            "employee_key": employee_key,
        }
        if "ЭтоГоловнойСотрудник" in row:
            person["primary"] = bool(row.get("ЭтоГоловнойСотрудник"))
        people.append(person)
    people.sort(key=lambda item: (item["fio"].casefold(), item["code"]))
    group: dict[str, Any] = {
        "position": position_name,
        "position_key": position_key,
        "department": department_name,
        "department_key": department_key,
        "department_path": path,
        "count": len(people),
        "people": people,
    }
    if inactive:
        group["inactive_skipped"] = inactive
    if left:
        group["left_skipped"] = left
    if on_leave:
        group["childcare_leave_skipped"] = on_leave
    if truncated:
        group["truncated"] = True
    return group


def _narrow_departments(
    source: StaffSource,
    rows: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    if "/" not in query or not rows:
        return rows
    wanted = [normalize_name(part) for part in query.split("/") if part.strip()]
    if len(wanted) < 2:
        return rows
    matched: list[dict[str, Any]] = []
    for row in rows:
        path = _department_path(source, row)
        actual = [normalize_name(part) for part in path.split("/") if part.strip()]
        index = 0
        for part in actual:
            if index < len(wanted) and part == wanted[index]:
                index += 1
        if index == len(wanted):
            matched.append(row)
    return matched or rows


def _department_path(source: StaffSource, row: dict[str, Any]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    current: dict[str, Any] | None = row
    while current:
        key = str(current.get("Ref_Key") or "").strip()
        if not key or key in seen:
            break
        seen.add(key)
        name = str(current.get("Description") or "").strip()
        if name:
            parts.append(name)
        parent = str(current.get("Parent_Key") or "").strip()
        if not parent or parent == EMPTY_KEY:
            break
        current = source.get(DEPARTMENTS, parent)
    return " / ".join(reversed(parts))


def _envelope(position: str, department: str, as_of: str) -> dict[str, Any]:
    return {
        "status": "empty",
        "as_of": as_of,
        "position": position,
        "department": department,
        "count": 0,
        "people": [],
        "groups": [],
        "position_matches": [],
        "department_matches": [],
        "message": "",
    }


def _ref(row: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(row.get("Description") or "").strip(),
        "key": str(row.get("Ref_Key") or "").strip(),
    }


def _rates(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_of(value: Any) -> str:
    if value is None or not str(value).strip():
        return datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("Дата as_of должна быть в формате YYYY-MM-DD.") from exc


def _search_variants(text: str) -> list[str]:
    raw = " ".join(text.split())
    folded = raw.replace("ё", "е").replace("Ё", "Е")
    if folded and folded != raw:
        return [raw, folded]
    return [raw] if raw else []


def _require_guid(value: str) -> None:
    if not _GUID.match(value or ""):
        raise ValueError(f"Некорректный ключ 1С: {value}")


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return [row for row in payload["value"] if isinstance(row, dict)]
    if isinstance(payload, dict) and payload.get("Ref_Key"):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _people_word(count: int) -> str:
    rest = abs(count) % 100
    if 11 <= rest <= 14:
        return "сотрудников"
    last = rest % 10
    if last == 1:
        return "сотрудник"
    if 2 <= last <= 4:
        return "сотрудника"
    return "сотрудников"


def _not_found_message(
    position: str,
    department: str,
    position_kind: str,
    department_kind: str,
) -> str:
    missing: list[str] = []
    if position_kind == "empty":
        missing.append(f"должность «{position}»")
    if department_kind == "empty":
        missing.append(f"подразделение «{department}»")
    joined = " и ".join(missing)
    return f"В 1С не найдено: {joined}. Название нужно как в справочнике."


def _ambiguous_message(kind: str, query: str, total: int, rows: list[dict[str, Any]]) -> str:
    names = [str(row.get("Description") or "").strip() for row in rows if row.get("Description")]
    shown = "; ".join(names[:CANDIDATES_SHOWN])
    extra = total - len(names[:CANDIDATES_SHOWN])
    tail = f"; и ещё {extra}" if extra > 0 else ""
    return (
        f"Уточните {kind} «{query}»: найдено {total}. Похожие названия: {shown}{tail}."
    )


def _found_message(
    position: str,
    department: str,
    groups: list[dict[str, Any]],
    count: int,
) -> str:
    if count == 0:
        if len(groups) > 1:
            return f"Сейчас на должности «{position}» в выбранных подразделениях никого нет."
        title = groups[0]["position"] if groups else position
        place = groups[0]["department"] if groups else department
        return f"Сейчас на должности «{title}» в подразделении «{place}» никого нет."
    filled = [group for group in groups if group["count"]]
    places = len({group["department_key"] for group in filled})
    titles = {group["position"] for group in filled}
    if len(titles) > 1:
        if places > 1:
            return (
                f"На должности «{position}» без учёта категории сейчас {count} "
                f"{_people_word(count)} в {places} подразделениях."
            )
        return (
            f"На должности «{position}» без учёта категории в подразделении "
            f"«{filled[0]['department']}» сейчас {count} {_people_word(count)}."
        )
    if places > 1:
        return f"Сейчас {count} {_people_word(count)} в {places} подразделениях."
    chosen = filled[0]
    return (
        f"На должности «{chosen['position']}» в подразделении "
        f"«{chosen['department']}» сейчас {count} {_people_word(count)}."
    )


def _join_messages(left: str, right: str) -> str:
    if left and right:
        return f"{left} {right}"
    return left or right

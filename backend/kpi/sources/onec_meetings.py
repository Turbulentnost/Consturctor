from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.config import settings

THEME_ENTITY = "Catalog_ТД_ТемыСовещаний"
USER_ENTITY = "Catalog_Пользователи"
PROTOCOL_ENTITY = "Document_ТД_Протокол"
EMPTY = "00000000-0000-0000-0000-000000000000"

# Одинаковые серии в справочнике заведены под несколькими названиями.
_NAME_ALIASES = {
    "выпуск продукции эц": "выпуск по заказам эц",
    "еженедельное совещание с одпт": "еженедельное совещание с одп",
    "еженедельное совещание с огэоиху": "еженедельное совещание с опэоиу",
    "еженедельное совещание с орпкк": "еженедельное совещание с оркк",
    "дпи суптл": "дпи суп",
    "дпи отдел продаж": "дпи отделов продаж",
    "тендерная комиссия": "тендерный комитет (регл.)",
    "еженедельное совещание со службой управления персоналом": "совещание со службой персонала",
    "совещание со службой управления персоналом": "совещание со службой персонала",
}

# Строки отчёта 1С «план-факт по совещаниям» для круга Донцовой (август 2026).
_CIRCLE_REPORT_SERIES = {
    "выпуск по заказам эц",
    "выпуск продукции по производству №1",
    "выпуск продукции по производству №2",
    "график отгрузок по производству №1",
    "график отгрузок по производству №2",
    "дпи отделов продаж",
    "дпи суп",
    "дпи юридический отдел",
    "еженедельное совещание по общим вопросам с отделами продаж",
    "еженедельное совещание с бухгалтерией",
    "еженедельное совещание с заместителем директора по перспективным проектам",
    "еженедельное совещание с овэд",
    "еженедельное совещание с одп",
    "еженедельное совещание с опэоиу",
    "еженедельное совещание с оркк",
    "еженедельное совещание с отделом по работе с пао газпром",
    "совещание с техническим директором",
    "совещание с юридическим отделом",
    "совещание со службой персонала",
    "тендерный комитет (регл.)",
    "управление товарными остатками",
    "еженедельное совещание сектором рекламы и pr",
}


def _odata_dt(value: date, *, end: bool = False) -> str:
    stamp = "T23:59:59" if end else "T00:00:00"
    return f"datetime'{value.isoformat()}{stamp}'"


def _parse_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text or text.startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        return None


def _client() -> httpx.Client:
    base = (settings.odata_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("ODATA_BASE_URL не задан")
    return httpx.Client(
        auth=(settings.odata_username, settings.odata_password),
        timeout=settings.odata_timeout_sec or 60,
        verify=False,
        base_url=base + "/",
    )


def _pages(client: httpx.Client, path: str, *, page: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        sep = "&" if "?" in path else "?"
        resp = client.get(f"{path}{sep}$top={page}&$skip={skip}&$format=json")
        if resp.status_code != 200:
            raise RuntimeError(f"{path} {resp.status_code} {resp.text[:400]}")
        chunk = [row for row in (resp.json().get("value") or []) if isinstance(row, dict)]
        rows.extend(chunk)
        if len(chunk) < page:
            break
        skip += page
        if skip > 8000:
            break
    return rows


def find_user_key(client: httpx.Client, fio: str) -> tuple[str, str]:
    safe = fio.replace("'", "''")
    rows = _pages(
        client,
        f"{USER_ENTITY}?$filter=DeletionMark eq false and substringof('{safe}', Description)",
        page=50,
    )
    exact = [row for row in rows if str(row.get("Description") or "").strip() == fio]
    row = (exact or rows)[0] if (exact or rows) else None
    if row is None:
        raise RuntimeError(f"Пользователь 1С не найден: {fio}")
    return str(row["Ref_Key"]), str(row.get("Description") or fio)


def weekdays_from_theme(theme: dict[str, Any]) -> list[int]:
    """1С: День 1=пн … 7=вс."""
    days: list[int] = []
    for row in theme.get("ПовторениеПоДнямНедели") or []:
        if not isinstance(row, dict):
            continue
        try:
            value = int(row.get("День") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 7:
            days.append(value)
    return sorted(set(days))


def count_iso_weekdays(start: date, end: date, weekdays: list[int]) -> int:
    wanted = {int(day) for day in weekdays if 1 <= int(day) <= 7}
    if not wanted or start > end:
        return 0
    total = 0
    cursor = start
    while cursor <= end:
        if cursor.isoweekday() in wanted:
            total += 1
        cursor += timedelta(days=1)
    return total


def plan_count(theme: dict[str, Any], start: date, end: date) -> int:
    """План по карточке расписания (один набор дней недели, без дублей карточек)."""
    if not theme.get("РасписаниеЗадано"):
        return 0
    weekdays = weekdays_from_theme(theme)
    if not weekdays or len(weekdays) >= 5:
        return 0
    return count_iso_weekdays(start, end, weekdays)


def normalize_theme_name(name: str) -> str:
    text = " ".join(str(name or "").replace('"', " ").replace("«", " ").replace("»", " ").split())
    key = text.casefold()
    return _NAME_ALIASES.get(key, key)


def looks_like_weekly_series(name: str) -> bool:
    key = normalize_theme_name(name)
    return key.startswith("еженедельн") or key.startswith("совещание с") or key.startswith(
        "совещание со "
    )


def theme_open_in_period(theme: dict[str, Any], start: date) -> bool:
    closed = _parse_dt(theme.get("ДатаЗакрытияТемы"))
    return closed is None or closed.date() >= start


def plan_from_occurrence_dates(
    dates: list[date],
    start: date,
    end: date,
    name: str = "",
) -> int:
    """План как в отчёте круга: регулярность факта за период.

    1 факт — разовая серия, план 1.
    Один и тот же день недели 2+ раз — еженедельно этот день.
    Второй день один раз при 3–4 фактах — тоже еженедельно (техдиректор, тендер).
    Два разных дня по одному разу — план = число фактов (товарные остатки),
    кроме явных еженеделок: тогда план по дню первого факта (юротдел, перспективные).
    Два повторяющихся дня — берём самый частый (персонал: пн, не пн+ср).
    """
    if not dates:
        return 0
    ordered = sorted(dates)
    by_wd = Counter(item.isoweekday() for item in ordered)
    repeating = [wd for wd, count in by_wd.items() if count >= 2]
    singles = [wd for wd, count in by_wd.items() if count == 1]
    if not repeating:
        key = normalize_theme_name(name)
        if len(ordered) >= 2 and key.startswith("еженедельн"):
            return count_iso_weekdays(start, end, [1])
        if len(ordered) >= 2 and looks_like_weekly_series(name):
            return count_iso_weekdays(start, end, [ordered[0].isoweekday()])
        return len(ordered)
    if len(repeating) >= 2:
        modal = max(by_wd.items(), key=lambda item: (item[1], -item[0]))[0]
        return count_iso_weekdays(start, end, [modal])
    if singles and 3 <= len(ordered) <= 4:
        return count_iso_weekdays(start, end, repeating + singles)
    return count_iso_weekdays(start, end, repeating)


def plan_for_series(
    dates: list[date],
    start: date,
    end: date,
    *,
    name: str = "",
    scheduled_weekdays: list[int] | None = None,
) -> int:
    scheduled = [day for day in (scheduled_weekdays or []) if 1 <= int(day) <= 7]
    if 1 <= len(scheduled) <= 2:
        fact_wd = {item.isoweekday() for item in dates}
        if not fact_wd or fact_wd & set(scheduled):
            return count_iso_weekdays(start, end, scheduled)
    return plan_from_occurrence_dates(dates, start, end, name=name)


def collect_plan_fact(
    *,
    leader_fio: str = "Донцова Анна Егоровна",
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    with _client() as client:
        leader_key, leader_name = find_user_key(client, leader_fio)
        themes = _pages(
            client,
            f"{THEME_ENTITY}?$filter=DeletionMark eq false and Руководитель_Key eq guid'{leader_key}'",
        )
        display_name: dict[str, str] = {}
        schedule_by_name: dict[str, list[int]] = {}
        circle_open: set[str] = set()
        for theme in themes:
            raw = str(theme.get("Description") or "").strip()
            key = normalize_theme_name(raw)
            is_circle = bool(theme.get("ТемаКругаУправления"))
            is_open = theme_open_in_period(theme, date_from)
            if is_circle and is_open:
                circle_open.add(key)
                if key not in display_name:
                    display_name[key] = raw
                weekdays = weekdays_from_theme(theme) if theme.get("РасписаниеЗадано") else []
                if 1 <= len(weekdays) <= 2:
                    schedule_by_name[key] = weekdays

        protocols = _pages(
            client,
            f"{PROTOCOL_ENTITY}?$filter=DeletionMark eq false"
            f" and Руководитель_Key eq guid'{leader_key}'"
            f" and Date ge {_odata_dt(date_from)} and Date le {_odata_dt(date_to, end=True)}"
            "&$expand=ТемаСовещания"
            "&$select=Ref_Key,Number,Date,Posted,Статус,ТемаСовещания_Key,ТемаСовещания",
        )
        dates_by_name: dict[str, list[date]] = defaultdict(list)
        for row in protocols:
            theme = row.get("ТемаСовещания") if isinstance(row.get("ТемаСовещания"), dict) else {}
            raw = str(theme.get("Description") or "").strip()
            key = normalize_theme_name(raw)
            parsed = _parse_dt(row.get("Date"))
            if parsed is None:
                continue
            dates_by_name[key].append(parsed.date())

        rows: list[dict[str, Any]] = []
        for key, occurred in dates_by_name.items():
            if key not in _CIRCLE_REPORT_SERIES:
                continue
            if key not in circle_open and key not in display_name:
                continue
            fact = len(occurred)
            plan = plan_for_series(
                occurred,
                date_from,
                date_to,
                name=display_name.get(key, key),
                scheduled_weekdays=schedule_by_name.get(key),
            )
            if plan == 0 and fact == 0:
                continue
            rows.append(
                {
                    "theme": display_name.get(key, key),
                    "plan": plan,
                    "fact": fact,
                }
            )
        rows.sort(key=lambda item: str(item["theme"]).casefold())
        return {
            "leader": leader_name,
            "leader_key": leader_key,
            "period_from": date_from.isoformat(),
            "period_to": date_to.isoformat(),
            "source": (
                "odata круг управления: Catalog_ТД_ТемыСовещаний.ТемаКругаУправления "
                "+ Document_ТД_Протокол"
            ),
            "rows": rows,
            "totals": {
                "plan": sum(int(row["plan"]) for row in rows),
                "fact": sum(int(row["fact"]) for row in rows),
                "themes": len(rows),
                "protocols": len(protocols),
            },
        }


def format_table(report: dict[str, Any]) -> str:
    lines = [
        f"Руководитель совещания: {report['leader']}",
        f"Период: {report['period_from']} — {report['period_to']}",
        "",
        f"{'Тема совещания':<72} {'план':>5} {'факт':>5}",
        "-" * 84,
    ]
    for row in report["rows"]:
        lines.append(f"{row['theme'][:72]:<72} {row['plan']:>5} {row['fact']:>5}")
    totals = report["totals"]
    lines.append("-" * 84)
    lines.append(f"{'Итого':<72} {totals['plan']:>5} {totals['fact']:>5}")
    return "\n".join(lines)

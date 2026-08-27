from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services import agent_kpi

ILCHENKO_USER_IDS = frozenset(
    {
        "A2DCC949FEDEC70D40318ABA83C618F4",
        "E11C4E11K00000000000000000000001",
    }
)

DAY_SECONDS = 24 * 3600
SIX_HOURS_SECONDS = 6 * 3600

ILCHENKO_SUMMARY = (
    "KPI должности помощника председателя совета директоров: "
    "своевременность пакета и протоколов СД/РК, контроль поручений и качество без возвратов."
)


def is_ilchenko(*, user_id: str = "", fio: str = "") -> bool:
    if (user_id or "").strip() in ILCHENKO_USER_IDS:
        return True
    return "ильченко" in (fio or "").casefold()


def _method(
    *,
    plan_explanation: str,
    fact_explanation: str,
    score_explanation: str,
    system: str,
    how: str,
    when: str,
    plan_update: str,
    fact_update: str,
    percent_formula: str,
    green_min: float,
    yellow_min: float,
    interval_seconds: int,
) -> dict[str, Any]:
    return agent_kpi.normalize_method(
        {
            "plan_explanation": plan_explanation,
            "fact_explanation": fact_explanation,
            "score_explanation": score_explanation,
            "system": system,
            "how": how,
            "when": when,
            "plan_update": plan_update,
            "fact_update": fact_update,
            "percent_formula": percent_formula,
            "green_min": green_min,
            "yellow_min": yellow_min,
            "schedule": {"kind": "interval", "interval_seconds": interval_seconds, "at": ""},
        },
        kind="position",
    )


def _tile(
    *,
    number: int,
    tile_id: str,
    name: str,
    target: float,
    weight: int,
    plan_description: str,
    fact_description: str,
    formula: str,
    method: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": tile_id,
        "name": name,
        "plan": {
            "label": "План",
            "value": target,
            "unit": "%",
            "description": plan_description,
        },
        "fact": {
            "label": "Факт",
            "value": None,
            "unit": "%",
            "description": fact_description,
        },
        "measure": {
            "kind": tile_id,
            "params": {"weight": weight, "number": number, "window_days": 90},
            "formula": formula,
        },
        "score_percent": None,
        "color": "none",
        "updated_at": "",
        "next_run_at": now.isoformat(),
        "evidence": "",
        "method": method,
    }


def ilchenko_tiles(*, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    locked_plan = "Норма должности фиксирована. План не пересчитываем, пока не изменят seed."
    return [
        _tile(
            number=1,
            tile_id="package_on_time",
            name="Своевременность пакета к заседаниям (СД + РК)",
            target=95,
            weight=25,
            plan_description="Не менее 95% заседаний СД и РК с готовым пакетом за рабочий день до начала.",
            fact_description="Доля прошедших заседаний СД/РК, у которых комплект был готов не позже чем за 1 рабочий день до начала.",
            formula="on_time_packages / meetings_with_deadline x 100",
            method=_method(
                plan_explanation=(
                    "План — норма должности: пакет к заседанию совета директоров "
                    "или ревизионной комиссии должен быть готов заранее. Цель 95 процентов. "
                    "Эту норму не меняем автоматически."
                ),
                fact_explanation=(
                    "Смотрим заседания СД и РК за последние 90 дней, у которых уже наступил срок пакета. "
                    "Заседание находим в Outlook по теме (совет директоров, СД, ревизион, РК) "
                    "и в файлах прогонов агентов. Пакет считаем своевременным, если комплект "
                    "материалов появился не позже чем за один рабочий день до начала. "
                    "Если заседаний в окне нет, факт не показываем."
                ),
                score_explanation=(
                    "Оценка совпадает с фактом. Зелёный — факт не ниже 95 процентов, "
                    "жёлтый — не ниже 85, иначе красный."
                ),
                system=(
                    "window=90d. Meetings = Outlook events matching SD/RK plus agent run files. "
                    "on_time = package ready at least 1 business day before meeting start. "
                    "fact = on_time / eligible * 100. score = fact. Do not change plan."
                ),
                how=(
                    "Outlook calendar + agent package/materials artifacts + 1C attachments. "
                    "Eligible = past SD/RK meetings whose package deadline has passed."
                ),
                when="раз в сутки",
                plan_update=locked_plan,
                fact_update="Каждый суточный пересчёт и после прогона агента по пакету.",
                percent_formula="Факт уже в процентах — это и есть KPI.",
                green_min=95,
                yellow_min=85,
                interval_seconds=DAY_SECONDS,
            ),
            now=now,
        ),
        _tile(
            number=2,
            tile_id="protocol_on_time",
            name="Своевременность протоколов (СД + РК)",
            target=95,
            weight=25,
            plan_description="Не менее 95% протоколов СД и РК в течение 5 рабочих дней после заседания.",
            fact_description="Доля заседаний, у которых с окончания прошло не меньше 5 рабочих дней и протокол появился в этот срок.",
            formula="on_time_protocols / meetings_due_for_protocol x 100",
            method=_method(
                plan_explanation=(
                    "План — норма должности: протокол СД или РК должен появиться "
                    "в течение пяти рабочих дней. Цель 95 процентов. Норму не пересчитываем."
                ),
                fact_explanation=(
                    "Берём заседания СД и РК за 90 дней, с окончания которых прошло "
                    "не меньше пяти рабочих дней. Протокол ищем в файлах агентов и в 1С. "
                    "Своевременный — если файл или документ появился не позже пяти рабочих дней. "
                    "Если таких заседаний нет, факт не показываем."
                ),
                score_explanation=(
                    "Оценка совпадает с фактом. Зелёный — не ниже 95 процентов, "
                    "жёлтый — не ниже 85, иначе красный."
                ),
                system=(
                    "window=90d. Eligible = SD/RK meetings ended >= 5 business days ago. "
                    "on_time = protocol artifact/document within 5 business days. "
                    "fact = on_time / eligible * 100. score = fact. Do not change plan."
                ),
                how="Outlook past meetings + agent protocol files + 1C documents.",
                when="раз в сутки",
                plan_update=locked_plan,
                fact_update="Каждый суточный пересчёт.",
                percent_formula="Факт уже в процентах — это и есть KPI.",
                green_min=95,
                yellow_min=85,
                interval_seconds=DAY_SECONDS,
            ),
            now=now,
        ),
        _tile(
            number=3,
            tile_id="instructions",
            name="Реестр и контроль исполнения поручений (СД + РК)",
            target=95,
            weight=25,
            plan_description="Не менее 95% поручений СД и РК закрыты в срок или ещё не просрочены.",
            fact_description="Доля поручений СД/РК в окне, которые закрыты в срок либо ещё не просрочены.",
            formula="(done_on_time + not_overdue) / all_instructions x 100",
            method=_method(
                plan_explanation=(
                    "План — норма контроля поручений СД и РК: 95 процентов позиций реестра "
                    "должны быть в сроке. Норму должности не меняем автоматически."
                ),
                fact_explanation=(
                    "Выгружаем поручения СД и РК из 1С за 90 дней. "
                    "В срок — закрытые не позже due_date и открытые, у которых срок ещё не вышел. "
                    "Если поручений нет, факт не показываем."
                ),
                score_explanation=(
                    "Оценка совпадает с фактом. Зелёный — не ниже 95 процентов, "
                    "жёлтый — не ниже 85, иначе красный."
                ),
                system=(
                    "window=90d. Source = 1C search_tasks / task card, filter SD/RK. "
                    "on_time = closed_on_time or open_and_not_overdue. "
                    "fact = on_time / all * 100. score = fact. Do not change plan."
                ),
                how="1C tasks/instructions for SD and RK, due dates and status.",
                when="каждые 6 часов",
                plan_update=locked_plan,
                fact_update="Каждые 6 часов: реестр меняется чаще пакета.",
                percent_formula="Факт уже в процентах — это и есть KPI.",
                green_min=95,
                yellow_min=85,
                interval_seconds=SIX_HOURS_SECONDS,
            ),
            now=now,
        ),
        _tile(
            number=4,
            tile_id="quality",
            name="Качество протокола и материалов (без возвратов по замечаниям)",
            target=98,
            weight=25,
            plan_description="Не менее 98% сданных пакетов и протоколов без возврата на доработку.",
            fact_description="Доля сданных пакетов и протоколов без статуса возврата или доработки.",
            formula="without_return / submitted x 100",
            method=_method(
                plan_explanation=(
                    "План — норма качества: почти все пакеты и протоколы принимаются "
                    "без возврата. Цель 98 процентов. Норму не пересчитываем."
                ),
                fact_explanation=(
                    "Смотрим сданные пакеты и протоколы за 90 дней. "
                    "Возврат — статус 1С вроде возвращён / на доработке или событие returned "
                    "в прогоне агента. Если сдач нет, факт не показываем."
                ),
                score_explanation=(
                    "Оценка совпадает с фактом. Зелёный — не ниже 98 процентов, "
                    "жёлтый — не ниже 88, иначе красный."
                ),
                system=(
                    "window=90d. submitted = package/protocol submissions. "
                    "return = 1C returned/rework status or agent event type returned. "
                    "fact = (submitted - returned) / submitted * 100. score = fact. "
                    "Do not change plan."
                ),
                how="1C document history and agent run events with type returned.",
                when="раз в сутки",
                plan_update=locked_plan,
                fact_update="Каждый суточный пересчёт.",
                percent_formula="Факт уже в процентах — это и есть KPI.",
                green_min=98,
                yellow_min=88,
                interval_seconds=DAY_SECONDS,
            ),
            now=now,
        ),
    ]

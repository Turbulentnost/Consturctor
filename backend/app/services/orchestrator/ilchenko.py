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

PSD_POSITION_NAME = "Помощник Председателя совета директоров"

ILCHENKO_SUMMARY = (
    "KPI должности помощника председателя совета директоров: "
    "своевременность пакета и протоколов СД/РК, контроль поручений и качество без возвратов."
)


def is_ilchenko(*, user_id: str = "", fio: str = "") -> bool:
    if (user_id or "").strip() in ILCHENKO_USER_IDS:
        return True
    return "ильченко" in (fio or "").casefold()


def _norm_position(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def is_psd_position(position: str = "") -> bool:
    return _norm_position(position) == _norm_position(PSD_POSITION_NAME)


def has_locked_position_kpi(*, position: str = "") -> bool:
    return is_psd_position(position)


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
            plan_description="Не менее 95% заседаний СД и РК с пакетом не позднее T−2 рабочих дня.",
            fact_description="Доля заседаний СД/РК, у которых предыдущий протокол закрыт или на исполнении не позже чем за 2 рабочих дня до начала.",
            formula="on_time_packages / meetings_with_deadline x 100",
            method=_method(
                plan_explanation=(
                    "План — норма должности: пакет к заседанию совета директоров "
                    "или ревизионной комиссии должен быть готов заранее. Цель 95 процентов. "
                    "Эту норму не меняем автоматически."
                ),
                fact_explanation=(
                    "Смотрим заседания СД и РК в Outlook, у которых уже наступил срок пакета T−2. "
                    "К каждому совещанию берём предыдущий протокол той же серии. "
                    "Пакет вовремя, если этот протокол в статусе «Закрыт» или «НаИсполнении» "
                    "и его дата не позже T−2 рабочих дня. Черновик «Подготовлен» не считаем. "
                    "Если заседаний в окне нет, факт не показываем."
                ),
                score_explanation=(
                    "Оценка совпадает с фактом. Зелёный — факт не ниже 95 процентов, "
                    "жёлтый — не ниже 85, иначе красный. Если факт ≥ 95% → 100%, "
                    "иначе (факт / 95%) × 100%."
                ),
                system=(
                    "Meetings = Outlook SD/RK. previous = last Document_ТД_Протокол "
                    "of the same series with Date < meeting. "
                    "ready = Date when Статус in {Закрыт, НаИсполнении}. deadline = T-2 workdays. "
                    "on_time = closed_at <= deadline. "
                    "fact = z_on_time / z_total * 100. score = gate 95. Do not change plan."
                ),
                how="Outlook «Совещания» + предыдущий Document_ТД_Протокол со статусом Закрыт или НаИсполнении.",
                when="раз в сутки",
                plan_update=locked_plan,
                fact_update="Каждый суточный пересчёт и после запуска агента по пакету.",
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
            plan_description="Не менее 95% протоколов ПСД и поручений месяца внесены в Action Tracker.",
            fact_description="min(R24/Rвсего, Rконтроль/Rактив). План месяца — 1С, факт — Excel агента.",
            formula="min(R24 / Rtotal, Rcontrol / Ractive) x 100",
            method=_method(
                plan_explanation=(
                    "План — норма должности из ПЛ-НПО-010: факт ≥ 95 процентов. "
                    "Норму не пересчитываем."
                ),
                fact_explanation=(
                    "Считает kpi.instruction_tracker: из 1С берёт поручения АСТ00 и протоколы ПСД "
                    "за месяц, из ActionTracker.xlsx — какие номера уже в реестре агента. "
                    "KPI3.1 = доля внесённых за 24 часа и заполненных. "
                    "KPI3.2 = доля активных с подтверждением не старше 7 дней. "
                    "В оценку идёт минимум двух долей."
                ),
                score_explanation=(
                    "Если факт ≥ 95 процентов → 100, иначе факт / 95. "
                    "Зелёный — не ниже 95, жёлтый — не ниже 85, иначе красный."
                ),
                system=(
                    "module=kpi.instruction_tracker. "
                    "expected = OData AST00 + Document_TD_Protokol PSD for month. "
                    "fact excel = ActionTracker.xlsx. "
                    "KPI3.1 = R24/Rtotal. KPI3.2 = Rcontrol/Ractive. "
                    "fact = min. score = gate_then_ratio 95. Do not change plan."
                ),
                how="kpi.instruction_tracker.compute_tile_update: 1C + Action Tracker.",
                when="каждые 6 часов и при входе на вкладку KPI",
                plan_update=locked_plan,
                fact_update="При открытии вкладки и каждые 6 часов тем же модулем.",
                percent_formula="Факт уже в процентах — это min двух долей.",
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
            fact_description="Протоколы Ильченко считаем без возвратов: в карточке 1С нет поля возврата, факт 100%.",
            formula="without_return / submitted x 100",
            method=_method(
                plan_explanation=(
                    "План — норма качества: почти все пакеты и протоколы принимаются "
                    "без возврата. Цель 98 процентов. Норму не пересчитываем."
                ),
                fact_explanation=(
                    "Берём протоколы СД и РК, которые создавала Ильченко. "
                    "В Document_ТД_Протокол нет поля возврата или доработки, "
                    "поэтому все её протоколы считаем принятыми без возврата. "
                    "Если протоколов нет, факт не показываем."
                ),
                score_explanation=(
                    "Оценка совпадает с фактом. Зелёный — не ниже 98 процентов, "
                    "жёлтый — не ниже 88, иначе красный."
                ),
                system=(
                    "window=90d. submitted = Document_ТД_Протокол created by Ilchenko. "
                    "return field does not exist on the 1C card. "
                    "v_errors = 0. fact = 100 if submitted > 0 else empty. "
                    "score = fact. Do not change plan."
                ),
                how="1C Document_ТД_Протокол. No return field: Vоши = 0, quality = 100%.",
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

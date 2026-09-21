from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.position_kpi import (
    PositionCompRule,
    PositionKpiMetric,
    PositionKpiProfile,
    PositionKpiSource,
)

SOURCE_CODE = "PL-NPO-010"
SOURCE_VERSION = "06"
SOURCE_TITLE = "Положение о материальном стимулировании работников управления делами"
EFFECTIVE_FROM = date(2026, 3, 1)
DEPARTMENT = "Управление делами"
BONUS_KIND = "salary_times_crp_times_sum"
BONUS_HUMAN = "П = ДО × ЦРП × ΣПn. ДО — оклад из штатного расписания, в положении сумм нет."
BONUS_NOTES = (
    "ЦРП — целевой размер премии при 100% всех показателей, в % от месячного оклада. "
    "Потолок: месячный доход при 100% целей не выше оклада + надбавки + эта премия, без проектной."
)

REG_PLAN = {
    "role": "plan",
    "kind": "regulation",
    "title": "ПЛ-НПО-010 §5.2.4",
    "detail": "Норма должности из таблицы показателей положения. План не пересчитываем.",
    "update_rule": "Меняется только новой версией положения.",
    "extra_json": {"source_code": SOURCE_CODE, "section": "5.2.4"},
}

VIOLATION_BANDS = {
    "kind": "violation_bands",
    "input": "violations",
    "bands": [
        {"lt": 5, "score": 100},
        {"lte": 8, "score": 50},
        {"gt": 8, "score": 0},
    ],
}
VIOLATION_HUMAN = (
    "Количество нарушений за расчётный период: менее 5 → 100%, от 5 до 8 → 50%, более 8 → 0%."
)
UNKNOWN_VIOLATION_FACT = {
    "role": "fact",
    "kind": "unknown",
    "title": "Нарушения за период",
    "detail": (
        "Положение задаёт шкалу, но не определяет, что считается нарушением "
        "и из какой системы брать счётчик."
    ),
    "update_rule": "Ежемесячно, после описания источника.",
    "extra_json": {"input": "violations"},
}
INDIVIDUAL_FORMULA = {"kind": "individual", "source": "form_02_58"}
INDIVIDUAL_HUMAN = "Зависит от индивидуальной цели (ИЦПП, форма 02-58)."
INDIVIDUAL_FACT = {
    "role": "fact",
    "kind": "manual",
    "title": "Индивидуальная цель",
    "detail": "Оценка по индивидуальной задаче в рамках должностной инструкции.",
    "update_rule": "Раз в расчётный период.",
    "extra_json": {"form": "02-58"},
}


def _gate_ratio(*, fact: str, plan: str, target_pct: int) -> dict[str, Any]:
    return {
        "kind": "gate_then_ratio",
        "direction": "higher",
        "fact": fact,
        "plan": plan,
        "target_pct": target_pct,
        "gate_score": 100,
        "cap": 100,
        "floor": 0,
    }


def _metric(
    *,
    mid: str,
    code: str,
    name: str,
    sort_order: int,
    weight: int,
    formula_kind: str,
    formula_json: dict[str, Any],
    formula_human: str,
    plan_value: int | None = None,
    direction: str = "higher",
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": mid,
        "code": code,
        "name": name,
        "sort_order": sort_order,
        "weight": weight,
        "unit": "%",
        "plan_value": plan_value,
        "direction": direction,
        "formula_kind": formula_kind,
        "formula_json": formula_json,
        "formula_human": formula_human,
        "sources": [dict(REG_PLAN), *sources],
    }


CATALOG: list[dict[str, Any]] = [
    {
        "id": "plnpo010-psd",
        "position_name": "Помощник Председателя совета директоров",
        "summary": "Своевременность пакета и протоколов СД/РК, контроль поручений, качество без возвратов.",
        "comp_id": "plnpo010-psd-comp",
        "metrics": [
            _metric(
                mid="plnpo010-psd-package",
                code="package_on_time",
                name="Своевременность пакета к заседаниям (СД + РК)",
                sort_order=1,
                weight=25,
                formula_kind="gate_then_ratio",
                formula_json=_gate_ratio(fact="z_on_time", plan="z_total", target_pct=95),
                formula_human=(
                    "Факт = Zвовремя / Zвсего × 100%. Цель ≥ 95%. "
                    "Если факт ≥ 95% → 100%, иначе (факт / 95%) × 100%."
                ),
                plan_value=95,
                sources=[
                    {
                        "role": "fact",
                        "kind": "outlook",
                        "title": "Заседания СД и РК",
                        "detail": "Zвсего — число заседаний СД+РК за период. T — дата заседания.",
                        "update_rule": "Раз в месяц по итогам периода.",
                        "extra_json": {
                            "var": "z_total",
                            "legend": "Zвсего",
                            "filters": ["совет директоров", "СД", "ревизион", "РК"],
                        },
                    },
                    {
                        "role": "fact",
                        "kind": "files",
                        "title": "Рассылка пакета",
                        "detail": "Zвовремя — пакет разослан не позднее T−2 рабочих дня.",
                        "update_rule": "Раз в месяц по итогам периода.",
                        "extra_json": {"var": "z_on_time", "legend": "Zвовремя", "deadline": "T-2d"},
                    },
                ],
            ),
            _metric(
                mid="plnpo010-psd-protocol",
                code="protocol_on_time",
                name="Своевременность протоколов (СД + РК)",
                sort_order=2,
                weight=25,
                formula_kind="gate_then_ratio",
                formula_json=_gate_ratio(fact="p_on_time", plan="p_total", target_pct=95),
                formula_human=(
                    "Факт = Pвовремя / Pвсего × 100%. Протокол не позднее T+2 рабочих дня. "
                    "Цель ≥ 95%. Если факт ≥ 95% → 100%, иначе (факт / 95%) × 100%."
                ),
                plan_value=95,
                sources=[
                    {
                        "role": "fact",
                        "kind": "outlook",
                        "title": "Заседания СД и РК",
                        "detail": "Pвсего — число заседаний, по которым уже наступил срок протокола T+2.",
                        "update_rule": "Раз в месяц по итогам периода.",
                        "extra_json": {"var": "p_total", "legend": "Pвсего"},
                    },
                    {
                        "role": "fact",
                        "kind": "files",
                        "title": "Протокол",
                        "detail": "Pвовремя — протокол выпущен не позднее T+2 рабочих дня.",
                        "update_rule": "Раз в месяц по итогам периода.",
                        "extra_json": {"var": "p_on_time", "legend": "Pвовремя", "deadline": "T+2d"},
                    },
                    {
                        "role": "fact",
                        "kind": "onec",
                        "title": "Документ протокола в 1С",
                        "detail": "Дополнительный источник факта появления протокола.",
                        "update_rule": "Раз в месяц по итогам периода.",
                        "extra_json": {"var": "p_on_time", "legend": "Pвовремя"},
                    },
                ],
            ),
            _metric(
                mid="plnpo010-psd-instructions",
                code="instructions",
                name="Реестр и контроль исполнения поручений (СД + РК)",
                sort_order=3,
                weight=25,
                formula_kind="min_of",
                formula_json={
                    "kind": "min_of",
                    "target_pct": 95,
                    "score_mode": "gate_then_ratio",
                    "gate_score": 100,
                    "cap": 100,
                    "parts": [
                        {
                            "id": "kpi3_1",
                            "kind": "ratio_higher",
                            "fact": "r24",
                            "plan": "r_total",
                            "legend": "R24 / Rвсего",
                        },
                        {
                            "id": "kpi3_2",
                            "kind": "ratio_higher",
                            "fact": "r_control",
                            "plan": "r_active",
                            "legend": "Rконтроль / Rактив",
                        },
                    ],
                },
                formula_human=(
                    "Факт = min(KPI3.1, KPI3.2). "
                    "KPI3.1 = R24 / Rвсего: поручение в реестре за 24 часа. "
                    "KPI3.2 = Rконтроль / Rактив: активное поручение обновлено не реже раза в 7 дней. "
                    "Цель ≥ 95%. Если факт ≥ 95% → 100%, иначе (факт / 95%) × 100%."
                ),
                plan_value=95,
                sources=[
                    {
                        "role": "fact",
                        "kind": "onec",
                        "title": "Реестр поручений СД и РК",
                        "detail": (
                            "Rвсего — все поручения/предписания. "
                            "R24 — внесены в реестр корректно в течение 24 часов. "
                            "Rактив — активные. Rконтроль — обновлены не реже раза в 7 дней."
                        ),
                        "update_rule": "Раз в месяц, оперативно чаще.",
                        "extra_json": {
                            "vars": ["r24", "r_total", "r_control", "r_active"],
                            "legend": ["R24", "Rвсего", "Rконтроль", "Rактив"],
                        },
                    },
                ],
            ),
            _metric(
                mid="plnpo010-psd-quality",
                code="quality",
                name="Качество протокола и материалов (без возвратов по вине секретаря)",
                sort_order=4,
                weight=25,
                formula_kind="complement_ratio",
                formula_json={
                    "kind": "complement_ratio",
                    "returned": "v_errors",
                    "total": "v_total",
                    "target_pct": 98,
                    "or_max_cases_per_quarter": 1,
                    "gate_score": 100,
                    "cap": 100,
                },
                formula_human=(
                    "Факт = 1 − Vоши / Vвсего. Цель ≥ 98% или не более 1 случая в квартал. "
                    "Если цель выполнена → 100%, иначе (факт / 98%) × 100%, не больше 100%."
                ),
                plan_value=98,
                sources=[
                    {
                        "role": "fact",
                        "kind": "onec",
                        "title": "Возвраты пакетов и протоколов",
                        "detail": "Vоши — возврат на исправление по вине секретаря. Vвсего — все пакеты/протоколы.",
                        "update_rule": "Раз в месяц / квартал.",
                        "extra_json": {
                            "vars": ["v_errors", "v_total"],
                            "legend": ["Vоши", "Vвсего"],
                        },
                    },
                    {
                        "role": "fact",
                        "kind": "agent_runs",
                        "title": "События возврата в запусках агента",
                        "detail": "Дополнительный признак returned / на доработке.",
                        "update_rule": "Раз в месяц.",
                        "extra_json": {"event_types": ["returned"]},
                    },
                ],
            ),
        ],
    },
    {
        "id": "plnpo010-assistant",
        "position_name": "Помощник руководителя",
        "summary": "Планирование заседаний и совещаний ПСД, ДПИ, регистрация приказов, индивидуальные задачи.",
        "comp_id": "plnpo010-assistant-comp",
        "metrics": [
            _metric(
                mid="plnpo010-assistant-meetings",
                code="meetings_schedule",
                name="Планирование заседаний, организация рабочего времени и административная поддержка директора",
                sort_order=1,
                weight=40,
                formula_kind="violation_bands",
                formula_json=dict(VIOLATION_BANDS),
                formula_human=VIOLATION_HUMAN,
                sources=[dict(UNKNOWN_VIOLATION_FACT)],
            ),
            _metric(
                mid="plnpo010-assistant-unplanned",
                code="unplanned_meetings",
                name="Планирование внеплановых совещаний / совещаний с участием ПСД",
                sort_order=2,
                weight=30,
                formula_kind="violation_bands",
                formula_json=dict(VIOLATION_BANDS),
                formula_human=VIOLATION_HUMAN,
                sources=[dict(UNKNOWN_VIOLATION_FACT)],
            ),
            _metric(
                mid="plnpo010-assistant-dpi",
                code="dpi_appointment",
                name="Назначение ДПИ за месяц",
                sort_order=3,
                weight=10,
                formula_kind="needs_clarify",
                formula_json={
                    "kind": "needs_clarify",
                    "note": "В скане ПЛ-НПО-010 ячейка расчёта склеена с соседними.",
                },
                formula_human="Формула в скане положения однозначно не читается — уточнить по оригиналу.",
                sources=[
                    {
                        "role": "fact",
                        "kind": "unknown",
                        "title": "Назначение ДПИ",
                        "detail": "Источник факта в положении не указан.",
                        "update_rule": "Раз в месяц.",
                        "extra_json": {},
                    }
                ],
            ),
            _metric(
                mid="plnpo010-assistant-orders",
                code="orders_registration",
                name="Регистрация приказов и распоряжений",
                sort_order=4,
                weight=10,
                formula_kind="needs_clarify",
                formula_json={
                    "kind": "needs_clarify",
                    "note": "В скане ПЛ-НПО-010 ячейка расчёта склеена с соседними.",
                },
                formula_human="Формула в скане положения однозначно не читается — уточнить по оригиналу.",
                sources=[
                    {
                        "role": "fact",
                        "kind": "onec",
                        "title": "Регистрация приказов и распоряжений",
                        "detail": "Вероятный источник — 1С документооборот. В положении система не названа.",
                        "update_rule": "Раз в месяц.",
                        "extra_json": {},
                    }
                ],
            ),
            _metric(
                mid="plnpo010-assistant-individual",
                code="individual",
                name="Индивидуальные задачи в рамках должностной инструкции",
                sort_order=5,
                weight=10,
                formula_kind="individual",
                formula_json=dict(INDIVIDUAL_FORMULA),
                formula_human=INDIVIDUAL_HUMAN,
                sources=[dict(INDIVIDUAL_FACT)],
            ),
        ],
    },
    {
        "id": "plnpo010-office",
        "position_name": "Офис-менеджер",
        "summary": "Входящая корреспонденция, реестры исходящих, индивидуальные задачи.",
        "comp_id": "plnpo010-office-comp",
        "metrics": [
            _metric(
                mid="plnpo010-office-incoming",
                code="incoming_mail",
                name=(
                    "Приём, обработка и регистрация входящей корреспонденции "
                    "по ГК для различных носителей (info, Почта России, курьер, адрес)"
                ),
                sort_order=1,
                weight=50,
                formula_kind="violation_bands",
                formula_json=dict(VIOLATION_BANDS),
                formula_human=VIOLATION_HUMAN,
                sources=[dict(UNKNOWN_VIOLATION_FACT)],
            ),
            _metric(
                mid="plnpo010-office-outgoing",
                code="outgoing_registry",
                name=(
                    "Формирование реестров для отправки почтовой корреспонденции, "
                    "контроль исполнения актов выполненных работ, оплата счетов"
                ),
                sort_order=2,
                weight=40,
                formula_kind="violation_bands",
                formula_json=dict(VIOLATION_BANDS),
                formula_human=VIOLATION_HUMAN,
                sources=[dict(UNKNOWN_VIOLATION_FACT)],
            ),
            _metric(
                mid="plnpo010-office-individual",
                code="individual",
                name="Индивидуальные задачи в рамках должностной инструкции",
                sort_order=3,
                weight=10,
                formula_kind="individual",
                formula_json=dict(INDIVIDUAL_FORMULA),
                formula_human=INDIVIDUAL_HUMAN,
                sources=[dict(INDIVIDUAL_FACT)],
            ),
        ],
    },
    {
        "id": "plnpo010-archive",
        "position_name": "Архивариус",
        "summary": "Приём и внесение документов в архив, индивидуальные задачи.",
        "comp_id": "plnpo010-archive-comp",
        "metrics": [
            _metric(
                mid="plnpo010-archive-receive",
                code="archive_receive",
                name="Приём документов в архив",
                sort_order=1,
                weight=10,
                formula_kind="violation_bands",
                formula_json=dict(VIOLATION_BANDS),
                formula_human=VIOLATION_HUMAN,
                sources=[dict(UNKNOWN_VIOLATION_FACT)],
            ),
            _metric(
                mid="plnpo010-archive-enter",
                code="archive_enter",
                name="Внесение документов в архив",
                sort_order=2,
                weight=70,
                formula_kind="violation_bands",
                formula_json=dict(VIOLATION_BANDS),
                formula_human=VIOLATION_HUMAN,
                sources=[dict(UNKNOWN_VIOLATION_FACT)],
            ),
            _metric(
                mid="plnpo010-archive-individual",
                code="individual",
                name="Индивидуальные задачи в рамках должностной инструкции",
                sort_order=3,
                weight=20,
                formula_kind="individual",
                formula_json=dict(INDIVIDUAL_FORMULA),
                formula_human=INDIVIDUAL_HUMAN,
                sources=[dict(INDIVIDUAL_FACT)],
            ),
        ],
    },
]


def _upsert(db: Session, model, item_id: str, **values: Any) -> None:
    row = db.get(model, item_id)
    if row is None:
        db.add(model(id=item_id, **values))
        return
    for key, value in values.items():
        setattr(row, key, value)


def upsert_catalog(db: Session) -> list[str]:
    """Idempotent seed: четыре должности из ПЛ-НПО-010."""
    ids: list[str] = []
    keep_profile_ids = {str(item["id"]) for item in CATALOG}
    keep_metric_ids: set[str] = set()
    keep_source_ids: set[str] = set()

    for item in CATALOG:
        profile_id = str(item["id"])
        ids.append(profile_id)
        _upsert(
            db,
            PositionKpiProfile,
            profile_id,
            position_name=item["position_name"],
            department=DEPARTMENT,
            status="active",
            source_code=SOURCE_CODE,
            source_version=SOURCE_VERSION,
            source_title=SOURCE_TITLE,
            effective_from=EFFECTIVE_FROM,
            summary=item["summary"],
        )
        db.flush()
        _upsert(
            db,
            PositionCompRule,
            str(item["comp_id"]),
            profile_id=profile_id,
            salary_min=None,
            salary_max=None,
            currency="RUB",
            bonus_kind=BONUS_KIND,
            bonus_base_pct=100,
            bonus_human=BONUS_HUMAN,
            payout_json=[],
            notes=BONUS_NOTES,
        )
        for metric in item["metrics"]:
            metric_id = str(metric["id"])
            keep_metric_ids.add(metric_id)
            _upsert(
                db,
                PositionKpiMetric,
                metric_id,
                profile_id=profile_id,
                code=metric["code"],
                name=metric["name"],
                sort_order=int(metric["sort_order"]),
                weight=int(metric["weight"]),
                unit=metric["unit"],
                plan_value=metric.get("plan_value"),
                direction=metric["direction"],
                formula_kind=metric["formula_kind"],
                formula_json=metric["formula_json"],
                formula_human=metric["formula_human"],
            )
            db.flush()
            for index, source in enumerate(metric["sources"], start=1):
                source_id = f"{metric_id}-{source['role']}-{source['kind']}-{index}"
                keep_source_ids.add(source_id)
                _upsert(
                    db,
                    PositionKpiSource,
                    source_id,
                    metric_id=metric_id,
                    role=source["role"],
                    kind=source["kind"],
                    title=source["title"],
                    detail=source["detail"],
                    update_rule=source["update_rule"],
                    extra_json=source.get("extra_json") or {},
                )

    for source in db.query(PositionKpiSource).all():
        if source.id.startswith("plnpo010-") and source.id not in keep_source_ids:
            db.delete(source)
    for metric in db.query(PositionKpiMetric).all():
        if metric.id.startswith("plnpo010-") and metric.id not in keep_metric_ids:
            db.delete(metric)
    for profile in db.query(PositionKpiProfile).all():
        if profile.id.startswith("plnpo010-") and profile.id not in keep_profile_ids:
            db.delete(profile)
    return ids

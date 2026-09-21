from __future__ import annotations

from datetime import date

from kpi.sources.onec_meetings import (
    count_iso_weekdays,
    looks_like_weekly_series,
    normalize_theme_name,
    plan_count,
    plan_for_series,
    plan_from_occurrence_dates,
)


AUG_START, AUG_END = date(2026, 8, 1), date(2026, 8, 31)


def test_weekly_friday_in_august_2026():
    theme = {
        "РасписаниеЗадано": True,
        "ПовторениеПоДнямНедели": [{"День": 5}],
    }
    assert plan_count(theme, AUG_START, AUG_END) == 4


def test_weekly_monday_in_august_2026():
    theme = {
        "РасписаниеЗадано": True,
        "ПовторениеПоДнямНедели": [{"День": 1}],
    }
    assert plan_count(theme, AUG_START, AUG_END) == 5


def test_unscheduled_is_zero():
    assert plan_count({"РасписаниеЗадано": False}, AUG_START, AUG_END) == 0


def test_august_weekday_counts():
    assert count_iso_weekdays(AUG_START, AUG_END, [1]) == 5
    assert count_iso_weekdays(AUG_START, AUG_END, [3]) == 4
    assert count_iso_weekdays(AUG_START, AUG_END, [5]) == 4
    assert count_iso_weekdays(AUG_START, AUG_END, [2, 5]) == 8
    assert count_iso_weekdays(AUG_START, AUG_END, [1, 4]) == 9


def test_plan_from_single_protocol():
    assert plan_from_occurrence_dates([date(2026, 8, 11)], AUG_START, AUG_END) == 1


def test_plan_weekly_from_same_weekday():
    assert plan_from_occurrence_dates(
        [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)],
        AUG_START,
        AUG_END,
    ) == 5


def test_plan_two_singles_is_fact():
    assert plan_from_occurrence_dates(
        [date(2026, 8, 11), date(2026, 8, 20)],
        AUG_START,
        AUG_END,
        name="Управление товарными остатками",
    ) == 2


def test_plan_legal_weekly_name_uses_first_weekday():
    assert plan_from_occurrence_dates(
        [date(2026, 8, 6), date(2026, 8, 12)],
        AUG_START,
        AUG_END,
        name="Совещание с юридическим отделом",
    ) == 4


def test_plan_tech_director_two_weekdays():
    assert plan_from_occurrence_dates(
        [date(2026, 8, 11), date(2026, 8, 14), date(2026, 8, 21)],
        AUG_START,
        AUG_END,
        name="Совещание с техническим директором",
    ) == 8


def test_plan_tender_monday_plus_thursday():
    assert plan_from_occurrence_dates(
        [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 20), date(2026, 8, 31)],
        AUG_START,
        AUG_END,
        name="Тендерный комитет (регл.)",
    ) == 9


def test_plan_personnel_modal_monday():
    assert plan_from_occurrence_dates(
        [
            date(2026, 8, 3),
            date(2026, 8, 5),
            date(2026, 8, 10),
            date(2026, 8, 19),
            date(2026, 8, 31),
        ],
        AUG_START,
        AUG_END,
        name="Совещание со службой персонала",
    ) == 5


def test_plan_shipment_friday_ignores_extra_wednesday():
    assert plan_from_occurrence_dates(
        [
            date(2026, 8, 5),
            date(2026, 8, 7),
            date(2026, 8, 14),
            date(2026, 8, 21),
            date(2026, 8, 28),
        ],
        AUG_START,
        AUG_END,
        name="График отгрузок по производству №1",
    ) == 4


def test_schedule_used_only_when_facts_fit():
    thursdays = [date(2026, 8, 6), date(2026, 8, 13), date(2026, 8, 20)]
    assert plan_for_series(thursdays, AUG_START, AUG_END, scheduled_weekdays=[4]) == 4
    mondays = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)]
    assert plan_for_series(mondays, AUG_START, AUG_END, scheduled_weekdays=[3]) == 5


def test_stock_schedule_tuesday_used_even_with_extra_thursday():
    assert plan_for_series(
        [date(2026, 8, 11), date(2026, 8, 20)],
        AUG_START,
        AUG_END,
        name="Управление товарными остатками",
        scheduled_weekdays=[2],
    ) == 4


def test_weekly_name_without_weekday_defaults_to_monday():
    assert plan_from_occurrence_dates(
        [date(2026, 8, 4), date(2026, 8, 13)],
        AUG_START,
        AUG_END,
        name="Еженедельное совещание с заместителем директора по перспективным проектам",
    ) == 5


def test_august_2026_circle_table():
    """Август 2026: 22 строки отчёта Донцовой из п-ф.xlsx."""
    series = {
        "Выпуск по заказам ЭЦ": [
            date(2026, 8, 7),
            date(2026, 8, 14),
            date(2026, 8, 21),
            date(2026, 8, 28),
        ],
        "Выпуск продукции по производству №1": [
            date(2026, 8, 7),
            date(2026, 8, 14),
            date(2026, 8, 21),
            date(2026, 8, 28),
        ],
        "Выпуск продукции по производству №2": [
            date(2026, 8, 7),
            date(2026, 8, 14),
            date(2026, 8, 21),
            date(2026, 8, 28),
        ],
        "График отгрузок по производству №1": [
            date(2026, 8, 5),
            date(2026, 8, 7),
            date(2026, 8, 14),
            date(2026, 8, 21),
            date(2026, 8, 28),
        ],
        "График отгрузок по производству №2": [
            date(2026, 8, 7),
            date(2026, 8, 14),
            date(2026, 8, 21),
            date(2026, 8, 28),
        ],
        "ДПИ отделов продаж": [date(2026, 8, 11)],
        "ДПИ СУП": [date(2026, 8, 10)],
        "ДПИ юридический отдел": [date(2026, 8, 6)],
        "Еженедельное совещание по общим вопросам с отделами продаж": [
            date(2026, 8, 5),
            date(2026, 8, 12),
            date(2026, 8, 19),
        ],
        "Еженедельное совещание с бухгалтерией": [
            date(2026, 8, 6),
            date(2026, 8, 13),
            date(2026, 8, 19),
            date(2026, 8, 26),
        ],
        "Еженедельное совещание с заместителем директора по перспективным проектам": [
            date(2026, 8, 4),
            date(2026, 8, 13),
        ],
        "Еженедельное совещание с ОВЭД": [
            date(2026, 8, 3),
            date(2026, 8, 10),
            date(2026, 8, 17),
        ],
        "Еженедельное совещание с ОДП": [
            date(2026, 8, 6),
            date(2026, 8, 13),
            date(2026, 8, 20),
        ],
        "Еженедельное совещание с ОПЭОиУ": [
            date(2026, 8, 3),
            date(2026, 8, 10),
            date(2026, 8, 17),
            date(2026, 8, 31),
        ],
        "Еженедельное совещание с ОРКК": [
            date(2026, 8, 4),
            date(2026, 8, 11),
            date(2026, 8, 18),
        ],
        "Еженедельное совещание с отделом по работе с ПАО Газпром": [
            date(2026, 8, 6),
            date(2026, 8, 13),
            date(2026, 8, 20),
        ],
        "Еженедельное совещание сектором рекламы и PR": [
            date(2026, 8, 6),
            date(2026, 8, 13),
            date(2026, 8, 20),
        ],
        "Совещание с техническим директором": [
            date(2026, 8, 11),
            date(2026, 8, 14),
            date(2026, 8, 21),
        ],
        "Совещание с юридическим отделом": [
            date(2026, 8, 6),
            date(2026, 8, 12),
        ],
        "Совещание со службой персонала": [
            date(2026, 8, 3),
            date(2026, 8, 5),
            date(2026, 8, 10),
            date(2026, 8, 19),
            date(2026, 8, 31),
        ],
        "Тендерный комитет (регл.)": [
            date(2026, 8, 3),
            date(2026, 8, 10),
            date(2026, 8, 20),
            date(2026, 8, 31),
        ],
        "Управление товарными остатками": [
            date(2026, 8, 11),
            date(2026, 8, 20),
        ],
    }
    schedules = {
        "Еженедельное совещание с ОВЭД": [3],
        "Еженедельное совещание с ОДП": [4],
        "Еженедельное совещание с ОПЭОиУ": [1],
        "Еженедельное совещание с ОРКК": [2],
        "Еженедельное совещание с отделом по работе с ПАО Газпром": [4],
        "Еженедельное совещание по общим вопросам с отделами продаж": [3],
        "Управление товарными остатками": [2],
    }
    expected = {
        "Выпуск по заказам ЭЦ": (4, 4),
        "Выпуск продукции по производству №1": (4, 4),
        "Выпуск продукции по производству №2": (4, 4),
        "График отгрузок по производству №1": (4, 5),
        "График отгрузок по производству №2": (4, 4),
        "ДПИ отделов продаж": (1, 1),
        "ДПИ СУП": (1, 1),
        "ДПИ юридический отдел": (1, 1),
        "Еженедельное совещание по общим вопросам с отделами продаж": (4, 3),
        "Еженедельное совещание с бухгалтерией": (4, 4),
        "Еженедельное совещание с заместителем директора по перспективным проектам": (5, 2),
        "Еженедельное совещание сектором рекламы и PR": (4, 3),
        "Еженедельное совещание с ОВЭД": (5, 3),
        "Еженедельное совещание с ОДП": (4, 3),
        "Еженедельное совещание с ОПЭОиУ": (5, 4),
        "Еженедельное совещание с ОРКК": (4, 3),
        "Еженедельное совещание с отделом по работе с ПАО Газпром": (4, 3),
        "Совещание с техническим директором": (8, 3),
        "Совещание с юридическим отделом": (4, 2),
        "Совещание со службой персонала": (5, 5),
        "Тендерный комитет (регл.)": (9, 4),
        "Управление товарными остатками": (4, 2),
    }
    got = {
        name: (
            plan_for_series(
                dates,
                AUG_START,
                AUG_END,
                name=name,
                scheduled_weekdays=schedules.get(name),
            ),
            len(dates),
        )
        for name, dates in series.items()
    }
    assert got == expected
    assert sum(plan for plan, _ in got.values()) == 92
    assert sum(fact for _, fact in got.values()) == 68


def test_aliases_merge_circle_duplicates():
    assert normalize_theme_name("Выпуск продукции ЭЦ") == normalize_theme_name("Выпуск по заказам ЭЦ")
    assert normalize_theme_name("Тендерная комиссия") == normalize_theme_name("Тендерный комитет (регл.)")
    assert normalize_theme_name("Еженедельное совещание с ОДПТ") == normalize_theme_name(
        "Еженедельное совещание с ОДП"
    )
    assert looks_like_weekly_series("Совещание с юридическим отделом")
    assert not looks_like_weekly_series("Управление товарными остатками")

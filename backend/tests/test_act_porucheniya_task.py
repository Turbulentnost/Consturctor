from __future__ import annotations

from app.services.act_porucheniya_task import (
    apply_act_document_filters,
    extract_act_numbers,
    extract_excel_path_from_task,
    parse_act_filter_from_task,
    parse_act_task_intent,
)


def test_extract_act_numbers() -> None:
    assert "ACT00-00088" in extract_act_numbers("Покажи ACT00-00088")
    assert "ACT00-00001" in extract_act_numbers("аст00-1")
    assert extract_act_numbers(
        "сохрани Excel с форматированием по каждому ACT00-***"
    ) == []
    assert extract_act_numbers("ACT00-00000") == []


def test_parse_overdue_filter() -> None:
    filt = parse_act_filter_from_task("Только просроченные поручения")
    assert "overdue" in filt["criticality_levels"]


def test_apply_criticality_filter() -> None:
    docs = [
        {
            "number": "ACT00-00001",
            "status": "В работе",
            "task_lines": [
                {
                    "task": "old task",
                    "deadline_raw": "2020-01-01T00:00:00",
                },
                {
                    "task": "future task",
                    "deadline_raw": "2099-12-31T00:00:00",
                },
            ],
        },
    ]
    filt = {"criticality_levels": ["overdue"], "act_numbers": [], "status_keys": [], "keywords": []}
    filtered, desc = apply_act_document_filters(docs, filt)
    assert len(filtered) == 1
    assert len(filtered[0]["task_lines"]) == 1
    assert filtered[0]["task_lines"][0]["task"] == "old task"


def test_apply_act_number_filter() -> None:
    docs = [
        {"number": "ACT00-00088", "number_display": "ACT00-00088", "final_deadline_raw": ""},
        {"number": "ACT00-00001", "number_display": "ACT00-00001", "final_deadline_raw": ""},
    ]
    filt = parse_act_filter_from_task("ACT00-00088")
    filtered, _ = apply_act_document_filters(docs, filt)
    assert len(filtered) == 1
    assert filtered[0]["number"] == "ACT00-00088"


def test_parse_summarize_excel_intent() -> None:
    task = (
        "суммаризируй информацию из этого excel "
        "file:///C:/Users/mdj/Desktop/act_porucheniya_ЖМД_7e81ded8.xlsx"
    )
    assert parse_act_task_intent(task) == "summarize_excel"
    assert "act_porucheniya" in extract_excel_path_from_task(task).casefold()

    typo_task = (
        "суммиризируй информацию из этого excel "
        "file:///C:/Users/mdj/Desktop/act_porucheniya_ЖМД_7e81ded8.xlsx"
    )
    assert parse_act_task_intent(typo_task) == "summarize_excel"


def test_parse_export_intent() -> None:
    assert parse_act_task_intent("Выгрузи полный ACT-реестр из OData на рабочий стол") == "export"


def test_parse_reformat_intent() -> None:
    assert parse_act_task_intent("обнови excel") == "reformat_excel"
    task = (
        "посмотри file:///C:/Users/mdj/Desktop/act_porucheniya_ЖМД_1e14b68c.xlsx "
        "и сделай цвета чуть более светлыми"
    )
    assert parse_act_task_intent(task) == "reformat_excel"


def test_parse_freeform_chat_intent() -> None:
    assert parse_act_task_intent("фыв") == "freeform_chat"
    assert parse_act_task_intent("привет, как дела?") == "freeform_chat"


def test_parse_analyze_chat_not_export() -> None:
    assert parse_act_task_intent("покажи только просроченные") == "analyze_chat"


def test_parse_merge_add_intent() -> None:
    task = (
        "добавь ещё Задача: выполнить работы по созданию агента, "
        "Исполнитель: Жалыбин Максим Дмитриевич, срок до 20.08.26, статус в работе"
    )
    assert parse_act_task_intent(task) == "merge_add"


def test_inline_add_does_not_apply_status_filter() -> None:
    task = (
        "добавь ещё Задача: выполнить работы по созданию агента, "
        "Исполнитель: Жалыбин Максим Дмитриевич, срок до 20.08.26, статус в работе"
    )
    filt = parse_act_filter_from_task(task)
    assert filt["status_keys"] == []
    assert "created" not in filt["status_keys"]


def test_compose_excel_workbook_summary() -> None:
    from app.services.act_porucheniya_report import compose_excel_workbook_summary

    payload = {
        "rows": [
            ["Номер ACT", "Задача", "Исполнитель", "Срок", "Статус"],
            ["ACT00-00001", "Test", "Иванов", "01.01.2020", "В работе"],
        ],
        "sheet": "Задачи ACT",
        "filename": "act.xlsx",
    }
    text = compose_excel_workbook_summary(payload, source_path="C:\\Desktop\\act.xlsx")
    assert "Строк задач: 1" in text
    assert "просроч" in text.casefold()

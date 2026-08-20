from app.services.workflows.cursor_tools import (
    _assumption_check_prompt,
    tools_prompt_block,
)
from app.services.workflows.prompts import (
    build_demo_prompt,
    parse_clarify_from_text,
)
from app.services.workflows.service import _cursor_chunks


def test_demo_prompt_with_draft_does_not_stop_for_clarify() -> None:
    text = build_demo_prompt(
        document_text="Распланировать серию совещаний по служебным запискам.",
        title="Серия совещаний",
        draft={
            "status": "draft",
            "steps": [
                {
                    "id": "s2",
                    "title": "Найти СЗ",
                    "system": "onec",
                    "entity": "service_note",
                    "operation": "search",
                }
            ],
        },
    )
    low = text.casefold()
    assert "не задавай clarify" in low
    assert "после clarify не вызывай" not in low
    assert "черновик инструкции" in low


def test_demo_prompt_requires_content_questions() -> None:
    text = build_demo_prompt(
        document_text="Следить за сроками в TurboProject и писать руководителю.",
        title="Сроки проектов",
    )
    low = text.casefold()
    assert "не бери" in low
    assert "CLARIFY" in text
    assert "как часто" in low
    assert "в каком виде" in low
    assert "RESULT:" in text
    assert "угадывать" in low or "default" in low
    assert "OData" in text or "odata" in low
    assert "видимом ответе" in low


def test_tools_catalog_attached_without_desktop_context() -> None:
    from app.services.workflows.cursor_tools import clear_tool_context, with_tools_if_desktop

    clear_tool_context()
    text = with_tools_if_desktop("Сделай сводку по проектам.")
    assert "constructor_tool" in text
    assert "turboproject" in text


def test_tools_block_does_not_force_all_projects() -> None:
    block = tools_prompt_block()
    assert '{"name": "turboproject", "arguments": {}}' not in block
    assert "CLARIFY" in block


def test_assumption_check_asks_not_to_process_catalog() -> None:
    text = _assumption_check_prompt(
        [{"name": "turboproject", "ok": True, "result": {"count": 12}}]
    )
    low = text.casefold()
    assert "clarify" in low
    assert "допущен" in low
    assert "как часто" in low
    assert "в каком виде" in low
    assert "не разбирай весь каталог" in low


def test_parse_clarify_markdown_headers() -> None:
    text = """
CLARIFY:
**QUESTION:** Какие проекты брать в расчёт?
**OPTIONS:**
- все сектора
- где пользователь руководитель
- один проект
**WHY:** в ТЗ не сказано
"""
    found = parse_clarify_from_text(text)
    assert found
    assert "проекты" in found[0].question.casefold()
    assert any("сектора" in opt for opt in found[0].options)


def test_parse_clarify_numbered_prose() -> None:
    text = (
        "Прогон без ответов на CLARIFY: выданы принятые решения из паспорта "
        "и 4 вопроса —\n"
        "(1) проекты: все сектора / где пользователь руководитель / один проект / иной критерий\n"
        "(2) запуск: только триггеры / периодически / ручной\n"
        "(3) доставка: notify исполнителям / отчёт в чат / ответственному\n"
    )
    found = parse_clarify_from_text(text)
    assert len(found) >= 3
    assert any("проект" in q.question.casefold() for q in found)
    assert any("запуск" in q.question.casefold() for q in found)


def test_parse_clarify_block() -> None:
    text = """
Нужно понять объём.

CLARIFY:
QUESTION: Какие проекты брать?
OPTIONS:
- только активные
- все проекты
- укажу названия
WHY: в ТЗ не сказано
QUESTION: Как часто проверять сроки?
OPTIONS:
- каждый час
- раз в день
WHY: расписание не задано
"""
    found = parse_clarify_from_text(text)
    assert len(found) == 2
    assert "проекты" in found[0].question.casefold()
    assert "часто" in found[1].question.casefold()
    assert "активные" in found[0].options[0]


def test_parse_clarify_drops_technical() -> None:
    text = """
CLARIFY:
QUESTION: Какой OData entity вызывать?
OPTIONS:
- onec.odata_get
- turboproject
"""
    assert parse_clarify_from_text(text) == []


def test_parse_clarify_fallback_scope_question() -> None:
    found = parse_clarify_from_text("Какие проекты брать для сводки?")
    assert found
    assert "проекты" in found[0].question.casefold()


def test_parse_clarify_ignores_finished_report() -> None:
    text = (
        "Нашёл 3 просрочки в проекте Альфа и отправил сводку руководителю. "
        "Прогон готов."
    )
    assert parse_clarify_from_text(text) == []


def test_cursor_chunks_split_thinking_and_text() -> None:
    chunks = _cursor_chunks(
        "update",
        {"thinking": "Сначала посмотрю каталог.", "text": "Какие объекты брать?"},
    )
    assert chunks == [
        ("thinking", "Сначала посмотрю каталог."),
        ("assistant", "Какие объекты брать?"),
    ]


def test_cursor_chunks_thinking_event() -> None:
    chunks = _cursor_chunks("thinking", {"text": "Ищу подходящий tool."})
    assert chunks == [("thinking", "Ищу подходящий tool.")]


def test_cursor_chunks_assistant_only() -> None:
    chunks = _cursor_chunks("assistant", {"text": "Беру только проекты текущего пользователя."})
    assert chunks == [("assistant", "Беру только проекты текущего пользователя.")]

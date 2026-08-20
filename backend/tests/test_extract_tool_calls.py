from app.services.workflows.cursor_tools import extract_tool_calls, should_run_tool_calls
from app.services.workflows.prompts import parse_work_result


def test_extract_tool_calls_allows_space_after_fence() -> None:
    text = (
        "Сформирую блоки constructor_tool прямо в ответе. "
        "Выполняю запрос к Document_ТД_Поручения для записи ACT00-00050."
        "``` constructor_tool\n"
        '{"name": "onec.odata_get", "arguments": {"entity": "Document_ТД_Поручения", '
        '"path": "$filter=startswith(Number,\'ACT50\')&$top=5"}}\n'
    )
    calls = extract_tool_calls(text)
    assert calls[0]["name"] == "onec.odata_get"
    assert calls[0]["arguments"]["entity"] == "Document_ТД_Поручения"


def test_extract_bare_tool_json() -> None:
    text = '{"name": "files.copy", "arguments": {"source": "C:\\\\a.xlsx", "dest_name": "Поручения"}}'
    calls = extract_tool_calls(text)
    assert calls == [
        {"name": "files.copy", "arguments": {"source": "C:\\a.xlsx", "dest_name": "Поручения"}}
    ]


def test_should_run_spaced_fence() -> None:
    text = "``` constructor_tool\n" '{"name": "turboproject", "arguments": {}}\n' "```\n"
    assert should_run_tool_calls(text, mode="execute") == [
        {"name": "turboproject", "arguments": {}}
    ]


def test_parse_work_result_drops_spaced_tool_fence() -> None:
    text = (
        "Сформирую блоки constructor_tool прямо в ответе.\n"
        "``` constructor_tool\n"
        '{"name": "onec.odata_get", "arguments": {}}\n'
        "```\n"
        "RESULT:\nНашёл поручение ACT00-00050.\n"
    )
    work = parse_work_result(text)
    assert "ACT00-00050" in work["text"]
    assert "constructor_tool" not in work["text"]
    assert "odata_get" not in work["text"]

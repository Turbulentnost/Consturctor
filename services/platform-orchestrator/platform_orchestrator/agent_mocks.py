"""Predefined mock AI agent scenarios for tool verification (USE_STUBS)."""

from __future__ import annotations

from typing import Any, TypedDict


class ToolCallSpec(TypedDict, total=False):
    thought: str
    tool_name: str
    payload: dict[str, Any]


class MockScenario(TypedDict):
    title: str
    description: str
    agent_id: str
    tool_calls: list[ToolCallSpec]


MOCK_SCENARIOS: dict[str, MockScenario] = {
    "mail_inbound": {
        "title": "Входящая почта",
        "description": "Агент проверяет IMAP, читает письмо и забирает вложения",
        "agent_id": "mock-mail-agent",
        "tool_calls": [
            {
                "thought": "Проверяю непрочитанные письма во входящих",
                "tool_name": "imap.list_unread",
                "payload": {"source": "mock_agent"},
            },
            {
                "thought": "Открываю письмо uid=101 для классификации",
                "tool_name": "imap.fetch_message",
                "payload": {"uid": 101},
            },
            {
                "thought": "Сохраняю вложения для регистрации в 1С",
                "tool_name": "imap.fetch_attachments",
                "payload": {"uid": 101},
            },
        ],
    },
    "onec_register": {
        "title": "Регистрация в 1С",
        "description": "Агент читает OData, создаёт документ и прикрепляет файл",
        "agent_id": "mock-onec-agent",
        "tool_calls": [
            {
                "thought": "Ищу контрагента и вид документа в OData",
                "tool_name": "onec.odata_get",
                "payload": {"path": "/Catalog_Контрагенты?$top=1"},
            },
            {
                "thought": "Создаю входящий документ через OData POST",
                "tool_name": "onec.odata_post",
                "payload": {"entity": "Document_ВходящаяКорреспонденция", "body": {"stub": True}},
            },
            {
                "thought": "Прикрепляю PDF к созданному документу",
                "tool_name": "onec.attach_file",
                "payload": {
                    "document_ref_key": "11111111-1111-1111-1111-000000000001",
                    "filename": "incoming.pdf",
                },
            },
        ],
    },
    "shell_probe": {
        "title": "Shell sandbox",
        "description": "Агент выполняет безопасную команду в sandbox",
        "agent_id": "mock-shell-agent",
        "tool_calls": [
            {
                "thought": "Проверяю окружение агента через echo",
                "tool_name": "shell.run",
                "payload": {"command": "echo mock-agent-ok"},
            },
        ],
    },
    "browser_research": {
        "title": "Browser research",
        "description": "Агент открывает страницу, делает скриншот и извлекает текст",
        "agent_id": "mock-browser-agent",
        "tool_calls": [
            {
                "thought": "Открываю ephemeral browser session",
                "tool_name": "browser.open_session",
                "payload": {},
            },
            {
                "thought": "Открываю страницу поставщика для сверки реквизитов",
                "tool_name": "browser.navigate",
                "payload": {"url": "https://example.com/supplier"},
            },
            {
                "thought": "Снимаю snapshot интерактивных элементов",
                "tool_name": "browser.snapshot",
                "payload": {},
            },
            {
                "thought": "Делаю скриншот для архива",
                "tool_name": "browser.screenshot",
                "payload": {"full_page": True},
            },
            {
                "thought": "Извлекаю текст с карточки контрагента",
                "tool_name": "browser.extract_text",
                "payload": {"selector": "main"},
            },
            {
                "thought": "Закрываю browser session",
                "tool_name": "browser.close_session",
                "payload": {},
            },
        ],
    },
    "full_correspondence": {
        "title": "Полный пайплайн корреспонденции",
        "description": "Почта → 1С → shell проверка → browser архив",
        "agent_id": "mock-full-agent",
        "tool_calls": [
            {
                "thought": "Шаг 1: непрочитанные письма",
                "tool_name": "imap.list_unread",
                "payload": {},
            },
            {
                "thought": "Шаг 2: регистрация документа в 1С",
                "tool_name": "onec.odata_post",
                "payload": {"entity": "Document_ВходящаяКорреспонденция"},
            },
            {
                "thought": "Шаг 3: проверка статуса через shell",
                "tool_name": "shell.run",
                "payload": {"command": "echo pipeline-ok"},
            },
            {
                "thought": "Шаг 4: архивная копия в browser",
                "tool_name": "browser.screenshot",
                "payload": {},
            },
        ],
    },
}


def list_mock_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "id": scenario_id,
            "title": scenario["title"],
            "description": scenario["description"],
            "agent_id": scenario["agent_id"],
            "tool_count": len(scenario["tool_calls"]),
            "tools": [call["tool_name"] for call in scenario["tool_calls"]],
        }
        for scenario_id, scenario in MOCK_SCENARIOS.items()
    ]


def get_mock_scenario(scenario_id: str) -> MockScenario:
    try:
        return MOCK_SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown mock scenario: {scenario_id}") from exc


def tool_names_from_scenario(scenario: MockScenario) -> list[str]:
    return [call["tool_name"] for call in scenario["tool_calls"]]

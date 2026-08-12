"""Predefined sandbox test calls for all platform tools."""

from __future__ import annotations

from typing import Any

from platform_orchestrator.agent_mocks import MockScenario, ToolCallSpec

SANDBOX_TESTS: dict[str, MockScenario] = {
    "onec_incoming": {
        "title": "1С: входящая корреспонденция",
        "description": "3 последних документа Document_ВходящаяКорреспонденция (документооборот)",
        "agent_id": "sandbox-onec",
        "tool_calls": [
            {
                "thought": "OData: 3 последних входящих документа из 1С",
                "tool_name": "onec.odata_get",
                "payload": {
                    "path": "/Document_ТД_ВходящаяКорреспонденция?$top=3",
                    "entity": "Document_ТД_ВходящаяКорреспонденция",
                    "top": 3,
                    "subsystem": "document_flow",
                },
            },
        ],
    },
    "imap_omto": {
        "title": "IMAP: письма пользователя omto",
        "description": "Поиск с фильтром user=omto и чтение 3 последних сообщений",
        "agent_id": "sandbox-imap",
        "tool_calls": [
            {
                "thought": "Ищу письма для пользователя omto",
                "tool_name": "imap.search",
                "payload": {"query": "omto", "user": "omto", "limit": 3},
            },
            {
                "thought": "Читаю сообщение 1/3",
                "tool_name": "imap.fetch_message",
                "payload": {"uid": 8801, "user": "omto"},
            },
            {
                "thought": "Читаю сообщение 2/3",
                "tool_name": "imap.fetch_message",
                "payload": {"uid": 8802, "user": "omto"},
            },
            {
                "thought": "Читаю сообщение 3/3",
                "tool_name": "imap.fetch_message",
                "payload": {"uid": 8803, "user": "omto"},
            },
        ],
    },
    "browser_rostov_news": {
        "title": "Browser: новости Ростова-на-Дону",
        "description": "Навигация и извлечение текста с новостной страницы",
        "agent_id": "sandbox-browser",
        "tool_calls": [
            {
                "thought": "Открываю ephemeral browser session",
                "tool_name": "browser.open_session",
                "payload": {},
            },
            {
                "thought": "Открываю ленту новостей Ростова-на-Дону",
                "tool_name": "browser.navigate",
                "payload": {"url": "https://161.ru/text/", "topic": "rostov_news"},
            },
            {
                "thought": "Извлекаю заголовки последних новостей",
                "tool_name": "browser.extract_text",
                "payload": {
                    "url": "https://161.ru/text/",
                    "selector": "body",
                    "topic": "rostov_news",
                },
            },
            {
                "thought": "Закрываю browser session",
                "tool_name": "browser.close_session",
                "payload": {},
            },
        ],
    },
    "shell_ls": {
        "title": "Shell: ls",
        "description": "Вывод команды ls в sandbox workspace",
        "agent_id": "sandbox-shell",
        "tool_calls": [
            {
                "thought": "Список файлов в рабочей директории агента",
                "tool_name": "shell.run",
                "payload": {"command": "ls"},
            },
        ],
    },
    "shell_native_dir": {
        "title": "Shell native: dir",
        "description": "Команда dir на Windows host (:7828)",
        "agent_id": "sandbox-shell-native",
        "tool_calls": [
            {
                "thought": "Список файлов в native shell workspace",
                "tool_name": "shell.run",
                "payload": {"command": "dir", "runtime": "native"},
            },
        ],
    },
    "fs_list": {
        "title": "Filesystem: list",
        "description": "Список файлов в allowlist-корне на Windows host (:7827)",
        "agent_id": "sandbox-fs",
        "tool_calls": [
            {
                "thought": "Список файлов в корне allowlist",
                "tool_name": "fs.list",
                "payload": {"path": "."},
            },
        ],
    },
    "com_list_apps": {
        "title": "COM: list apps",
        "description": "Зарегистрированные COM-приложения на Windows host (:7826)",
        "agent_id": "sandbox-com",
        "tool_calls": [
            {
                "thought": "Список доступных COM-приложений",
                "tool_name": "com.list_apps",
                "payload": {},
            },
        ],
    },
    "com_outlook_calendar": {
        "title": "COM Outlook: календарь",
        "description": "Запуск Outlook и список встреч на 7 дней (:7826)",
        "agent_id": "sandbox-com-outlook",
        "tool_calls": [
            {
                "thought": "Запускаю Outlook через COM",
                "tool_name": "com.outlook.launch",
                "payload": {"visible": False},
            },
            {
                "thought": "Читаю календарь на ближайшую неделю",
                "tool_name": "com.outlook.calendar_list",
                "payload": {"days": 7, "limit": 20},
            },
            {
                "thought": "Закрываю COM-сессию Outlook",
                "tool_name": "com.outlook.close",
                "payload": {"quit": False},
            },
        ],
    },
}

SANDBOX_ORDER = (
    "onec_incoming",
    "imap_omto",
    "browser_rostov_news",
    "shell_ls",
    "shell_native_dir",
    "fs_list",
    "com_list_apps",
    "com_outlook_calendar",
)


def list_sandbox_tests() -> list[dict[str, Any]]:
    return [
        {
            "id": test_id,
            "title": scenario["title"],
            "description": scenario["description"],
            "agent_id": scenario["agent_id"],
            "tool_count": len(scenario["tool_calls"]),
            "tools": [call["tool_name"] for call in scenario["tool_calls"]],
            "category": test_id.split("_", 1)[0],
        }
        for test_id in SANDBOX_ORDER
        for scenario in [SANDBOX_TESTS[test_id]]
    ]


def get_sandbox_test(test_id: str) -> MockScenario:
    try:
        return SANDBOX_TESTS[test_id]
    except KeyError as exc:
        raise KeyError(f"Unknown sandbox test: {test_id}") from exc

"""Каталог схем инструментов для агента.

Исполнение desktop-tools — на клиенте (SSE tool_request).
IMAP — только на сервере (см. agent_runtime._invoke_imap_server).
"""

from __future__ import annotations

from typing import Any


class LocalMcpError(RuntimeError):
    pass


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "web_search",
            "description": (
                "Быстрый веб-поиск (DuckDuckGo/Wikipedia) без браузера. "
                "Исполняется на desktop пользователя."
            ),
            "execution": "desktop",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                    "fetch_top": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        },
        {
            "name": "site_browser",
            "description": (
                "Универсальный парсер любого сайта через Playwright Chromium. "
                "Исполняется на desktop пользователя."
            ),
            "execution": "desktop",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "extract", "search"],
                        "default": "open",
                    },
                    "url": {"type": "string"},
                    "query": {"type": "string"},
                    "wait_ms": {"type": "integer", "default": 0},
                    "wait_selector": {"type": "string"},
                    "input_selector": {"type": "string"},
                    "submit_selector": {"type": "string"},
                    "item_selector": {"type": "string"},
                    "title_selector": {"type": "string"},
                    "link_selector": {"type": "string"},
                    "max_items": {"type": "integer", "default": 30},
                    "headless": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
        },
        {
            "name": "imap.list_unread",
            "description": "Список непрочитанных писем (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "user": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
        {
            "name": "imap.search",
            "description": "Поиск писем по критериям (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "user": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
        {
            "name": "imap.fetch_message",
            "description": "Загрузить письмо по uid (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "uid": {"type": "integer"},
                    "message_id": {"type": "integer"},
                    "user": {"type": "string"},
                },
            },
        },
        {
            "name": "imap.fetch_attachments",
            "description": "Список вложений письма по uid (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "uid": {"type": "integer"},
                    "message_id": {"type": "integer"},
                    "user": {"type": "string"},
                },
            },
        },
        {
            "name": "onec.odata_get",
            "description": "Чтение сущности/пути 1С OData (сервер).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "path": {"type": "string"},
                    "top": {
                        "type": "integer",
                        "default": 3,
                        "description": "OData $top — сколько записей вернуть",
                    },
                    "skip": {
                        "type": "integer",
                        "default": 0,
                        "description": "OData $skip — смещение (сколько записей пропустить)",
                    },
                },
            },
        },
        {
            "name": "onec.odata_post",
            "description": "Создание объекта через 1С OData (сервер).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "body": {"type": "object"},
                },
                "required": ["entity"],
            },
        },
        {
            "name": "onec.odata_patch",
            "description": "Обновление объекта через 1С OData (сервер).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "ref_key": {"type": "string"},
                    "body": {"type": "object"},
                },
                "required": ["entity", "ref_key"],
            },
        },
        {
            "name": "onec.attach_file",
            "description": "Прикрепление файла к документу 1С (пока не реализовано).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_ref_key": {"type": "string"},
                    "filename": {"type": "string"},
                },
            },
        },
        {
            "name": "onec.sql_query",
            "description": "Только SELECT к ERP SQL (allowlist таблиц, сервер).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
        *_desktop_ac_tools(),
    ]


def _desktop_ac_tools() -> list[dict[str, Any]]:
    """Схемы ported desktop-инструментов (исполнение на клиенте)."""
    items: list[tuple[str, str, dict[str, Any]]] = [
        ("outlook.search_mail", "Поиск писем Outlook через COM на desktop.", {
            "folder": {"type": "string"},
            "date": {"type": "string"},
            "date_from": {"type": "string"},
            "date_to": {"type": "string"},
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        }),
        ("outlook.read_calendar", "Чтение календаря Outlook через COM на desktop.", {
            "date": {"type": "string"},
            "date_from": {"type": "string"},
            "date_to": {"type": "string"},
            "days_forward": {"type": "integer"},
            "max_results": {"type": "integer"},
        }),
        ("browser.list_installed_browsers", "Список установленных браузеров на desktop.", {}),
        ("browser.open_browser", "Открыть установленный браузер (штатный профиль).", {
            "browser_id": {"type": "string"},
            "url": {"type": "string"},
        }),
        ("browser.search_web", "Веб-поиск DuckDuckGo на desktop.", {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        }),
        ("browser.open_page", "Прочитать web-страницу через CDP на desktop.", {
            "url": {"type": "string"},
            "max_chars": {"type": "integer"},
            "browser_id": {"type": "string"},
        }),
        ("browser.extract_table", "Извлечь таблицы со страницы на desktop.", {
            "url": {"type": "string"},
            "table_hint": {"type": "string"},
        }),
        ("browser.scroll_page", "Прокрутить страницу и прочитать текст.", {
            "url": {"type": "string"},
            "direction": {"type": "string"},
            "pixels": {"type": "integer"},
        }),
        ("browser.click_link", "Перейти по ссылке на странице.", {
            "url": {"type": "string"},
            "link_text": {"type": "string"},
            "href": {"type": "string"},
        }),
        ("browser.navigate", "Открыть URL в управляемом браузере (скриншот).", {
            "url": {"type": "string"},
            "browser_id": {"type": "string"},
        }),
        ("browser.screenshot", "Скриншот текущей вкладки браузера.", {
            "browser_id": {"type": "string"},
        }),
        ("browser.get_page_html", "HTML текущей вкладки через CDP.", {
            "url": {"type": "string"},
            "max_chars": {"type": "integer"},
        }),
        ("browser.dump_page_source", "Выгрузить HTML+CSS страницы в папку агента.", {
            "url": {"type": "string"},
            "dump_name": {"type": "string"},
        }),
        ("browser.click", "Клик по координатам в браузере.", {
            "x": {"type": "number"},
            "y": {"type": "number"},
        }),
        ("browser.type_text", "Ввод текста в активное поле браузера.", {
            "text": {"type": "string"},
        }),
        ("browser.press_key", "Нажатие клавиши в браузере.", {
            "key": {"type": "string"},
        }),
        ("browser.scroll", "Прокрутка вкладки браузера (UI).", {
            "direction": {"type": "string"},
            "pixels": {"type": "integer"},
        }),
        ("onec.search_documents", "Поиск документов 1С (desktop COM/read-only).", {
            "document_type": {"type": "string"},
            "number": {"type": "string"},
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        }),
        ("onec.get_document_card", "Карточка документа 1С на desktop.", {
            "document_ref": {"type": "string"},
        }),
        ("onec.search_tasks", "Поиск задач 1С на desktop.", {
            "query": {"type": "string"},
            "status": {"type": "string"},
            "max_results": {"type": "integer"},
        }),
        ("onec.get_task_card", "Карточка задачи 1С на desktop.", {
            "task_ref": {"type": "string"},
        }),
        ("excel.list_files", "Список файлов в рабочей папке агента.", {}),
        ("excel.read_workbook", "Чтение .xlsx из папки агента.", {
            "filename": {"type": "string"},
            "sheet": {"type": "string"},
            "max_rows": {"type": "integer"},
        }),
        ("excel.create_workbook", "Создать .xlsx в папке агента.", {
            "filename": {"type": "string"},
            "headers": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array"},
        }),
        ("excel.edit_workbook", "Изменить .xlsx в папке агента.", {
            "filename": {"type": "string"},
            "operations": {"type": "array"},
        }),
        ("workspace.powershell_run", "PowerShell только в папке агента.", {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
        }),
        ("code.write_python", "Сохранить .py в папку code агента.", {
            "code": {"type": "string"},
            "filename": {"type": "string"},
        }),
        ("code.run_python", "Запустить .py из папки агента.", {
            "filename": {"type": "string"},
            "code": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
        }),
        ("agent.wait", "Пауза агента на N секунд.", {
            "seconds": {"type": "number"},
        }),
        ("report.build_task_report", "Собрать отчёт по поручениям из собранных данных.", {}),
        ("report.build_meeting_summary", "Сводка/протокол совещания из собранных данных.", {}),
        ("report.build_schedule_recommendations", "Рекомендации по графику из календаря.", {}),
        ("users.list", "Список пользователей Constructor: id, ФИО, должность, подразделение. Вызови перед notify.send, чтобы выбрать получателя.", {
            "query": {"type": "string"},
        }, []),
        ("notify.send", "Отправить уведомление пользователю (сразу или в указанное время). user_id бери из инструмента users.list — не выдумывай id.", {
            "user_id": {"type": "string", "description": "id получателя из users.list"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "send_at": {"type": "string"},
            "workflow_id": {"type": "string"},
        }, ["user_id", "title"]),
        ("agent.schedule", "Запланировать запуск агента: в момент at (ISO), через after_seconds, или когда выполнится condition (свободный текст: файл, письмо, любое событие). Пустой workflow_id = текущий агент.", {
            "workflow_id": {"type": "string"},
            "message": {"type": "string"},
            "at": {"type": "string"},
            "after_seconds": {"type": "number"},
            "condition": {"type": "string"},
            "once": {"type": "boolean"},
        }, []),
        ("agent.schedule.cancel", "Отменить ранее созданный триггер agent.schedule по trigger_id.", {
            "trigger_id": {"type": "string"},
        }, ["trigger_id"]),
    ]
    tools: list[dict[str, Any]] = []
    for item in items:
        name, description, properties = item[0], item[1], item[2]
        required = list(item[3]) if len(item) > 3 else []
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        tools.append(
            {
                "name": name,
                "description": description + " Исполняется на desktop пользователя.",
                "execution": "desktop",
                "input_schema": schema,
            }
        )
    return tools


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = arguments
    raise LocalMcpError(
        f"Инструмент «{name}» больше не исполняется через local_mcp.call_tool. "
        "Desktop-tools — SSE tool_request; imap.*/onec.* — серверные сервисы."
    )

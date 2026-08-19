"""Каталог схем инструментов для агента.

Исполнение desktop-tools — на клиенте (SSE tool_request).
IMAP — только на сервере (см. agent_runtime._invoke_imap_server).
"""

from __future__ import annotations

from typing import Any


class LocalMcpError(RuntimeError):
    pass


def _raw_tools() -> list[dict[str, Any]]:
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
            "name": "onec.odata_catalog",
            "description": (
                "Список доступных сущностей 1С OData: документы, справочники/таблицы и регистры. "
                "Сначала вызови этот инструмент, затем onec.odata_get с entity из ответа. "
                "Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": (
                            "Фильтр: document / catalog (таблицы, справочники) / register / other"
                        ),
                    },
                    "search": {
                        "type": "string",
                        "description": "Подстрока в имени сущности (Document_, Catalog_, *Register_)",
                    },
                    "limit": {"type": "integer", "default": 400},
                    "refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": "Сбросить кэш и заново прочитать service document / $metadata",
                    },
                },
            },
        },
        {
            "name": "onec.odata_get",
            "description": (
                "Чтение сущности/пути 1С OData (сервер). "
                "entity бери из onec.odata_catalog. Для карточки документа передай "
                "ref_key или path с guid — вернутся все реквизиты, не только номер/дата. "
                "Табличные части (участники и т.п.) подтягиваются как Entity_ИмяТЧ. "
                "Не выдумывай имена EntitySet."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Имя EntitySet из onec.odata_catalog, например Document_Проект",
                    },
            "path": {
                "type": "string",
                "description": "Путь OData, включая ключ: Document_Имя(guid'...')",
            },
            "ref_key": {
                "type": "string",
                "description": "GUID документа: читает карточку целиком, не список",
            },
            "number": {
                "type": "string",
                "description": "Номер документа. Один номер может повторяться по годам: вернутся свежие сначала, с темой и табличными частями.",
            },
            "filter": {
                "type": "string",
                "description": "OData $filter, например Number eq '000000001'",
            },
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
        {
            "name": "onec.erp_tasks_current",
            "description": (
                "Текущие (открытые) задачи пользователя из базы 1С erp_pm. "
                "ФИО берётся из JWT сессии Constructor; fio/user_id в аргументах не обязательны. "
                "Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50},
                    "fio": {
                        "type": "string",
                        "description": "Необязательно: чужое ФИО. Пусто — пользователь из JWT.",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Необязательно: id пользователя 1С. Пусто — из JWT.",
                    },
                },
            },
        },
        {
            "name": "onec.erp_tasks_period",
            "description": (
                "Задачи пользователя из erp_pm за период (дата создания). "
                "ФИО берётся из JWT, если не переданы fio/user_id. Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Начало периода YYYY-MM-DD",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Конец периода YYYY-MM-DD",
                    },
                    "include_done": {
                        "type": "boolean",
                        "default": True,
                        "description": "Включать выполненные задачи",
                    },
                    "limit": {"type": "integer", "default": 100},
                    "fio": {"type": "string"},
                    "user_id": {"type": "string"},
                },
                "required": ["date_from", "date_to"],
            },
        },
        {
            "name": "onec.erp_subordinate_tasks",
            "description": (
                "Дерево задач подчинённых из erp_pm и 1С:Документооборот: "
                "сначала руководитель (если include_self), затем непосредственные "
                "подчинённые (должность, задачи и сроки за период), затем "
                "подчинённые каждого из них и так далее. "
                "Только действующие назначения, без уволенных и переведённых. "
                "Человек из JWT сессии; можно передать access_token. "
                "Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "access_token": {
                        "type": "string",
                        "description": (
                            "JWT Constructor. Если пусто — берётся токен сессии "
                            "(Authorization Bearer)."
                        ),
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Начало периода YYYY-MM-DD. Пусто — 30 дней назад.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Конец периода YYYY-MM-DD. Пусто — сегодня.",
                    },
                    "only_open": {
                        "type": "boolean",
                        "default": False,
                        "description": "Только открытые задачи",
                    },
                    "include_done": {
                        "type": "boolean",
                        "default": True,
                        "description": "Включать выполненные задачи за период",
                    },
                    "limit_per_person": {
                        "type": "integer",
                        "default": 30,
                        "description": "Максимум задач на одного человека",
                    },
                    "include_self": {
                        "type": "boolean",
                        "default": True,
                        "description": "Включить руководителя (себя) отдельной строкой",
                    },
                },
            },
        },
        {
            "name": "onec.docflow_tasks",
            "description": (
                "Задачи пользователя из 1С:Документооборот (публикация /doc). "
                "ФИО из JWT сессии. Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Начало периода YYYY-MM-DD. Пусто — без нижней границы.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Конец периода YYYY-MM-DD. Пусто — без верхней границы.",
                    },
                    "only_open": {
                        "type": "boolean",
                        "default": True,
                        "description": "Только открытые задачи",
                    },
                    "include_done": {
                        "type": "boolean",
                        "description": "Включать выполненные задачи",
                    },
                    "limit": {"type": "integer", "default": 200},
                },
            },
        },
        {
            "name": "turboproject",
            "description": (
                "Проекты TurboProject с синхронизацией 1С. "
                "Карточка: имя, даты MSP/1С, статистика задач, просроченные задачи и вехи, "
                "ресурсы (ФИО), руководитель/куратор/заказчик и весь блок data_1c. "
                "Фильтры: query (имя/номер), manager (руководитель 1С), file_id, "
                "overdue_only, limit. Учётка на сервере. Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поиск по названию проекта, имени MPP или номеру 1С",
                    },
                    "manager": {
                        "type": "string",
                        "description": "ФИО руководителя проекта из 1С (data_1c.rukovoditel)",
                    },
                    "file_id": {
                        "type": "string",
                        "description": "ID файла проекта (ProjectFile.id)",
                    },
                    "overdue_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Только проекты с просроченными задачами или вехами",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Максимум проектов в ответе (пусто — все, не больше 200)",
                    },
                },
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
        ("notify.send", "Отправить уведомление на компьютер получателя (Windows-тост + inbox). user_id бери из users.list — не выдумывай id. Если человек просил уведомления — вызови этот tool до RESULT.", {
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
    server_tools = {"users.list", "notify.send"}
    tools: list[dict[str, Any]] = []
    for item in items:
        name, description, properties = item[0], item[1], item[2]
        required = list(item[3]) if len(item) > 3 else []
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        if name in server_tools:
            suffix = " Исполняется на сервере Constructor."
            execution = "server"
        else:
            suffix = " Исполняется на desktop пользователя."
            execution = "desktop"
        tools.append(
            {
                "name": name,
                "description": description + suffix,
                "execution": execution,
                "input_schema": schema,
            }
        )
    return tools


SYSTEMS = ("onec", "turboproject", "outlook", "imap", "web", "desktop", "constructor")
OPERATIONS = (
    "search",
    "read",
    "list",
    "create",
    "update",
    "delete",
    "export",
    "notify",
    "execute",
)

# Контракт нужен подбору инструментов и валидации ответа: по названию совместимость
# определить нельзя (web_search и onec.sql_query «оба ищут»).
_CONTRACTS: dict[str, tuple[str, str, str, list[str], list[str], str]] = {
    # name: (system, entity, operation, required_filters, result_fields, pagination)
    "web_search": ("web", "web_page", "search", ["query"], ["results"], "none"),
    "site_browser": ("web", "web_page", "search", ["url"], ["items", "text"], "none"),
    "imap.list_unread": ("imap", "mail_message", "list", [], ["messages"], "count"),
    "imap.search": ("imap", "mail_message", "search", ["query"], ["messages"], "count"),
    "imap.fetch_message": ("imap", "mail_message", "read", ["uid"], ["subject", "body"], "none"),
    "imap.fetch_attachments": ("imap", "mail_attachment", "list", ["uid"], ["files"], "none"),
    "onec.odata_catalog": ("onec", "metadata", "list", [], ["entities"], "count"),
    "onec.odata_get": ("onec", "odata_entity", "read", ["entity"], ["rows", "value"], "cursor"),
    "onec.odata_post": ("onec", "odata_entity", "create", ["entity"], ["ref_key"], "none"),
    "onec.odata_patch": (
        "onec",
        "odata_entity",
        "update",
        ["entity", "ref_key"],
        ["ref_key"],
        "none",
    ),
    "onec.attach_file": (
        "onec",
        "file",
        "create",
        ["document_ref_key", "filename"],
        [],
        "none",
    ),
    "onec.sql_query": ("onec", "sql_table", "search", ["sql"], ["rows"], "count"),
    "onec.erp_tasks_current": ("onec", "task", "list", [], ["tasks"], "count"),
    "onec.erp_tasks_period": (
        "onec",
        "task",
        "list",
        ["date_from", "date_to"],
        ["tasks"],
        "count",
    ),
    "onec.erp_subordinate_tasks": ("onec", "task", "list", [], ["tree"], "count"),
    "onec.docflow_tasks": ("onec", "task", "list", [], ["tasks"], "count"),
    "onec.search_documents": ("onec", "document", "search", [], ["documents"], "count"),
    "onec.get_document_card": (
        "onec",
        "document",
        "read",
        ["document_ref"],
        ["document"],
        "none",
    ),
    "onec.search_tasks": ("onec", "task", "search", [], ["tasks"], "count"),
    "onec.get_task_card": ("onec", "task", "read", ["task_ref"], ["task"], "none"),
    "turboproject": ("turboproject", "project", "search", [], ["projects"], "count"),
    "outlook.search_mail": ("outlook", "mail_message", "search", [], ["messages"], "count"),
    "outlook.read_calendar": ("outlook", "calendar_event", "list", [], ["events"], "count"),
    "browser.list_installed_browsers": ("web", "browser", "list", [], ["items"], "none"),
    "browser.open_browser": ("web", "browser", "execute", ["browser_id"], [], "none"),
    "browser.search_web": ("web", "web_page", "search", ["query"], ["results"], "none"),
    "browser.open_page": ("web", "web_page", "read", ["url"], ["text"], "none"),
    "browser.extract_table": ("web", "web_page", "read", ["url"], ["items"], "none"),
    "browser.scroll_page": ("web", "web_page", "read", ["url"], ["text"], "none"),
    "browser.click_link": ("web", "web_page", "execute", ["url"], ["text"], "none"),
    "browser.navigate": ("web", "web_page", "execute", ["url"], [], "none"),
    "browser.screenshot": ("web", "web_page", "read", [], ["file"], "none"),
    "browser.get_page_html": ("web", "web_page", "read", ["url"], ["text"], "none"),
    "browser.dump_page_source": ("web", "web_page", "export", ["url"], ["files"], "none"),
    "browser.click": ("web", "web_page", "execute", ["x", "y"], [], "none"),
    "browser.type_text": ("web", "web_page", "execute", ["text"], [], "none"),
    "browser.press_key": ("web", "web_page", "execute", ["key"], [], "none"),
    "browser.scroll": ("web", "web_page", "execute", [], [], "none"),
    "excel.list_files": ("desktop", "file", "list", [], ["files"], "none"),
    "excel.read_workbook": ("desktop", "spreadsheet", "read", ["filename"], ["rows"], "count"),
    "excel.create_workbook": ("desktop", "spreadsheet", "export", ["filename"], ["file"], "none"),
    "excel.edit_workbook": ("desktop", "spreadsheet", "export", ["filename"], ["file"], "none"),
    "workspace.powershell_run": ("desktop", "shell", "execute", ["command"], ["text"], "none"),
    "code.write_python": ("desktop", "code", "create", ["code"], ["file"], "none"),
    "code.run_python": ("desktop", "code", "execute", [], ["text"], "none"),
    "agent.wait": ("constructor", "agent", "execute", ["seconds"], [], "none"),
    "report.build_task_report": ("desktop", "report", "export", [], ["file"], "none"),
    "report.build_meeting_summary": ("desktop", "report", "export", [], ["file"], "none"),
    "report.build_schedule_recommendations": ("desktop", "report", "export", [], ["file"], "none"),
    "users.list": ("constructor", "user", "list", [], ["users"], "count"),
    "notify.send": (
        "constructor",
        "notification",
        "notify",
        ["user_id", "title"],
        ["id", "delivered"],
        "none",
    ),
    "agent.schedule": ("constructor", "trigger", "create", [], ["trigger_id"], "none"),
    "agent.schedule.cancel": ("constructor", "trigger", "delete", ["trigger_id"], [], "none"),
}


def _contract_for(name: str, execution: str) -> dict[str, Any]:
    system, entity, operation, filters, fields, pagination = _CONTRACTS.get(
        name, (execution or "desktop", "", "execute", [], [], "none")
    )
    return {
        "system": system,
        "entity": entity,
        "operation": operation,
        "required_filters": list(filters),
        "result_fields": list(fields),
        "pagination": pagination,
    }


def list_tools() -> list[dict[str, Any]]:
    """Каталог с контрактами: по ним идёт подбор инструмента и проверка ответа."""
    tools: list[dict[str, Any]] = []
    for tool in _raw_tools():
        name = str(tool.get("name") or "")
        tools.append({**tool, **_contract_for(name, str(tool.get("execution") or ""))})
    return tools


def tool_contracts() -> dict[str, dict[str, Any]]:
    return {str(tool["name"]): tool for tool in list_tools() if tool.get("name")}


def candidates_for(
    *,
    system: str = "",
    entity: str = "",
    operation: str = "",
) -> list[dict[str, Any]]:
    """Инструменты, совместимые по системе, сущности и операции."""
    wanted_system = (system or "").strip().casefold()
    wanted_entity = (entity or "").strip().casefold()
    wanted_operation = (operation or "").strip().casefold()
    found: list[dict[str, Any]] = []
    for tool in list_tools():
        if wanted_system and str(tool.get("system") or "").casefold() != wanted_system:
            continue
        if wanted_operation and str(tool.get("operation") or "").casefold() != wanted_operation:
            continue
        if wanted_entity:
            tool_entity = str(tool.get("entity") or "").casefold()
            if tool_entity != wanted_entity and wanted_entity not in tool_entity:
                continue
        found.append(tool)
    return found


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = arguments
    raise LocalMcpError(
        f"Инструмент «{name}» больше не исполняется через local_mcp.call_tool. "
        "Desktop-tools — SSE tool_request; imap.*/onec.* — серверные сервисы."
    )

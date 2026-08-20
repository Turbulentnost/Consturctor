"""Каталог схем инструментов для агента.

Исполнение desktop-tools — на клиенте (SSE tool_request).
IMAP — только на сервере (см. agent_runtime._invoke_imap_server).
"""

from __future__ import annotations

from typing import Any


class LocalMcpError(RuntimeError):
    pass


def _prop(typ: str, description: str, **extra: Any) -> dict[str, Any]:
    field: dict[str, Any] = {"type": typ, "description": description}
    field.update(extra)
    return field


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
                    "query": _prop("string", "Что искать в вебе — короткая фраза, не ТЗ агента"),
                    "max_results": _prop("integer", "Сколько ссылок вернуть", default=5),
                    "fetch_top": _prop(
                        "boolean", "Если true — ещё скачать текст первой ссылки", default=False
                    ),
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
                    "action": _prop(
                        "string",
                        "open — открыть страницу, extract — вытащить блоки, search — поиск на сайте",
                        enum=["open", "extract", "search"],
                        default="open",
                    ),
                    "url": _prop("string", "Полный URL страницы, начиная с https://"),
                    "query": _prop("string", "Текст поиска на сайте, только для action=search"),
                    "wait_ms": _prop("integer", "Пауза после загрузки, миллисекунды", default=0),
                    "wait_selector": _prop("string", "CSS-селектор, которого ждать"),
                    "input_selector": _prop("string", "CSS поля ввода для search"),
                    "submit_selector": _prop("string", "CSS кнопки отправки поиска"),
                    "item_selector": _prop("string", "CSS карточки результата"),
                    "title_selector": _prop("string", "CSS заголовка внутри карточки"),
                    "link_selector": _prop("string", "CSS ссылки внутри карточки"),
                    "max_items": _prop("integer", "Максимум карточек", default=30),
                    "headless": _prop("boolean", "Без окна браузера", default=True),
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
                    "limit": _prop("integer", "Сколько писем вернуть", default=20),
                    "user": _prop("string", "Ящик. Пусто — ящик сессии"),
                    "query": _prop("string", "Подстрока в теме или отправителе, не свободное ТЗ"),
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
                    "query": _prop("string", "Текст поиска в теме или отправителе"),
                    "user": _prop("string", "Ящик. Пусто — ящик сессии"),
                    "limit": _prop("integer", "Сколько писем вернуть", default=50),
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
                    "uid": _prop("integer", "uid письма из imap.list_unread или imap.search"),
                    "message_id": _prop("integer", "Альтернатива uid: внутренний id письма"),
                    "user": _prop("string", "Ящик. Пусто — ящик сессии"),
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
                    "uid": _prop("integer", "uid письма из imap.list_unread или imap.search"),
                    "message_id": _prop("integer", "Альтернатива uid: внутренний id письма"),
                    "user": _prop("string", "Ящик. Пусто — ящик сессии"),
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
                    "limit": _prop("integer", "Максимум сущностей в списке", default=400),
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
                    "entity": _prop("string", "Имя EntitySet из onec.odata_catalog"),
                    "body": _prop("object", "Поля нового объекта 1С, как в OData"),
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
                    "entity": _prop("string", "Имя EntitySet из onec.odata_catalog"),
                    "ref_key": _prop("string", "GUID объекта, который меняем"),
                    "body": _prop("object", "Только поля, которые нужно изменить"),
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
                    "document_ref_key": _prop("string", "GUID документа 1С"),
                    "filename": _prop("string", "Имя файла в папке агента"),
                },
            },
        },
        {
            "name": "onec.sql_query",
            "description": "Только SELECT к ERP SQL (allowlist таблиц, сервер).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": _prop("string", "Один SELECT. Таблицы только из allowlist, без INSERT/UPDATE"),
                },
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
                    "limit": _prop("integer", "Максимум задач", default=50),
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
                    "limit": _prop("integer", "Максимум задач", default=100),
                    "fio": _prop("string", "Чужое ФИО. Пусто — пользователь из JWT"),
                    "user_id": _prop("string", "id пользователя 1С. Пусто — из JWT"),
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
                    "limit": _prop("integer", "Максимум задач", default=200),
                },
            },
        },
        {
            "name": "turboproject",
            "description": (
                "Проекты TurboProject с синхронизацией 1С. "
                "Карточка: имя, даты MSP/1С, статистика задач, просроченные задачи и вехи, "
                "ресурсы (ФИО), руководитель/куратор/заказчик и весь блок data_1c. "
                "Фильтры: query (только название / имя MPP / номер 1С, не фраза), "
                "manager (одно ФИО руководителя 1С), file_id, overdue_only, limit. "
                "Учётка на сервере. Исполняется на сервере."
            ),
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Название проекта, имя MPP или номер 1С — не фраза "
                            "и не список участников"
                        ),
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
            "folder": _prop("string", "Папка Outlook, например Inbox"),
            "date": _prop("string", "Один день YYYY-MM-DD"),
            "date_from": _prop("string", "Начало периода YYYY-MM-DD"),
            "date_to": _prop("string", "Конец периода YYYY-MM-DD"),
            "query": _prop("string", "Подстрока в теме или отправителе, не список людей"),
            "max_results": _prop("integer", "Максимум писем"),
        }),
        ("outlook.read_calendar", "Все запланированные встречи Outlook за период. Без дат — ближайший год с сегодня, не неделя. В ответе events и free_slots.", {
            "date": _prop("string", "Один день YYYY-MM-DD"),
            "date_from": _prop("string", "Начало периода YYYY-MM-DD"),
            "date_to": _prop("string", "Конец периода YYYY-MM-DD"),
            "days_forward": _prop("integer", "Сколько дней вперёд от сегодня, если дат нет. По умолчанию 365"),
            "max_results": _prop("integer", "Максимум событий, до 500"),
        }),
        ("outlook.create_event", "Создать встречи в свободных слотах календаря Outlook. Тема и текст помечаются как ИИ-агент. Нужно подтверждение человека.", {
            "subject": _prop("string", "Тема встречи без префикса ИИ-агент — его добавит инструмент"),
            "start": _prop("string", "Начало ISO datetime, слот должен быть свободным"),
            "end": _prop("string", "Конец ISO datetime"),
            "duration_minutes": _prop("integer", "Длительность в минутах, если end нет"),
            "body": _prop("string", "Текст встречи; в конец добавится подпись ИИ-агента"),
            "location": _prop("string", "Место или ссылка"),
            "events": _prop(
                "array",
                "Несколько встреч за один вызов: subject, start, end или duration_minutes",
            ),
        }),
        ("browser.list_installed_browsers", "Список установленных браузеров на desktop.", {}),
        ("browser.open_browser", "Открыть установленный браузер (штатный профиль).", {
            "browser_id": _prop("string", "id браузера из browser.list_installed_browsers"),
            "url": _prop("string", "Необязательный URL для открытия"),
        }),
        ("browser.search_web", "Веб-поиск DuckDuckGo на desktop.", {
            "query": _prop("string", "Что искать — короткая фраза"),
            "max_results": _prop("integer", "Сколько ссылок вернуть"),
        }),
        ("browser.open_page", "Прочитать web-страницу через CDP на desktop.", {
            "url": _prop("string", "Полный URL, начиная с https://"),
            "max_chars": _prop("integer", "Обрезать текст страницы до N символов"),
            "browser_id": _prop("string", "id браузера. Пусто — текущий"),
        }),
        ("browser.extract_table", "Извлечь таблицы со страницы на desktop.", {
            "url": _prop("string", "Полный URL страницы с таблицей"),
            "table_hint": _prop("string", "Подсказка: заголовок или текст рядом с таблицей"),
        }),
        ("browser.scroll_page", "Прокрутить страницу и прочитать текст.", {
            "url": _prop("string", "URL открытой страницы"),
            "direction": _prop("string", "down или up"),
            "pixels": _prop("integer", "На сколько пикселей прокрутить"),
        }),
        ("browser.click_link", "Перейти по ссылке на странице.", {
            "url": _prop("string", "URL текущей страницы"),
            "link_text": _prop("string", "Видимый текст ссылки"),
            "href": _prop("string", "Адрес ссылки, если текст неизвестен"),
        }),
        ("browser.navigate", "Открыть URL в управляемом браузере (скриншот).", {
            "url": _prop("string", "Полный URL"),
            "browser_id": _prop("string", "id браузера. Пусто — текущий"),
        }),
        ("browser.screenshot", "Скриншот текущей вкладки браузера.", {
            "browser_id": _prop("string", "id браузера. Пусто — текущий"),
        }),
        ("browser.get_page_html", "HTML текущей вкладки через CDP.", {
            "url": _prop("string", "URL страницы"),
            "max_chars": _prop("integer", "Обрезать HTML до N символов"),
        }),
        ("browser.dump_page_source", "Выгрузить HTML+CSS страницы в папку агента.", {
            "url": _prop("string", "URL страницы"),
            "dump_name": _prop("string", "Имя папки выгрузки в каталоге агента"),
        }),
        ("browser.click", "Клик по координатам в браузере.", {
            "x": _prop("number", "Координата X в пикселях"),
            "y": _prop("number", "Координата Y в пикселях"),
        }),
        ("browser.type_text", "Ввод текста в активное поле браузера.", {
            "text": _prop("string", "Текст для ввода"),
        }),
        ("browser.press_key", "Нажатие клавиши в браузере.", {
            "key": _prop("string", "Клавиша, например Enter или Tab"),
        }),
        ("browser.scroll", "Прокрутка вкладки браузера (UI).", {
            "direction": _prop("string", "down или up"),
            "pixels": _prop("integer", "На сколько пикселей прокрутить"),
        }),
        ("onec.search_documents", "Поиск документов 1С (desktop, 32-bit COMConnector через cscript, не 32-bit Python).", {
            "document_type": _prop("string", "Вид документа 1С, если известен"),
            "number": _prop("string", "Номер документа"),
            "query": _prop("string", "Подстрока в номере или названии, не фраза-ТЗ"),
            "max_results": _prop("integer", "Максимум документов"),
        }),
        ("onec.get_document_card", "Карточка документа 1С на desktop (32-bit COMConnector через cscript).", {
            "document_ref": _prop("string", "Ссылка или номер из onec.search_documents / onec.meeting_service_notes"),
            "number": _prop("string", "Номер документа, например 000013243"),
            "query": _prop("string", "Номер или подстрока, если ссылки нет"),
        }),
        ("onec.search_tasks", "Поиск задач 1С на desktop.", {
            "query": _prop("string", "Подстрока в названии задачи"),
            "status": _prop("string", "Статус, если нужен фильтр"),
            "max_results": _prop("integer", "Максимум задач"),
        }),
        ("onec.get_task_card", "Карточка задачи 1С на desktop.", {
            "task_ref": _prop("string", "Ссылка задачи из onec.search_tasks"),
        }),
        (
            "onec.meeting_service_notes",
            "Только чтение COM через 32-bit V83.COMConnector (cscript), без py -3.12-32. "
            "Служебные записки 1С с темой «организация совещаний». "
            "В ответе: тема СЗ, тема совещания, место, желаемые дата/время/длительность, "
            "руководитель, приоритет, периодичность, вид, ПСД. date или date_from/date_to. "
            "Ничего не записывает и не меняет в 1С.",
            {
                "date": _prop("string", "Один день YYYY-MM-DD"),
                "date_from": _prop("string", "Начало периода YYYY-MM-DD"),
                "date_to": _prop("string", "Конец периода YYYY-MM-DD"),
                "fio": _prop("string", "Кому направлены. Пусто — пользователь COM-сессии"),
                "max_results": _prop("integer", "Максимум записок, не больше 200"),
            },
        ),
        ("excel.list_files", "Список файлов в рабочей папке агента.", {}),
        ("excel.read_workbook", "Чтение .xlsx из папки агента.", {
            "filename": _prop("string", "Имя файла в папке агента, например report.xlsx"),
            "sheet": _prop("string", "Имя листа. Пусто — первый"),
            "max_rows": _prop("integer", "Максимум строк"),
        }),
        ("excel.create_workbook", "Создать или перезаписать .xlsx в папке агента. Если файл уже есть — перезапишет, отдельный overwrite не нужен.", {
            "filename": _prop("string", "Имя файла, например report.xlsx"),
            "headers": _prop("array", "Заголовки колонок", items={"type": "string"}),
            "rows": _prop("array", "Строки таблицы: список списков или объектов"),
        }),
        ("excel.edit_workbook", "Изменить .xlsx в папке агента. Можно operations или сразу headers+rows (тогда файл перезапишется).", {
            "filename": _prop("string", "Имя файла в папке агента"),
            "operations": _prop(
                "array",
                "Правки листа: action add_sheet, delete_sheet, append_row или set_cell. Не export.",
            ),
            "headers": _prop("array", "Если нет operations — заголовки для полной перезаписи"),
            "rows": _prop("array", "Если нет operations — строки для полной перезаписи"),
        }),
        ("workspace.powershell_run", "PowerShell только в папке агента.", {
            "command": _prop("string", "Команда PowerShell без выхода из папки агента"),
            "timeout_seconds": _prop("integer", "Таймаут выполнения"),
        }),
        ("code.write_python", "Сохранить .py в папку code агента.", {
            "code": _prop("string", "Текст программы Python"),
            "filename": _prop("string", "Имя файла, например script.py"),
        }),
        ("code.run_python", "Запустить .py из папки агента.", {
            "filename": _prop("string", "Имя файла из папки code"),
            "code": _prop("string", "Либо сам код, если файла ещё нет"),
            "timeout_seconds": _prop("integer", "Таймаут выполнения"),
        }),
        ("agent.wait", "Пауза агента на N секунд.", {
            "seconds": _prop("number", "Сколько секунд ждать"),
        }),
        (
            "data.process",
            "Обработать полный ответ предыдущего инструмента коротким Python: "
            "в коде доступны data и нужно присвоить result. "
            "dataset_id бери из усечённого ответа. Исполняется на сервере.",
            {
                "code": _prop("string", "Короткий Python: есть data, присвой result"),
                "dataset_id": _prop("string", "id набора из предыдущего ответа, например d1"),
            },
            ["code"],
        ),
        ("report.build_task_report", "Собрать отчёт по поручениям из собранных данных.", {}),
        ("report.build_meeting_summary", "Сводка/протокол совещания из собранных данных.", {}),
        ("report.build_schedule_recommendations", "Рекомендации по графику из календаря.", {}),
        ("users.current", "Текущий пользователь сессии Constructor: id, ФИО, должность, подразделение. Если регламент говорит «текущий пользователь», «данный пользователь» или «мои данные» — вызови этот tool, не спрашивай человека.", {}),
        ("users.list", "Список пользователей Constructor: id, ФИО, должность, подразделение. Вызови перед notify.send, чтобы выбрать получателя.", {
            "query": _prop("string", "ФИО, email или id — не роль и не «все» / «получатели»"),
        }, []),
        (
            "users.subordinates",
            "Подчинённые руководителя из оргструктуры erp_pm: ФИО, должность, подразделение. "
            "Не зависит от регистрации в Constructor. Пустой fio — текущий пользователь сессии.",
            {
                "fio": _prop("string", "ФИО руководителя. Пусто — текущий пользователь"),
                "user_id": _prop("string", "id из сессии или 1С. Пусто — текущий пользователь"),
            },
            [],
        ),
        ("notify.send", "Отправить уведомление на компьютер получателя (Windows-тост + inbox). user_id бери из users.list — не выдумывай id. Подтверждение человека не нужно: вызывай сразу, не откладывай. Если человек просил уведомления — вызови этот tool до RESULT.", {
            "user_id": _prop("string", "id получателя из users.list, не ФИО"),
            "title": _prop("string", "Заголовок уведомления"),
            "body": _prop("string", "Текст уведомления"),
            "send_at": _prop("string", "Когда отправить, ISO. Пусто — сразу"),
            "workflow_id": _prop("string", "id агента. Пусто — текущий"),
        }, ["user_id", "title"]),
        ("agent.schedule", "Запланировать запуск агента: в момент at (ISO), через after_seconds, или когда выполнится condition (свободный текст: файл, письмо, любое событие). Пустой workflow_id = текущий агент.", {
            "workflow_id": _prop("string", "id агента. Пусто — текущий"),
            "message": _prop("string", "Что сказать агенту при запуске"),
            "at": _prop("string", "Момент запуска, ISO datetime"),
            "after_seconds": _prop("number", "Запуск через N секунд, если at нет"),
            "condition": _prop("string", "Событие: файл, письмо и т.п."),
            "once": _prop("boolean", "true — один раз, false — повторять"),
        }, []),
        ("agent.schedule.cancel", "Отменить ранее созданный триггер agent.schedule по trigger_id.", {
            "trigger_id": _prop("string", "id триггера из ответа agent.schedule"),
        }, ["trigger_id"]),
    ]
    server_tools = {"users.current", "users.list", "users.subordinates", "notify.send", "data.process"}
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
# Третий элемент — одна операция или набор (один tool закрывает несколько).
_CONTRACTS: dict[str, tuple[str, str, str | tuple[str, ...], list[str], list[str], str]] = {
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
    "onec.meeting_service_notes": (
        "onec",
        "service_note",
        ("list", "search", "read"),
        [],
        ["notes"],
        "count",
    ),
    "turboproject": (
        "turboproject",
        "project",
        ("search", "read", "list"),
        [],
        ["projects"],
        "count",
    ),
    "outlook.search_mail": ("outlook", "mail_message", "search", [], ["messages"], "count"),
    "outlook.read_calendar": ("outlook", "calendar_event", "list", [], ["events"], "count"),
    "outlook.create_event": (
        "outlook",
        "calendar_event",
        "create",
        ["subject", "start"],
        ["event"],
        "none",
    ),
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
    "excel.edit_workbook": ("desktop", "spreadsheet", "update", ["filename"], ["file"], "none"),
    "workspace.powershell_run": ("desktop", "shell", "execute", ["command"], ["text"], "none"),
    "code.write_python": ("desktop", "code", "create", ["code"], ["file"], "none"),
    "code.run_python": ("desktop", "code", "execute", [], ["text"], "none"),
    "agent.wait": ("constructor", "agent", "execute", ["seconds"], [], "none"),
    "data.process": ("constructor", "dataset", "execute", ["code"], ["result"], "none"),
    "report.build_task_report": ("desktop", "report", "export", [], ["file"], "none"),
    "report.build_meeting_summary": ("desktop", "report", "export", [], ["file"], "none"),
    "report.build_schedule_recommendations": ("desktop", "report", "export", [], ["file"], "none"),
    "users.current": ("constructor", "user", "read", [], ["user"], "none"),
    "users.list": ("constructor", "user", "list", [], ["users"], "count"),
    "users.subordinates": ("constructor", "subordinate", "list", [], ["users"], "count"),
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


DESIGN_PHASE = "design"
EXECUTE_PHASE = "execute"

# Фазы объявляет контракт, а не промпт. На проектировании доступны только tools,
# которые показывают контекст самого агента и не читают бизнес-данные.
# Новый context-tool достаточно добавить сюда — промпты не меняются.
_DESIGN_PHASE_TOOLS = frozenset({"users.current", "users.subordinates"})
_HELPER_TOOLS = frozenset({"data.process"})
_COM32_RUNTIME_TOOLS = frozenset(
    {
        "onec.search_documents",
        "onec.get_document_card",
        "onec.search_tasks",
        "onec.get_task_card",
        "onec.meeting_service_notes",
    }
)


def _phases_for(name: str) -> list[str]:
    if name in _DESIGN_PHASE_TOOLS:
        return [DESIGN_PHASE, EXECUTE_PHASE]
    return [EXECUTE_PHASE]


def _contract_for(name: str, execution: str) -> dict[str, Any]:
    system, entity, raw_operation, filters, fields, pagination = _CONTRACTS.get(
        name, (execution or "desktop", "", "execute", [], [], "none")
    )
    if isinstance(raw_operation, (list, tuple)):
        operations = [str(item).strip() for item in raw_operation if str(item).strip()]
    else:
        operations = [str(raw_operation).strip()] if str(raw_operation).strip() else ["execute"]
    return {
        "system": system,
        "entity": entity,
        "operation": operations[0] if operations else "execute",
        "operations": operations,
        "required_filters": list(filters),
        "result_fields": list(fields),
        "pagination": pagination,
        "phases": _phases_for(name),
        "helper": name in _HELPER_TOOLS,
        "runtime": "com32" if name in _COM32_RUNTIME_TOOLS else "",
    }


def _ensure_input_descriptions(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        if str(spec.get("description") or "").strip():
            continue
        spec["description"] = f"поле {key}"
    return tool


def list_tools() -> list[dict[str, Any]]:
    """Каталог с контрактами: по ним идёт подбор инструмента и проверка ответа."""
    tools: list[dict[str, Any]] = []
    for tool in _raw_tools():
        name = str(tool.get("name") or "")
        merged = {**tool, **_contract_for(name, str(tool.get("execution") or ""))}
        tools.append(_ensure_input_descriptions(merged))
    return tools


def tool_contracts() -> dict[str, dict[str, Any]]:
    return {str(tool["name"]): tool for tool in list_tools() if tool.get("name")}


def tools_for_phase(phase: str) -> list[dict[str, Any]]:
    wanted = (phase or "").strip().casefold() or EXECUTE_PHASE
    return [tool for tool in list_tools() if wanted in (tool.get("phases") or [])]


def design_context_tools() -> list[dict[str, Any]]:
    """Tools, которые разрешены на проектировании: контекст, без бизнес-данных."""
    return tools_for_phase(DESIGN_PHASE)


def helper_tools() -> list[dict[str, Any]]:
    """Вспомогательные tools прогона: обработка набора, не шаг черновика."""
    return [tool for tool in list_tools() if tool.get("helper")]


def contract_vocabulary() -> dict[str, Any]:
    """Измерения контрактов без имён инструментов — вход для проектировщика.

    Проектировщик выбирает system/entity/operation отсюда, поэтому новый tool
    расширяет словарь сам, без правок промптов.
    """
    systems: set[str] = set()
    entities: set[str] = set()
    operations: set[str] = set()
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for tool in list_tools():
        if tool.get("helper"):
            continue
        system = str(tool.get("system") or "").strip()
        entity = str(tool.get("entity") or "").strip()
        tool_operations = [
            str(item).strip()
            for item in (tool.get("operations") or [tool.get("operation")])
            if str(item).strip()
        ]
        if not system or not tool_operations:
            continue
        systems.add(system)
        if entity:
            entities.add(entity)
        required = [str(item) for item in (tool.get("required_filters") or [])]
        fields = [str(item) for item in (tool.get("result_fields") or [])]
        for operation in tool_operations:
            operations.add(operation)
            key = (system, entity, operation)
            group = grouped.get(key)
            if group is None:
                grouped[key] = {
                    "system": system,
                    "entity": entity,
                    "operation": operation,
                    "required_params": sorted(required),
                    "result_fields": set(fields),
                    "pagination": str(tool.get("pagination") or "none"),
                }
                continue
            if len(required) < len(group["required_params"]):
                group["required_params"] = sorted(required)
            group["result_fields"].update(fields)
    combinations = [
        {**group, "result_fields": sorted(group["result_fields"])}
        for group in grouped.values()
    ]
    combinations.sort(key=lambda item: (item["system"], item["entity"], item["operation"]))
    return {
        "systems": sorted(systems),
        "entities": sorted(entities),
        "operations": sorted(operations),
        "combinations": combinations,
    }


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
        tool_operations = {
            str(item).strip().casefold()
            for item in (tool.get("operations") or [tool.get("operation")])
            if str(item).strip()
        }
        if wanted_operation and wanted_operation not in tool_operations:
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

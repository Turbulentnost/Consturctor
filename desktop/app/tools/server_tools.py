"""Server-executed tools exposed to the local Cursor SDK agent.

These tools do not run on the desktop. They are proxied to the Constructor
backend via POST /api/v1/tools/{name}/invoke (see host.py). The schemas mirror
backend/app/services/local_mcp.py so the agent gets the same rich argument
contract it would get on the server runtime.

Routing rule (host.py): a tool runs on the desktop by default; only names in
SERVER_TOOL_NAMES are proxied to the server. Keep this list in sync with the
backend endpoint gate (_SERVER_TOOLS in backend/app/api/v1/tools.py).
"""

from __future__ import annotations

from typing import Any


def _prop(typ: str, description: str, **extra: Any) -> dict[str, Any]:
    field: dict[str, Any] = {"type": typ, "description": description}
    field.update(extra)
    return field


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_SERVER_TOOL_DEFS: list[tuple[str, str, dict[str, Any]]] = [
    (
        "imap.list_unread",
        "Список непрочитанных писем (сервер, IMAP).",
        _schema(
            {
                "limit": _prop("integer", "Сколько писем вернуть", default=20),
                "user": _prop("string", "Ящик. Пусто - ящик сессии"),
                "query": _prop("string", "Подстрока в теме или отправителе, не свободное ТЗ"),
            }
        ),
    ),
    (
        "imap.search",
        "Поиск писем по критериям (сервер, IMAP).",
        _schema(
            {
                "query": _prop("string", "Текст поиска в теме или отправителе"),
                "user": _prop("string", "Ящик. Пусто - ящик сессии"),
                "limit": _prop("integer", "Сколько писем вернуть", default=50),
            }
        ),
    ),
    (
        "imap.fetch_message",
        "Загрузить письмо по uid (сервер, IMAP).",
        _schema(
            {
                "uid": _prop("integer", "uid письма из imap.list_unread или imap.search"),
                "message_id": _prop("integer", "Альтернатива uid: внутренний id письма"),
                "user": _prop("string", "Ящик. Пусто - ящик сессии"),
            }
        ),
    ),
    (
        "imap.fetch_attachments",
        "Список вложений письма по uid (сервер, IMAP).",
        _schema(
            {
                "uid": _prop("integer", "uid письма из imap.list_unread или imap.search"),
                "message_id": _prop("integer", "Альтернатива uid: внутренний id письма"),
                "user": _prop("string", "Ящик. Пусто - ящик сессии"),
            }
        ),
    ),
    (
        "onec.odata_catalog",
        (
            "Каталог сущностей 1С OData. Сначала локальный снимок метаданных ERP "
            "(имена и структура полей/ТЧ), без живой 1С. "
            "Затем onec.odata_get с entity из ответа. "
            "Живая 1С только если сущности нет в снимке или refresh=true. "
            "Исполняется на сервере."
        ),
        _schema(
            {
                "kind": _prop("string", "Фильтр: document / catalog / register / other"),
                "search": _prop(
                    "string",
                    "Имя или смысл сущности: поручение, служебная записка, Document_ТД_Протокол",
                ),
                "entity": _prop("string", "Точное или почти точное имя EntitySet, вернёт и структуру"),
                "include_structure": _prop(
                    "boolean",
                    "Вернуть поля и табличные части. По умолчанию да, если задан search/entity",
                    default=True,
                ),
                "limit": _prop("integer", "Максимум сущностей в списке", default=400),
                "refresh": _prop(
                    "boolean",
                    "Пропустить снимок и прочитать живую 1С ($metadata)",
                    default=False,
                ),
            }
        ),
    ),
    (
        "onec.odata_get",
        (
            "Чтение сущности/пути 1С OData (сервер). entity бери из onec.odata_catalog. "
            "Для карточки документа передай ref_key или path с guid - вернутся все реквизиты. "
            "Не выдумывай имена EntitySet."
        ),
        _schema(
            {
                "entity": _prop("string", "Имя EntitySet из onec.odata_catalog, например Document_Проект"),
                "path": _prop("string", "Путь OData, включая ключ: Document_Имя(guid'...')"),
                "ref_key": _prop("string", "GUID документа: читает карточку целиком, не список"),
                "number": _prop("string", "Номер документа. Свежие сначала, с темой и табличными частями."),
                "filter": _prop("string", "OData $filter, например Number eq '000000001'"),
                "top": _prop("integer", "OData $top - сколько записей вернуть", default=3),
                "skip": _prop("integer", "OData $skip - смещение", default=0),
            }
        ),
    ),
    (
        "onec.odata_post",
        "Создание объекта через 1С OData (сервер). Требует подтверждения человека.",
        _schema(
            {
                "entity": _prop("string", "Имя EntitySet из onec.odata_catalog"),
                "body": _prop("object", "Поля нового объекта 1С, как в OData"),
            },
            ["entity"],
        ),
    ),
    (
        "onec.odata_patch",
        "Обновление объекта через 1С OData (сервер). Требует подтверждения человека.",
        _schema(
            {
                "entity": _prop("string", "Имя EntitySet из onec.odata_catalog"),
                "ref_key": _prop("string", "GUID объекта, который меняем"),
                "body": _prop("object", "Только поля, которые нужно изменить"),
            },
            ["entity", "ref_key"],
        ),
    ),
    (
        "onec.attach_file",
        "Прикрепление файла к документу 1С (сервер). Требует подтверждения человека.",
        _schema(
            {
                "document_ref_key": _prop("string", "GUID документа 1С"),
                "filename": _prop("string", "Имя файла в папке агента"),
            }
        ),
    ),
    (
        "onec.sql_query",
        "Только SELECT к ERP SQL (allowlist таблиц, сервер).",
        _schema(
            {
                "sql": _prop("string", "Один SELECT. Таблицы только из allowlist, без INSERT/UPDATE"),
            },
            ["sql"],
        ),
    ),
    (
        "onec.erp_tasks_current",
        (
            "Текущие (открытые) задачи пользователя из базы 1С erp_pm. "
            "Не журнал АСТ00 и не поиск «Проверить поручение». "
            "ФИО берётся из сессии Constructor; fio/user_id не обязательны. Сервер."
        ),
        _schema(
            {
                "limit": _prop("integer", "Максимум задач", default=50),
                "fio": _prop("string", "Необязательно: чужое ФИО. Пусто - пользователь сессии."),
                "user_id": _prop("string", "Необязательно: id пользователя 1С. Пусто - из сессии."),
            }
        ),
    ),
    (
        "onec.erp_tasks_period",
        "Задачи пользователя из erp_pm за период (дата создания). ФИО из сессии. Сервер.",
        _schema(
            {
                "date_from": _prop("string", "Начало периода YYYY-MM-DD"),
                "date_to": _prop("string", "Конец периода YYYY-MM-DD"),
                "include_done": _prop("boolean", "Включать выполненные задачи", default=True),
                "limit": _prop("integer", "Максимум задач", default=100),
                "fio": _prop("string", "Чужое ФИО. Пусто - пользователь сессии"),
                "user_id": _prop("string", "id пользователя 1С. Пусто - из сессии"),
            },
            ["date_from", "date_to"],
        ),
    ),
    (
        "onec.erp_subordinate_tasks",
        (
            "Дерево задач подчинённых из erp_pm и 1С:Документооборот за период. "
            "Только действующие назначения. Человек из сессии. Сервер."
        ),
        _schema(
            {
                "access_token": _prop("string", "JWT Constructor. Пусто - токен сессии."),
                "date_from": _prop("string", "Начало периода YYYY-MM-DD. Пусто - 30 дней назад."),
                "date_to": _prop("string", "Конец периода YYYY-MM-DD. Пусто - сегодня."),
                "only_open": _prop("boolean", "Только открытые задачи", default=False),
                "include_done": _prop("boolean", "Включать выполненные задачи за период", default=True),
                "limit_per_person": _prop("integer", "Максимум задач на одного человека", default=30),
                "include_self": _prop("boolean", "Включить руководителя (себя) отдельной строкой", default=True),
            }
        ),
    ),
    (
        "onec.erp_assignments",
        (
            "Журнал поручений 1С ERP (Document_ТД_Поручения, серия АСТ00). "
            "Проверка поручений = action=list, задачи «Проверить поручение» в 1С нет. "
            "Заказчик = реквизит Руководитель. action=list/get/files/download/tasks/protocols. "
            "Содержимое файла: onec.download_artifact с file_id из action=files. "
            "Номер кириллический АСТ, не латиница ACT. Сервер."
        ),
        _schema(
            {
                "action": _prop("string", "list | get | files | download | tasks | protocols", default="list"),
                "customer": _prop("string", "ФИО заказчика (Руководитель)"),
                "number": _prop("string", "Номер АСТ00-..."),
                "ref_key": _prop("string", "GUID документа"),
                "query": _prop("string", "Подстрока в ОЧем или задаче"),
                "date_from": _prop("string", "YYYY-MM-DD"),
                "date_to": _prop("string", "YYYY-MM-DD"),
                "only_open": _prop("boolean", "Только Создано/ВРаботе"),
                "include_last_day": _prop("boolean", "Открытые плюс все за сегодня", default=True),
                "include_files": _prop("boolean", "Сразу вернуть файлы", default=False),
                "file_id": _prop("string", "GUID вложения для action=download"),
                "limit": _prop("integer", "Максимум записей", default=40),
                "performer": _prop("string", "ФИО исполнителя для action=tasks"),
            }
        ),
    ),
    (
        "onec.download_artifact",
        (
            "Скачать приложенный файл 1С по GUID вкладки «Файлы». "
            "file_id из onec.erp_assignments action=files. "
            "OData Base64, том на диске, hs/dtw/files или UNC. Сервер, только чтение."
        ),
        _schema(
            {
                "file_id": _prop("string", "GUID вложения 1С (Ref_Key файла)"),
                "file_ref_key": _prop("string", "То же, что file_id"),
                "entity": _prop(
                    "string",
                    "Необязательно: Catalog_ТД_ПорученияПрисоединенныеФайлы или Catalog_ТД_ПротоколПрисоединенныеФайлы",
                ),
            },
            ["file_id"],
        ),
    ),
    (
        "onec.erp_assignments_write",
        (
            "Запись в журнал поручений 1С. Требует подтверждения человека. "
            "create / update / comment_task."
        ),
        _schema(
            {
                "action": _prop("string", "create | update | comment_task", default="update"),
                "number": _prop("string", "Номер АСТ00-..."),
                "ref_key": _prop("string", "GUID документа"),
                "topic": _prop("string", "ОЧем"),
                "basis": _prop("string", "Основание"),
                "customer": _prop("string", "ФИО заказчика"),
                "status": _prop("string", "Создано | ВРаботе | Принято"),
                "due": _prop("string", "Срок YYYY-MM-DD"),
                "lines": _prop("array", "Строки text/due/executor/priority"),
                "comment": _prop("string", "Комментарий возврата"),
                "task_ref_key": _prop("string", "GUID задачи исполнителя"),
            }
        ),
    ),
    (
        "onec.erp_write_probe",
        (
            "Проба записи конструктора: тестовый объект CONSTRUCTOR_PROBE "
            "нужной сущности 1С, проверка изменения, удаление. Не для боевых карточек."
        ),
        _schema(
            {
                "customer": _prop("string", "ФИО для теста. Пусто — сессия"),
                "workflow_id": _prop("string", "id черновика"),
                "intents": _prop("array", "Какие сущности и поля проверить"),
            }
        ),
    ),
    (
        "onec.docflow_tasks",
        "Задачи пользователя из 1С:Документооборот. ФИО из сессии. Сервер.",
        _schema(
            {
                "date_from": _prop("string", "Начало периода YYYY-MM-DD. Пусто - без нижней границы."),
                "date_to": _prop("string", "Конец периода YYYY-MM-DD. Пусто - без верхней границы."),
                "only_open": _prop("boolean", "Только открытые задачи", default=True),
                "include_done": _prop("boolean", "Включать выполненные задачи"),
                "limit": _prop("integer", "Максимум задач", default=200),
            }
        ),
    ),
    (
        "users.current",
        (
            "Текущий пользователь сессии Constructor: id, ФИО, должность, подразделение. "
            "Если регламент говорит «текущий пользователь» или «мои данные» - вызови этот tool, "
            "не спрашивай человека. Сервер."
        ),
        _schema({}),
    ),
    (
        "users.list",
        (
            "Список пользователей Constructor: id, ФИО, должность, подразделение. "
            "Вызови перед notify.send, чтобы выбрать получателя. Сервер."
        ),
        _schema(
            {
                "query": _prop("string", "ФИО, email или id - не роль и не «все» / «получатели»"),
            }
        ),
    ),
    (
        "users.subordinates",
        (
            "Подчинённые руководителя из оргструктуры erp_pm: ФИО, должность, подразделение. "
            "Пустой fio - текущий пользователь сессии. Сервер."
        ),
        _schema(
            {
                "fio": _prop("string", "ФИО руководителя. Пусто - текущий пользователь"),
                "user_id": _prop("string", "id из сессии или 1С. Пусто - текущий пользователь"),
            }
        ),
    ),
    (
        "notify.send",
        (
            "Отправить уведомление получателю (Windows-тост + inbox). user_id бери из users.list - "
            "не выдумывай id. Подтверждение человека не нужно: вызывай сразу. Сервер."
        ),
        _schema(
            {
                "user_id": _prop("string", "id получателя из users.list, не ФИО"),
                "title": _prop("string", "Заголовок уведомления"),
                "body": _prop("string", "Текст уведомления"),
                "send_at": _prop("string", "Когда отправить, ISO. Пусто - сразу"),
                "workflow_id": _prop("string", "id агента. Пусто - текущий"),
            },
            ["user_id", "title"],
        ),
    ),
]


SERVER_TOOL_NAMES: frozenset[str] = frozenset(name for name, _desc, _schema_ in _SERVER_TOOL_DEFS)
SERVER_TOOL_TIMEOUTS: dict[str, int] = {
    "onec.download_artifact": 300,
}


def canonical_server_tool_name(name: str) -> str:
    from app.tools.tool_names import resolve_tool_name

    return resolve_tool_name(name, SERVER_TOOL_NAMES)


def server_tool_timeout_seconds(name: str) -> int:
    official = canonical_server_tool_name(name)
    return int(SERVER_TOOL_TIMEOUTS.get(official) or 0)


def list_server_tools() -> list[dict[str, Any]]:
    """Server tool specs for the SDK catalog (execution=server)."""
    tools: list[dict[str, Any]] = []
    for name, description, schema in _SERVER_TOOL_DEFS:
        item: dict[str, Any] = {
            "name": name,
            "description": description,
            "inputSchema": schema,
            "execution": "server",
        }
        timeout = SERVER_TOOL_TIMEOUTS.get(name)
        if timeout:
            item["timeoutSeconds"] = timeout
        tools.append(item)
    return tools

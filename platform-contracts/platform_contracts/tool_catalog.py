"""Каталог platform tools: описания и JSON Schema параметров для внешних агентов."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ToolCatalogEntry:
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool = False
    runtime: str = "docker"
    category: str = ""


def _schema(*, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        body["required"] = required
    return body


def _str(desc: str, *, default: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "string", "description": desc}
    if default is not None:
        item["default"] = default
    return item


def _int(desc: str, *, default: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "integer", "description": desc}
    if default is not None:
        item["default"] = default
    return item


def _bool(desc: str, *, default: bool | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "boolean", "description": desc}
    if default is not None:
        item["default"] = default
    return item


_TOOL_ENTRIES: tuple[ToolCatalogEntry, ...] = (
    ToolCatalogEntry(
        name="imap.list_unread",
        category="imap",
        runtime="docker",
        read_only=True,
        description=(
            "Список UID непрочитанных писем в общем IMAP-ящике (INBOX). "
            "Используйте перед imap.fetch_message. Не фильтрует по отправителю — для поиска берите imap.search."
        ),
        parameters=_schema(properties={"limit": _int("Макс. UID (stub); в real игнорируется", default=50)}),
    ),
    ToolCatalogEntry(
        name="imap.search",
        category="imap",
        runtime="docker",
        read_only=True,
        description=(
            "Поиск писем в IMAP: критерий OR FROM needle SUBJECT needle (без полнотекстового TEXT). "
            "Возвращает последние limit совпадений (самые новые), не «первое найденное». "
            "Поля user или query — подстрока для FROM/SUBJECT; email в user даёт точный FROM."
        ),
        parameters=_schema(
            properties={
                "query": _str("Подстрока для FROM/SUBJECT"),
                "user": _str("Алиас или email отправителя (приоритетнее query для фильтра)"),
                "limit": _int("Сколько последних UID вернуть", default=50),
            },
        ),
    ),
    ToolCatalogEntry(
        name="imap.fetch_message",
        category="imap",
        runtime="docker",
        read_only=True,
        description=(
            "Прочитать письмо по UID: subject, from, body_text (plain, до ~12 КБ). "
            "UID берите из imap.search или imap.list_unread. После — imap.fetch_attachments для вложений."
        ),
        parameters=_schema(
            properties={
                "uid": _int("IMAP UID сообщения"),
                "user": _str("Контекст stub-поиска (опционально)"),
                "query": _str("Контекст stub-поиска (опционально)"),
            },
            required=["uid"],
        ),
    ),
    ToolCatalogEntry(
        name="imap.fetch_attachments",
        category="imap",
        runtime="docker",
        read_only=True,
        description=(
            "Метаданные вложений письма (filename, size) по UID. "
            "Не скачивает содержимое на диск — только список."
        ),
        parameters=_schema(properties={"uid": _int("IMAP UID сообщения")}, required=["uid"]),
    ),
    ToolCatalogEntry(
        name="onec.odata_get",
        category="onec",
        runtime="docker",
        read_only=True,
        description=(
            "HTTP GET к OData 1С ERP (документы, справочники). "
            "Учётные данные: ERP_LOGIN/ERP_PASSWORD из окружения или username/password в payload. "
            "HTTP 402 = неверный логин/пароль. "
            "path сохраняет query string ($top, $filter). "
            "Для задач исполнителя используйте onec.com.query_tasks, не OData."
        ),
        parameters=_schema(
            properties={
                "entity": _str("Имя сущности OData, напр. Document_ТД_ВходящаяКорреспонденция"),
                "path": _str("Путь после /odata/... включая ?$top=N"),
                "top": _int("Лимит записей если path без $top", default=5),
                "username": _str("Логин OData (опционально, иначе ERP_LOGIN)"),
                "password": _str("Пароль OData (опционально)"),
            },
        ),
    ),
    ToolCatalogEntry(
        name="onec.odata_post",
        category="onec",
        runtime="docker",
        description=(
            "Создать объект 1С через OData POST. entity — из allowlist сервиса. "
            "body — поля документа/справочника в JSON."
        ),
        parameters=_schema(
            properties={
                "entity": _str("Имя сущности OData"),
                "body": {"type": "object", "description": "JSON тело создаваемого объекта"},
            },
            required=["entity", "body"],
        ),
    ),
    ToolCatalogEntry(
        name="onec.odata_patch",
        category="onec",
        runtime="docker",
        description="Обновить объект 1С по ref_key через OData PATCH.",
        parameters=_schema(
            properties={
                "entity": _str("Имя сущности OData"),
                "ref_key": _str("GUID ссылки Ref_Key"),
                "body": {"type": "object", "description": "Поля для обновления"},
            },
            required=["entity", "ref_key", "body"],
        ),
    ),
    ToolCatalogEntry(
        name="onec.attach_file",
        category="onec",
        runtime="docker",
        description=(
            "Прикрепить файл к документу 1С. В текущей сборке NOT_IMPLEMENTED — "
            "используйте ручное прикрепление или onec.odata_patch для метаданных."
        ),
        parameters=_schema(
            properties={
                "document_ref_key": _str("Ref_Key документа"),
                "filename": _str("Имя файла"),
                "content_base64": _str("Содержимое файла в base64"),
            },
        ),
    ),
    ToolCatalogEntry(
        name="onec.sql_query",
        category="onec",
        runtime="docker",
        read_only=True,
        description=(
            "Read-only SELECT к SQL-базе ERP (pyodbc). Только запросы из allowlist сервиса. "
            "Макс. ~100 строк. Для документов предпочтительнее onec.odata_get."
        ),
        parameters=_schema(properties={"sql": _str("SQL SELECT")}, required=["sql"]),
    ),
    ToolCatalogEntry(
        name="onec.com.status",
        category="onec.com",
        runtime="windows",
        read_only=True,
        description=(
            "Статус COM-сервиса 1С ERP (:7831, Windows 32-bit Python). "
            "Проверяет bitness, строку подключения, готовность COMConnector."
        ),
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="onec.com.connect",
        category="onec.com",
        runtime="windows",
        description=(
            "Открыть COM-сеанс 1С ERP через V83.COMConnector под ERP_LOGIN. "
            "Возвращает session_id для onec.com.invoke / query_tasks / release. "
            "Только Windows host :7831."
        ),
        parameters=_schema(
            properties={"progid": _str("ProgID COMConnector", default="V83.COMConnector")},
        ),
    ),
    ToolCatalogEntry(
        name="onec.com.query_tasks",
        category="onec.com",
        runtime="windows",
        read_only=True,
        description=(
            "Список задач исполнителя через COM-запрос в ERP (не OData, не GUI). "
            "По умолчанию: Задача.ЗадачаИсполнителя для текущего ERP-пользователя. "
            "prefer_crm=true — CRM_ЗадачиПользователей. "
            "Для документооборота и смешанных источников предпочтительнее onec.com.query_work_items. "
            "Ответ: tasks[] с number, description, date, due_date, executor; task_source; current_user."
        ),
        parameters=_schema(
            properties={
                "session_id": _str("Существующая COM-сессия (опционально, иначе создаётся новая)"),
                "mine_only": _bool("Только задачи текущего пользователя", default=True),
                "limit": _int("Макс. записей", default=30),
                "prefer_crm": _bool("CRM вместо ERP Задача.ЗадачаИсполнителя", default=False),
            },
        ),
    ),
    ToolCatalogEntry(
        name="onec.com.query_work_items",
        category="onec.com",
        runtime="windows",
        read_only=True,
        description=(
            "Унифицированный список рабочих элементов из нескольких источников 1С через COM. "
            "scope: docflow | docflow_protocol | docflow_orders | erp_tasks | crm | business_process | all. "
            "Возвращает tasks[] с полем source и список фактически использованных sources."
        ),
        parameters=_schema(
            properties={
                "session_id": _str("Существующая COM-сессия (опционально)"),
                "fio": _str("ФИО исполнителя (по умолчанию текущий ERP-пользователь)"),
                "scope": _str("Область источников", default="all"),
                "limit": _int("Макс. записей", default=100),
                "only_open": _bool("Только открытые", default=True),
            },
        ),
    ),
    ToolCatalogEntry(
        name="onec.com.execute_query",
        category="onec.com",
        runtime="windows",
        read_only=True,
        description=(
            "Произвольный read-only запрос 1С (ВЫБРАТЬ/SELECT) через COM Query. "
            "parameters — именованные параметры запроса. Макс. ~500 строк."
        ),
        parameters=_schema(
            properties={
                "session_id": _str("Существующая COM-сессия (опционально)"),
                "query_text": _str("Текст запроса 1С"),
                "parameters": {"type": "object", "description": "Параметры запроса"},
                "limit": _int("Макс. строк в ответе", default=200),
            },
            required=["query_text"],
        ),
    ),
    ToolCatalogEntry(
        name="onec.com.metadata_search",
        category="onec.com",
        runtime="windows",
        read_only=True,
        description=(
            "Поиск объектов метаданных 1С (Documents, Catalogs, InformationRegisters и др.) "
            "по подстроке в имени или синониме."
        ),
        parameters=_schema(
            properties={
                "session_id": _str("Существующая COM-сессия (опционально)"),
                "pattern": _str("Подстрока для поиска"),
                "kinds": {"type": "array", "items": {"type": "string"}, "description": "Типы метаданных"},
                "limit": _int("Макс. результатов", default=50),
            },
        ),
    ),
    ToolCatalogEntry(
        name="onec.com.list_assignment_sources",
        category="onec.com",
        runtime="windows",
        read_only=True,
        description="Справочник встроенных источников поручений/задач для onec.com.query_work_items.",
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="onec.com.invoke",
        category="onec.com",
        runtime="windows",
        description=(
            "Вызов разрешённого метода COM-объекта сеанса 1С: Connect, NewObject, Documents, "
            "GetObject, Quit, String, EvalExpr, BatchExecute. Требует session_id из onec.com.connect."
        ),
        parameters=_schema(
            properties={
                "session_id": _str("ID COM-сессии"),
                "method": _str("Имя метода"),
                "args": {"type": "array", "description": "Позиционные аргументы", "items": {}},
                "kwargs": {"type": "object", "description": "Именованные аргументы"},
            },
            required=["session_id", "method"],
        ),
    ),
    ToolCatalogEntry(
        name="onec.com.release",
        category="onec.com",
        runtime="windows",
        description="Закрыть COM-сеанс 1С ERP и освободить ресурсы на Windows host.",
        parameters=_schema(properties={"session_id": _str("ID COM-сессии")}, required=["session_id"]),
    ),
    ToolCatalogEntry(
        name="com.list_apps",
        category="com",
        runtime="windows",
        read_only=True,
        description=(
            "Список зарегистрированных COM-приложений на Windows host (onec, outlook, excel, word…). "
            "Используйте перед com.connect."
        ),
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="com.connect",
        category="com",
        runtime="windows",
        description=(
            "Подключиться к COM-приложению (Outlook, Excel, 1C через legacy bridge). "
            "app — ключ из com.list_apps или progid явно."
        ),
        parameters=_schema(
            properties={
                "app": _str("Ключ приложения: onec, outlook, excel, word, powerpoint", default="onec"),
                "progid": _str("ProgID если app не задан"),
            },
        ),
    ),
    ToolCatalogEntry(
        name="com.invoke",
        category="com",
        runtime="windows",
        description="Вызов метода COM-объекта generic bridge (session_id из com.connect).",
        parameters=_schema(
            properties={
                "session_id": _str("ID COM-сессии"),
                "method": _str("Имя метода"),
                "args": {"type": "array", "items": {}},
                "kwargs": {"type": "object"},
            },
            required=["session_id", "method"],
        ),
    ),
    ToolCatalogEntry(
        name="com.release",
        category="com",
        runtime="windows",
        description="Закрыть generic COM-сессию.",
        parameters=_schema(properties={"session_id": _str("ID COM-сессии")}, required=["session_id"]),
    ),
    ToolCatalogEntry(
        name="com.outlook.launch",
        category="com",
        runtime="windows",
        description="Запустить Microsoft Outlook через COM на Windows host. Возвращает session_id.",
        parameters=_schema(properties={"visible": _bool("Показать окно Outlook", default=True)}),
    ),
    ToolCatalogEntry(
        name="com.outlook.close",
        category="com",
        runtime="windows",
        description="Закрыть COM-сессию Outlook. quit=true — завершить процесс Outlook.",
        parameters=_schema(
            properties={
                "session_id": _str("ID сессии Outlook"),
                "quit": _bool("Завершить Outlook", default=False),
            },
            required=["session_id"],
        ),
    ),
    ToolCatalogEntry(
        name="com.outlook.calendar_list",
        category="com",
        runtime="windows",
        read_only=True,
        description=(
            "Список встреч календаря Outlook за период (days от сегодня или start/end ISO). "
            "Требует session_id из com.outlook.launch."
        ),
        parameters=_schema(
            properties={
                "session_id": _str("ID сессии Outlook"),
                "days": _int("Горизонт в днях от сегодня", default=7),
                "start": _str("Начало периода ISO datetime"),
                "end": _str("Конец периода ISO datetime"),
                "limit": _int("Макс. встреч", default=50),
                "query": _str("Фильтр по теме"),
                "include_body": _bool("Включить текст описания встречи", default=False),
            },
        ),
    ),
    ToolCatalogEntry(
        name="com.outlook.calendar_get",
        category="com",
        runtime="windows",
        read_only=True,
        description="Одна встреча Outlook по EntryID из calendar_list.",
        parameters=_schema(
            properties={
                "entry_id": _str("Outlook EntryID"),
                "session_id": _str("ID сессии Outlook"),
                "include_body": _bool("Включить описание", default=True),
            },
            required=["entry_id"],
        ),
    ),
    ToolCatalogEntry(
        name="fs.list",
        category="fs",
        runtime="windows",
        read_only=True,
        description=(
            "Список файлов в allowlist-каталоге Windows host (:7830). "
            "path — относительный или абсолютный внутри разрешённых корней."
        ),
        parameters=_schema(
            properties={
                "path": _str("Каталог", default="."),
                "pattern": _str("Glob-шаблон имён", default="*"),
                "recursive": _bool("Рекурсивный обход", default=False),
            },
        ),
    ),
    ToolCatalogEntry(
        name="fs.read",
        category="fs",
        runtime="windows",
        read_only=True,
        description="Прочитать файл из allowlist-корня. as_base64 для бинарных файлов.",
        parameters=_schema(
            properties={
                "path": _str("Путь к файлу"),
                "max_bytes": _int("Лимит чтения"),
                "encoding": _str("Кодировка текста", default="utf-8"),
                "as_base64": _bool("Вернуть content_base64", default=False),
            },
            required=["path"],
        ),
    ),
    ToolCatalogEntry(
        name="fs.write",
        category="fs",
        runtime="windows",
        description=(
            "Записать файл в allowlist-корень. mode: overwrite|append|create. "
            "Для бинарных файлов (.docx, .xlsx) передайте content_base64. "
            "Путь задаётся явно в payload.path (полный путь в allowlist). "
            "Allowlist: C:\\Users\\Public\\Documents, CONSTRUCTOR_ROOT, data\\filesystem."
        ),
        parameters=_schema(
            properties={
                "path": _str("Полный путь к файлу, напр. C:\\Users\\Public\\Documents\\a.docx"),
                "content": _str("Текстовое содержимое"),
                "content_base64": _str("Бинарное содержимое base64"),
                "encoding": _str("Кодировка", default="utf-8"),
                "mode": _str("overwrite, append или create", default="overwrite"),
            },
            required=["path"],
        ),
    ),
    ToolCatalogEntry(
        name="fs.build_office_file",
        category="fs",
        runtime="windows",
        description=(
            "Создать .docx или .xlsx по указанному path (OOXML, без Word/Excel). "
            "Агент сам задаёт полный путь внутри FS_ROOT_ALLOWLIST. "
            "format: docx|xlsx (или по расширению path). Для xlsx опционально rows: [[...]]."
        ),
        parameters=_schema(
            properties={
                "path": _str("Полный путь с именем файла (.docx / .xlsx)"),
                "format": _str("docx или xlsx (опционально, иначе из расширения path)"),
                "title": _str("Заголовок документа / листа", default="Constructor agent file"),
                "body": _str("Текст для docx"),
                "rows": {
                    "type": "array",
                    "description": "Строки таблицы для xlsx",
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "mode": _str("overwrite|create|append", default="overwrite"),
            },
            required=["path"],
        ),
    ),
    ToolCatalogEntry(
        name="fs.stat",
        category="fs",
        runtime="windows",
        read_only=True,
        description="Метаданные файла или каталога (размер, mtime, is_dir).",
        parameters=_schema(properties={"path": _str("Путь")}, required=["path"]),
    ),
    ToolCatalogEntry(
        name="fs.move",
        category="fs",
        runtime="windows",
        description="Переместить файл/каталог внутри allowlist-корней.",
        parameters=_schema(
            properties={"from": _str("Исходный путь"), "to": _str("Целевой путь")},
            required=["from", "to"],
        ),
    ),
    ToolCatalogEntry(
        name="fs.copy",
        category="fs",
        runtime="windows",
        description="Копировать файл внутри allowlist-корней.",
        parameters=_schema(
            properties={"from": _str("Исходный путь"), "to": _str("Целевой путь")},
            required=["from", "to"],
        ),
    ),
    ToolCatalogEntry(
        name="shell.run",
        category="shell",
        runtime="both",
        description=(
            "Выполнить shell-команду. runtime=sandbox — изолированный Docker (:7823); "
            "runtime=native — Windows host (:7828/:7830) с allowlist команд (dir, type, git…). "
            "Без runtime — по SHELL_DEFAULT_RUNTIME. Возвращает stdout, stderr, exit_code."
        ),
        parameters=_schema(
            properties={
                "command": _str("Команда shell"),
                "cwd": _str("Рабочий каталог (native)"),
                "timeout": _int("Таймаут секунд"),
                "runtime": _str("sandbox или native"),
            },
            required=["command"],
        ),
    ),
    ToolCatalogEntry(
        name="desktop.system_info",
        category="desktop",
        runtime="windows",
        read_only=True,
        description="Информация о Windows desktop host: OS, Python, hostname, user, cwd.",
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="desktop.capabilities",
        category="desktop",
        runtime="windows",
        read_only=True,
        description=(
            "Каталог пакетов desktop host (:7830): com, fs, shell, desktop tools. "
            "Вызывайте первым для проверки доступности host-инструментов."
        ),
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="desktop.clipboard_read",
        category="desktop",
        runtime="windows",
        read_only=True,
        description="Прочитать текст из буфера обмена Windows (Unicode).",
        parameters=_schema(properties={"max_chars": _int("Лимит символов", default=8000)}),
    ),
    ToolCatalogEntry(
        name="desktop.clipboard_write",
        category="desktop",
        runtime="windows",
        description="Записать текст в буфер обмена Windows.",
        parameters=_schema(properties={"text": _str("Текст")}, required=["text"]),
    ),
    ToolCatalogEntry(
        name="desktop.open_path",
        category="desktop",
        runtime="windows",
        description="Открыть файл или каталог приложением по умолчанию (Windows shell).",
        parameters=_schema(properties={"path": _str("Абсолютный путь")}, required=["path"]),
    ),
    ToolCatalogEntry(
        name="browser.open_session",
        category="browser",
        runtime="both",
        description=(
            "Открыть эфемерную браузерную сессию Playwright (cookies живут до close_session). "
            "run_id агента связывает вкладки одного прогона."
        ),
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="browser.close_session",
        category="browser",
        runtime="both",
        description="Закрыть браузерную сессию и все вкладки.",
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="browser.navigate",
        category="browser",
        runtime="both",
        description="Перейти по URL в активной вкладке. URL должен быть в allowlist worker.",
        parameters=_schema(
            properties={
                "url": _str("URL страницы"),
                "timeout_ms": _int("Таймаут навигации мс"),
            },
            required=["url"],
        ),
    ),
    ToolCatalogEntry(
        name="browser.snapshot",
        category="browser",
        runtime="both",
        read_only=True,
        description=(
            "Снимок интерактивных элементов страницы (ref, role, name, selector). "
            "Вызывайте перед browser.click / browser.type."
        ),
        parameters=_schema(properties={}),
    ),
    ToolCatalogEntry(
        name="browser.click",
        category="browser",
        runtime="both",
        description="Клик по элементу через CSS selector или ref из browser.snapshot.",
        parameters=_schema(
            properties={
                "selector": _str("CSS selector"),
                "ref": _str("Ref из snapshot, напр. e3"),
                "timeout_ms": _int("Таймаут мс"),
            },
        ),
    ),
    ToolCatalogEntry(
        name="browser.type",
        category="browser",
        runtime="both",
        description="Ввод текста в поле. submit=true — Enter после ввода. password=true — скрытый ввод.",
        parameters=_schema(
            properties={
                "text": _str("Текст для ввода"),
                "selector": _str("CSS selector"),
                "ref": _str("Ref из snapshot"),
                "clear": _bool("Очистить поле перед вводом", default=True),
                "submit": _bool("Нажать Enter", default=False),
                "password": _bool("Поле пароля", default=False),
                "timeout_ms": _int("Таймаут мс"),
            },
            required=["text"],
        ),
    ),
    ToolCatalogEntry(
        name="browser.fill",
        category="browser",
        runtime="both",
        description="Полностью заменить значение input (clear + type).",
        parameters=_schema(
            properties={
                "text": _str("Текст"),
                "selector": _str("CSS selector"),
                "ref": _str("Ref из snapshot"),
                "submit": _bool("Enter после ввода", default=False),
                "timeout_ms": _int("Таймаут мс"),
            },
            required=["text"],
        ),
    ),
    ToolCatalogEntry(
        name="browser.wait",
        category="browser",
        runtime="both",
        description="Ждать selector/ref, URL glob или sleep_ms.",
        parameters=_schema(
            properties={
                "selector": _str("CSS selector"),
                "ref": _str("Ref из snapshot"),
                "url": _str("Glob URL"),
                "sleep_ms": _int("Пауза мс"),
                "timeout_ms": _int("Макс. ожидание мс"),
            },
        ),
    ),
    ToolCatalogEntry(
        name="browser.tabs",
        category="browser",
        runtime="both",
        read_only=True,
        description="Управление вкладками: action=list|new|switch.",
        parameters=_schema(
            properties={
                "action": _str("list, new или switch", default="list"),
                "page_id": _str("ID вкладки для switch"),
                "url": _str("URL для new"),
            },
        ),
    ),
    ToolCatalogEntry(
        name="browser.screenshot",
        category="browser",
        runtime="both",
        read_only=True,
        description="PNG-скриншот активной страницы (path в ответе). full_page — вся прокрутка.",
        parameters=_schema(
            properties={
                "url": _str("Сначала перейти по URL если страница пуста"),
                "full_page": _bool("Скриншот всей страницы", default=False),
            },
        ),
    ),
    ToolCatalogEntry(
        name="browser.extract_text",
        category="browser",
        runtime="both",
        read_only=True,
        description=(
            "Извлечь текст со страницы, по URL или DuckDuckGo-поиск через query. "
            "selector по умолчанию body."
        ),
        parameters=_schema(
            properties={
                "url": _str("URL страницы"),
                "query": _str("Поисковый запрос DuckDuckGo"),
                "selector": _str("CSS selector", default="body"),
                "max_results": _int("Результатов поиска", default=5),
                "fetch_first": _bool("Сначала загрузить страницу", default=True),
            },
        ),
    ),
)

TOOL_CATALOG: dict[str, ToolCatalogEntry] = {entry.name: entry for entry in _TOOL_ENTRIES}


def all_tool_names() -> list[str]:
    return sorted(TOOL_CATALOG)


def get_tool_entry(name: str) -> ToolCatalogEntry | None:
    return TOOL_CATALOG.get(name.strip())


def openai_function_schema(name: str) -> dict[str, Any] | None:
    entry = get_tool_entry(name)
    if entry is None:
        return None
    return {
        "type": "function",
        "function": {
            "name": entry.name,
            "description": entry.description,
            "parameters": entry.parameters,
        },
    }


def tool_metadata(name: str) -> dict[str, Any] | None:
    entry = get_tool_entry(name)
    if entry is None:
        return None
    return {
        "name": entry.name,
        "description": entry.description,
        "parameters": entry.parameters,
        "read_only": entry.read_only,
        "runtime": entry.runtime,
        "category": entry.category,
    }


def list_tool_metadata(names: Iterable[str] | None = None) -> list[dict[str, Any]]:
    selected = sorted(names) if names is not None else all_tool_names()
    items: list[dict[str, Any]] = []
    for name in selected:
        meta = tool_metadata(name)
        if meta is not None:
            items.append(meta)
        else:
            items.append({"name": name, "description": "", "parameters": {"type": "object", "properties": {}}})
    return items

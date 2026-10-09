"""Паспорта инструментов: что инструмент делает простыми словами и что ему нужно для работы.

Это человеческая часть карточки. Описание для LLM, схема параметров, таймаут и способ
исполнения берутся из самой реализации (app/vendors/constructor, app/vendors/aiagentback),
поэтому не расходятся с кодом. Инструмент без паспорта в каталог не попадёт — так
в стенде не появляется ничего неописанного.
"""

from __future__ import annotations

from app.tools.registry import Passport, PassportGroup

GROUPS: list[PassportGroup] = [
    PassportGroup(
        id="agent",
        title="Управление запуском агента",
        summary="Пауза, отложенный и условный перезапуск агента, текущая дата.",
        tools=[
            Passport(
                "agent.wait",
                summary=(
                    "Приостанавливает выполнение агента на заданное число секунд (до часа). Нужен, "
                    "когда агент ждёт внешнего события: письма, загрузки страницы, снятия лимита "
                    "запросов."
                ),
            ),
            Passport(
                "agent.schedule",
                summary=(
                    "Создаёт триггер повторного запуска агента: в заданный момент (at), через N "
                    "секунд (after_seconds) или по текстовому условию (condition — «когда придёт "
                    "письмо от Иванова»). С once=false триггер повторяется. Возвращает trigger_id."
                ),
                side_effect="write",
                requires=["Сервер Constructor: API расписаний агентов"],
            ),
            Passport(
                "agent.schedule.cancel",
                summary="Удаляет триггер, созданный agent.schedule, по его trigger_id.",
                side_effect="write",
                requires=["Сервер Constructor: API расписаний агентов"],
            ),
            Passport(
                "get_current_date",
                summary=(
                    "Возвращает сегодняшнюю дату, день недели и время в заданном часовом поясе (по "
                    "умолчанию Europe/Moscow), чтобы агент не гадал, какое сегодня число."
                ),
                title="Текущая дата",
                runtime="local",
            ),
        ],
    ),
    PassportGroup(
        id="users",
        title="Пользователи и уведомления Constructor",
        summary=(
            "Кто запустил агента, кто есть в Constructor и в оргструктуре, отправка уведомлений на "
            "компьютер сотрудника."
        ),
        requires=["Сервер Constructor и JWT-сессия пользователя"],
        tools=[
            Passport(
                "users.current",
                summary=(
                    "Возвращает пользователя текущей сессии Constructor: id, ФИО, должность, "
                    "подразделение. Агент вызывает его вместо того, чтобы спрашивать человека, кто "
                    "он."
                ),
                title="Текущий пользователь",
            ),
            Passport(
                "users.list",
                summary=(
                    "Ищет пользователей Constructor по ФИО, e-mail или id и возвращает id, ФИО, "
                    "должность и подразделение. Обычно нужен перед notify.send, чтобы получить "
                    "настоящий user_id."
                ),
            ),
            Passport(
                "users.subordinates",
                summary=(
                    "Возвращает подчинённых руководителя по оргструктуре 1С erp_pm (ФИО, должность, "
                    "подразделение) — в том числе тех, кто не зарегистрирован в Constructor. Без "
                    "параметров — подчинённые текущего пользователя."
                ),
                title="Подчинённые руководителя",
                requires=[
                    "ERP SQL Server: ERP_SQL_SERVER, ERP_SQL_DATABASE, ERP_SQL_USER, ERP_SQL_PASSWORD",
                ],
            ),
            Passport(
                "notify.send",
                summary=(
                    "Отправляет пользователю Constructor уведомление: Windows-тост на его компьютере "
                    "и запись во входящих. Отправку можно отложить (send_at). Получатель задаётся "
                    "user_id из users.list."
                ),
                side_effect="write",
                requires=["Desktop Constructor у получателя (winotify) для показа тоста"],
            ),
        ],
    ),
    PassportGroup(
        id="workspace",
        title="Код и команды",
        summary="Python и PowerShell внутри рабочей папки агента, чтение файлов с сетевых шар.",
        requires=["Рабочая папка агента на устройстве"],
        tools=[
            Passport(
                "code.write_python",
                summary=(
                    "Сохраняет Python-файл в рабочую папку агента: обычные скрипты — в code/, модули "
                    "KPI — в generated/<slug>.py, тесты — в tests/test_<slug>.py. Код не запускает."
                ),
            ),
            Passport(
                "code.run_python",
                summary=(
                    "Запускает Python-скрипт из папки агента (или переданный inline-код) и возвращает"
                    " stdout, stderr и код выхода; файлы tests/test_*.py запускаются через pytest. "
                    "Рабочая директория — папка агента."
                ),
                requires=["Python на устройстве; pytest для тестов"],
            ),
            Passport(
                "workspace.powershell_run",
                summary=(
                    "Выполняет PowerShell-команду в рабочей папке агента (выйти за её пределы нельзя)"
                    " и возвращает stdout и stderr. Есть таймаут и выбор подпапки."
                ),
                requires=["Windows PowerShell"],
            ),
            Passport(
                "filesystem",
                summary=(
                    "Читает файлы на разрешённых сетевых шарах (по умолчанию \\\\192.168.1.198). "
                    "resolve восстанавливает путь с опечаткой или обрезкой нечётким поиском, list "
                    "показывает каталог, read возвращает текст файла (у PDF — текстовый слой, без "
                    "OCR). Запись не поддерживается."
                ),
                title="Сетевая файловая система",
                runtime="fs",
                requires=[
                    "Доступ к сетевой шаре с сервера",
                    "FS_ALLOWED_ROOTS, FS_MAX_READ_BYTES, FS_MAX_LIST_ENTRIES, FS_FUZZY_MIN_SCORE",
                ],
            ),
        ],
    ),
    PassportGroup(
        id="excel",
        title="Excel",
        summary="Файлы рабочей папки агента и книги Excel: чтение, создание, правка, Action Tracker.",
        requires=["openpyxl", "Рабочая папка агента на устройстве"],
        tools=[
            Passport(
                "excel.list_files",
                summary=(
                    "Показывает файлы в рабочей папке агента, включая materials/ и загруженные "
                    "пользователем книги. С него агент начинает работу с вложениями."
                ),
            ),
            Passport(
                "excel.read_workbook",
                summary=(
                    "Читает лист книги .xlsx/.xlsm: заголовки и строки (не больше max_rows). Только "
                    "Excel — Word, PDF и картинки читает office.read_file."
                ),
            ),
            Passport(
                "excel.create_workbook",
                summary=(
                    "Создаёт или перезаписывает оформленную книгу .xlsx: баннер с заголовком, KPI, "
                    "цветная шапка, зебра, автофильтр, перенос текста, ширина колонок по содержимому."
                ),
            ),
            Passport(
                "excel.edit_workbook",
                summary=(
                    "Правит существующую книгу .xlsx: добавляет строки, меняет ячейки, создаёт и "
                    "удаляет листы. Если вместо operations переданы headers и rows — перезаписывает "
                    "лист целиком."
                ),
            ),
            Passport(
                "excel.write_action_tracker",
                summary=(
                    "Собирает ActionTracker.xlsx из последних ответов onec.erp_assignments и "
                    "onec.meeting_protocols: все поручения и протоколы ПСД. Данные берёт из "
                    "сохранённых tool_results сам; если выборка была усечена, файл не пишет."
                ),
            ),
        ],
    ),
    PassportGroup(
        id="documents",
        title="Документы, отчёты и аудио",
        summary="Чтение Word/PDF/сканов, оформление и экспорт отчётов, расшифровка аудио.",
        tools=[
            Passport(
                "office.read_file",
                summary=(
                    "Извлекает текст из Word (.docx), PDF и изображений. Если текстового слоя нет "
                    "(скан, фото), отдаёт страницы картинками для зрения модели. Старый формат .doc "
                    "не поддерживается."
                ),
                requires=["python-docx, PyMuPDF / pdfplumber"],
            ),
            Passport(
                "office.format_document",
                summary=(
                    "Создаёт или переоформляет Excel/Word по корпоративному шаблону: тема, титул, "
                    "KPI, шапка таблицы, зебра, статусы, колонтитулы. Если файл уже есть, а данных "
                    "нет — только применяет оформление."
                ),
                requires=["openpyxl, python-docx"],
            ),
            Passport(
                "report.export_document",
                summary=(
                    "Сохраняет готовый отчёт файлом в папке агента: Word (.docx) с корпоративным "
                    "оформлением или Markdown, если python-docx недоступен. Текст разделов пишет "
                    "агент; markdown в body (таблицы, списки, подзаголовки, жирный) превращается в "
                    "форматирование Word."
                ),
                requires=["python-docx"],
            ),
            Passport(
                "report.build_meeting_summary",
                summary=(
                    "Собирает текст сводки, повестки или протокола совещания из уже полученных "
                    "данных. Ничего не пишет в Outlook и не создаёт файлов — для файла есть "
                    "report.export_document."
                ),
            ),
            Passport(
                "report.build_schedule_recommendations",
                summary=(
                    "Формирует текстовые рекомендации по графику встреч на основе прочитанного "
                    "календаря. Календарь не меняет."
                ),
            ),
            Passport(
                "report.build_task_report",
                summary=(
                    "Формирует текстовый отчёт по поручениям с оценкой риска просрочки на основе "
                    "собранных данных. Во внешние системы ничего не пишет."
                ),
            ),
            Passport(
                "audio.transcribe",
                summary=(
                    "Расшифровывает аудиофайл, приложенный к запуску (faster-whisper на сервере). "
                    "Полный текст с таймкодами сохраняется во временный файл, в ответе — путь, число "
                    "сегментов и длительность. Повторный вызов отдаёт готовую расшифровку. Говорящие "
                    "не размечаются."
                ),
                title="Расшифровка аудио",
                requires=[
                    "faster-whisper на сервере, WHISPER_MODEL",
                    "Вложения запуска Constructor",
                ],
            ),
        ],
    ),
    PassportGroup(
        id="web",
        title="Веб-поиск и парсинг сайтов",
        summary="Поиск в интернете без браузера, парсинг сайтов через Playwright, выгрузка закупок с ЭТП.",
        tools=[
            Passport(
                "web_search",
                summary=(
                    "Быстрый поиск в интернете через DuckDuckGo и Wikipedia без запуска браузера. "
                    "Возвращает список результатов; fetch_top дополнительно загружает текст первых "
                    "страниц."
                ),
                title="Веб-поиск",
                requires=["Выход в интернет", "CLI tools/web_search_tool"],
                replaces=["web_search"],
            ),
            Passport(
                "site_browser",
                summary=(
                    "Открывает сайт в headless Chromium (Playwright) и извлекает данные: текст "
                    "страницы, элементы по CSS-селекторам или результаты поиска по сайту."
                ),
                title="Парсер сайта",
                requires=["Playwright + Chromium", "CLI tools/site_browser_tool"],
            ),
            Passport(
                "plan_export",
                summary=(
                    "Ищет закупки на электронной торговой площадке по ключевым словам и выгружает "
                    "найденное в Excel на рабочий стол пользователя. Набор колонок настраивается."
                ),
                title="Закупки с ЭТП в Excel",
                side_effect="create_draft",
                requires=["Playwright + Chromium, openpyxl", "CLI tools/roseltorg_tender_search"],
            ),
        ],
    ),
    PassportGroup(
        id="browser",
        title="Браузер: чтение страниц",
        summary=(
            "Браузер пользователя в режиме только чтения: какие браузеры есть, открыть страницу, "
            "достать текст и таблицы, пройти по ссылке."
        ),
        requires=["Установленный Chromium-браузер (Edge, Chrome, Yandex и др.) с поддержкой CDP"],
        tools=[
            Passport(
                "browser.list_installed_browsers",
                summary=(
                    "Определяет, какие браузеры установлены на компьютере (Edge, Chrome, Brave, "
                    "Yandex, Opera, Vivaldi, Chromium, Firefox): путь, версия и можно ли читать их "
                    "через CDP."
                ),
            ),
            Passport(
                "browser.open_browser",
                summary=(
                    "Запускает выбранный браузер (по id или имени) с обычным профилем пользователя и,"
                    " при желании, сразу открывает URL. Логины и сессии пользователя сохраняются."
                ),
            ),
            Passport(
                "browser.search_web",
                summary=(
                    "Ищет в интернете через браузер в режиме только чтения и возвращает результаты; "
                    "поиск можно ограничить списком доменов."
                ),
            ),
            Passport(
                "browser.open_page",
                summary=(
                    "Открывает страницу в режиме только чтения и возвращает её текст (с лимитом "
                    "символов). Может использовать штатный профиль пользователя, чтобы видеть "
                    "страницы за авторизацией."
                ),
                replaces=["fetch_page_via_user_browser"],
            ),
            Passport(
                "browser.extract_table",
                summary=(
                    "Открывает страницу и извлекает HTML-таблицы в структурированном виде; table_hint"
                    " помогает выбрать нужную таблицу."
                ),
            ),
            Passport(
                "browser.scroll_page",
                summary=(
                    "Прокручивает страницу вверх или вниз на заданное число пикселей и возвращает "
                    "текст, ставший видимым. Для длинных лент и подгружаемого контента."
                ),
            ),
            Passport(
                "browser.click_link",
                summary=(
                    "Переходит по ссылке на странице (по тексту или href) и возвращает текст "
                    "открывшейся страницы. Формы не отправляет."
                ),
            ),
        ],
    ),
    PassportGroup(
        id="browser_ui",
        title="Браузер: управление интерфейсом",
        summary=(
            "Работа со вкладкой как человек: скриншоты, клики по координатам, ввод текста. Через CDP,"
            " а если штатный профиль уже открыт без CDP — по видимому экрану (OS fallback)."
        ),
        requires=[
            "Установленный Chromium-браузер с поддержкой CDP; для OS fallback — активный рабочий стол",
        ],
        tools=[
            Passport(
                "browser.navigate",
                summary=(
                    "Открывает URL в управляемой вкладке и возвращает скриншот. По умолчанию "
                    "использует штатный профиль пользователя с его авторизацией; если CDP недоступен,"
                    " переходит к управлению видимым экраном."
                ),
            ),
            Passport(
                "browser.screenshot",
                summary=(
                    "Делает скриншот текущей вкладки (base64 PNG), чтобы модель увидела интерфейс и "
                    "выбрала следующее действие."
                ),
            ),
            Passport(
                "browser.get_page_html",
                summary=(
                    "Возвращает HTML текущей вкладки через CDP: url, title, html с лимитом и краткое "
                    "резюме структуры. Нужен для анализа DOM и скрытого контента; визуальную часть "
                    "показывает browser.screenshot."
                ),
            ),
            Passport(
                "browser.dump_page_source",
                summary=(
                    "Сохраняет полный HTML и собранный CSS текущей вкладки в page_dumps/<имя>/ "
                    "рабочей папки и возвращает пути к файлам. Дальше содержимое разбирают кодом "
                    "(code.write_python + code.run_python), не загружая его в контекст модели."
                ),
            ),
            Passport(
                "browser.click",
                summary="Кликает по координатам (x, y) со скриншота и возвращает новый скриншот.",
            ),
            Passport(
                "browser.type_text",
                summary=(
                    "Вводит текст в активное поле (сначала нужен browser.click по полю) и возвращает "
                    "скриншот. В OS fallback вставляет текст через буфер обмена."
                ),
            ),
            Passport(
                "browser.press_key",
                summary=(
                    "Нажимает служебную клавишу (Enter, Tab, Escape, Backspace, стрелки) и возвращает"
                    " скриншот."
                ),
            ),
            Passport(
                "browser.scroll",
                summary="Прокручивает текущую вкладку вверх или вниз и возвращает скриншот.",
            ),
        ],
    ),
    PassportGroup(
        id="outlook",
        title="Outlook на компьютере пользователя",
        summary=(
            "Почта, календарь и задачи Outlook через COM от имени пользователя, плюс карточка плана "
            "совещаний в интерфейсе Constructor."
        ),
        requires=[
            "Windows и запущенный Microsoft Outlook с профилем пользователя",
            "pywin32 (COM)",
        ],
        tools=[
            Passport(
                "outlook.search_mail",
                summary=(
                    "Ищет письма в папке Outlook (по умолчанию «Входящие») за дату или период по "
                    "короткой подстроке темы или отправителя. Возвращает письма с entry_id для "
                    "дальнейших действий."
                ),
            ),
            Passport(
                "outlook.fetch_message",
                summary="Возвращает тело письма, признак «не прочитано» и список вложений по entry_id.",
            ),
            Passport(
                "outlook.save_attachment",
                summary=(
                    "Сохраняет вложение письма (по номеру 1…N) на диск, по умолчанию — в рабочую "
                    "папку агента."
                ),
                side_effect="create_draft",
            ),
            Passport(
                "outlook.save_message",
                summary=(
                    "Сохраняет письмо целиком в файл .msg — например, чтобы приложить его к входящей "
                    "корреспонденции в 1С."
                ),
                side_effect="create_draft",
            ),
            Passport(
                "outlook.read_calendar",
                summary=(
                    "Читает встречи Outlook за день или период: свой календарь, общий ящик "
                    "«Совещания» или отфильтрованные по ФИО участников. Возвращает события, список "
                    "календарей и свободные слоты."
                ),
                replaces=["read_outlook_calendars"],
            ),
            Passport(
                "outlook.mark_read",
                summary="Помечает письмо прочитанным или непрочитанным.",
            ),
            Passport(
                "outlook.display_message",
                summary=(
                    "Открывает письмо в окне Outlook или готовит ответ, ответ всем либо пересылку. С "
                    "send=true пересылка уходит сразу, без окна."
                ),
                side_effect="write",
            ),
            Passport(
                "outlook.create_event",
                summary=(
                    "Создаёт одну или несколько встреч в Outlook и при необходимости рассылает "
                    "приглашения. Может создать встречу в чужом календаре, если есть право записи. "
                    "Тема и текст помечаются как созданные ИИ-агентом. Требует подтверждения "
                    "человека."
                ),
                side_effect="write",
                replaces=["send_meeting_invite"],
            ),
            Passport(
                "outlook.read_tasks",
                summary="Читает задачи Outlook пользователя.",
            ),
            Passport(
                "email.create_draft",
                summary="Создаёт черновик письма в Outlook, не отправляя его.",
            ),
            Passport(
                "email.send",
                summary=(
                    "Отправляет письмо из Outlook пользователя. Помечено как опасное действие и "
                    "требует подтверждения человека."
                ),
            ),
            Passport(
                "calendar.show_meetings",
                summary=(
                    "Показывает пользователю итоговый план совещаний карточкой: темы, участники, "
                    "замещения и цветовая разметка (зелёным — поставить, красным — отменить, без "
                    "цвета — оставить). Только визуализация: в Outlook ничего не пишет."
                ),
                requires=["Интерфейс Constructor для отображения карточки"],
            ),
        ],
    ),
    PassportGroup(
        id="exchange",
        title="Календарь Exchange (служебная учётка)",
        summary=(
            "Календарь Exchange на сервере от имени служебной учётки Postagent: серии встреч, "
            "перенос, отмена, состав участников, подбор времени и переговорных, поиск e-mail по ФИО."
        ),
        requires=[
            "Exchange Web Services (exchangelib)",
            "OUTLOOK_EMAIL, OUTLOOK_PASSWORD, OUTLOOK_SERVER, OUTLOOK_MAILBOX, OUTLOOK_TIMEZONE",
        ],
        tools=[
            Passport(
                "send_recurring_meeting_invite",
                summary=(
                    "Создаёт серию встреч (ежедневно, еженедельно или ежемесячно) в календаре "
                    "служебной учётки и рассылает приглашения участникам и переговорным. Серия "
                    "заканчивается после N повторений или в заданную дату."
                ),
                title="Повторяющееся совещание",
                side_effect="write",
            ),
            Passport(
                "cancel_meeting",
                summary=(
                    "Отменяет встречу или всю серию и рассылает участникам уведомление с "
                    "комментарием. Встречу ищет по id или по теме и времени; list_only показывает "
                    "список, dry_run — только проверка без отмены."
                ),
                title="Отмена совещания",
                side_effect="write",
                requires=[
                    "SMTP для уведомлений: OUTLOOK_SMTP_HOST, OUTLOOK_SMTP_PORT, OUTLOOK_SMTP_FROM",
                ],
            ),
            Passport(
                "reschedule_meeting",
                summary=(
                    "Переносит встречу или всю серию на новое время (можно поменять длительность и "
                    "место) и рассылает обновлённое приглашение. Есть list_only и dry_run."
                ),
                title="Перенос совещания",
                side_effect="write",
            ),
            Passport(
                "update_meeting_attendees",
                summary=(
                    "Добавляет или удаляет участников встречи (одного вхождения или всей серии). "
                    "Новым участникам уходит приглашение, исключённым — уведомление, руководителю и "
                    "инициатору — письмо об изменении состава. dry_run — только предпросмотр."
                ),
                title="Состав участников совещания",
                side_effect="write",
                requires=[
                    "SMTP для уведомлений: OUTLOOK_SMTP_HOST, OUTLOOK_SMTP_PORT, OUTLOOK_SMTP_FROM",
                ],
            ),
            Passport(
                "find_meeting_slot",
                summary=(
                    "Подбирает ближайшее время, когда свободны все участники: рабочие дни, "
                    "08:00–17:00, без окна блокировки 1С 12:00–13:10. Может сразу проверить свободные"
                    " переговорные."
                ),
                title="Подбор времени совещания",
                timeout_seconds=180,
            ),
            Passport(
                "find_quorum_meeting_slots",
                summary=(
                    "Подбирает время, когда свободны все обязательные участники и заданная доля "
                    "остальных (min_coverage_ratio). Возвращает лучшие слоты, конфликты и оценку, "
                    "какие мешающие встречи можно перенести."
                ),
                title="Подбор времени по кворуму",
                timeout_seconds=180,
            ),
            Passport(
                "meeting_rooms",
                summary=(
                    "Показывает переговорные комнаты (из meeting_rooms.json и, при discover, из "
                    "Exchange) и проверяет, свободны ли они на заданный слот."
                ),
                title="Переговорные",
            ),
            Passport(
                "lookup_email_by_fio",
                summary=(
                    "Находит корпоративные адреса @turbo-don.ru по списку ФИО через адресную книгу "
                    "Exchange (GAL)."
                ),
                title="E-mail по ФИО",
                requires=["ONEC_CORPORATE_EMAIL_DOMAIN"],
            ),
        ],
    ),
    PassportGroup(
        id="imap",
        title="Почта IMAP (сервер)",
        summary="Почтовый ящик на сервере Constructor по IMAP — без Outlook на компьютере пользователя.",
        requires=["IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD на сервере Constructor", "imapclient"],
        tools=[
            Passport(
                "imap.list_unread",
                summary="Возвращает непрочитанные письма ящика (с лимитом и необязательным фильтром).",
                title="Непрочитанные письма",
            ),
            Passport(
                "imap.search",
                summary="Ищет письма в ящике по строке запроса.",
                title="Поиск писем",
            ),
            Passport(
                "imap.fetch_message",
                summary="Загружает письмо по uid или Message-ID: заголовки и текст.",
                title="Письмо целиком",
            ),
            Passport(
                "imap.fetch_attachments",
                summary="Возвращает список вложений письма по uid или Message-ID.",
                title="Вложения письма",
            ),
        ],
    ),
    PassportGroup(
        id="onec_desktop",
        title="1С на компьютере пользователя",
        summary=(
            "Чтение документов, задач и вложений 1С через COM-коннектор (32-битный cscript) или "
            "OData, открытие форм и подготовка входящей из письма. Всё в режиме только чтения."
        ),
        requires=["Windows и клиент 1С с COM-коннектором (V83.COMConnector, 32 бит)"],
        tools=[
            Passport(
                "onec.search_documents",
                summary=(
                    "Ищет документы 1С по виду, номеру или тексту и возвращает список для открытия "
                    "карточки."
                ),
            ),
            Passport(
                "onec.get_document_card",
                summary=(
                    "Возвращает карточку документа 1С (реквизиты и табличные части) по ссылке, номеру"
                    " или запросу."
                ),
            ),
            Passport(
                "onec.search_tasks",
                summary=(
                    "Ищет задачи 1С по тексту и статусу; mine_only — только задачи текущего "
                    "пользователя."
                ),
            ),
            Passport(
                "onec.get_task_card",
                summary="Возвращает карточку задачи 1С по ссылке или номеру.",
            ),
            Passport(
                "onec.list_attachments",
                summary="Показывает присоединённые файлы объекта 1С (документа или задачи).",
            ),
            Passport(
                "onec.read_attachment",
                summary="Читает присоединённый файл 1С и возвращает его текст.",
            ),
            Passport(
                "onec.open_form",
                summary=(
                    "Открывает форму 1С на экране пользователя (например, входящую корреспонденцию с "
                    "подставленным файлом письма). Ничего не записывает — дальше работает "
                    "пользователь."
                ),
            ),
            Passport(
                "onec.save_incoming_mail_msg",
                summary=(
                    "Сохраняет письмо Outlook в .msg и готовит его к приложению во входящую "
                    "корреспонденцию 1С."
                ),
                side_effect="create_draft",
                requires=["Microsoft Outlook"],
            ),
            Passport(
                "onec.register_incoming_from_mail",
                summary=(
                    "Готовит регистрацию входящей корреспонденции из письма Outlook: сохраняет письмо"
                    " и открывает форму 1С с данными отправителя и темой. Документ записывает "
                    "пользователь."
                ),
                requires=["Microsoft Outlook"],
            ),
            Passport(
                "onec.meeting_service_notes",
                summary=(
                    "Очередь служебных записок 1С на организацию совещаний: по умолчанию "
                    "несогласованные за 30 дней с желаемой датой от сегодня. Тема и цель совещания, "
                    "желаемые дата и время, длительность, место, вид, ПСД, ФИО руководителя, "
                    "инициатора и участников. OData напрямую, без Constructor и COM."
                ),
                requires=["1С OData: ONEC_ODATA_URL, ONEC_ODATA_USER, ONEC_ODATA_PASSWORD"],
                replaces=["get_meeting_memos", "get_meeting_dashboard"],
            ),
        ],
    ),
    PassportGroup(
        id="onec_server",
        title="1С:ERP и Документооборот (сервер)",
        summary=(
            "1С:ERP и 1С:Документооборот через сервер Constructor: OData, SQL, задачи, журнал "
            "поручений, входящая корреспонденция, протоколы совещаний, файлы."
        ),
        requires=[
            "1С OData: ODATA_BASE_URL, ODATA_USERNAME, ODATA_PASSWORD",
            "Сессия Constructor (ФИО пользователя берётся из JWT)",
        ],
        tools=[
            Passport(
                "onec.odata_catalog",
                summary=(
                    "Показывает сущности 1С OData (справочники, документы, регистры) с полями и "
                    "табличными частями. Сначала берёт локальный снимок метаданных ERP; живую 1С "
                    "опрашивает только при refresh или если сущности нет в снимке."
                ),
                title="Каталог сущностей 1С",
            ),
            Passport(
                "onec.odata_get",
                summary=(
                    "Читает данные 1С через OData: список сущности с фильтром и пагинацией или одну "
                    "запись по ref_key/номеру со всеми реквизитами. Имя сущности берётся из "
                    "onec.odata_catalog."
                ),
                title="Чтение данных 1С OData",
            ),
            Passport(
                "onec.sql_query",
                summary=(
                    "Выполняет SELECT к SQL-базе 1С:ERP. Разрешено только чтение и только таблицы из "
                    "allowlist."
                ),
                title="SQL-запрос к ERP",
                requires=[
                    "ERP SQL Server: ERP_SQL_SERVER, ERP_SQL_DATABASE, ERP_SQL_USER, ERP_SQL_PASSWORD, ERP_SQL_DRIVER (pyodbc)",
                ],
            ),
            Passport(
                "onec.erp_tasks_current",
                summary=(
                    "Возвращает открытые задачи пользователя из 1С erp_pm. ФИО берётся из сессии "
                    "Constructor."
                ),
                title="Текущие задачи ERP",
                requires=["ERP SQL Server: ERP_SQL_*"],
            ),
            Passport(
                "onec.erp_tasks_odata",
                summary=(
                    "Возвращает текущие задачи исполнителя через OData (Task_ЗадачаИсполнителя); если"
                    " OData вернула неполные данные, дополняет их SQL-запросом."
                ),
                title="Текущие задачи ERP через OData",
                requires=["ERP SQL Server: ERP_SQL_* (для fallback_sql)"],
            ),
            Passport(
                "onec.erp_tasks_period",
                summary=(
                    "Возвращает задачи пользователя из erp_pm, созданные за период; можно включить "
                    "выполненные."
                ),
                title="Задачи ERP за период",
                requires=["ERP SQL Server: ERP_SQL_*"],
            ),
            Passport(
                "onec.erp_subordinate_tasks",
                summary=(
                    "Строит дерево задач подчинённых текущего пользователя из erp_pm и "
                    "1С:Документооборот за период (только действующие назначения)."
                ),
                title="Задачи подчинённых",
                requires=[
                    "ERP SQL Server: ERP_SQL_*",
                    "1С:Документооборот: DOCFLOW_ODATA_USERNAME, DOCFLOW_ODATA_PASSWORD",
                ],
            ),
            Passport(
                "onec.erp_assignments",
                summary=(
                    "Работает с журналом поручений 1С ERP (серия АСТ00): список по заказчику и "
                    "периоду, карточка поручения, приложенные файлы, связанные задачи и протоколы. По"
                    " умолчанию — открытые поручения, include_all — весь журнал."
                ),
                title="Журнал поручений ERP",
                replaces=["get_porucheniya"],
            ),
            Passport(
                "onec.erp_assignments_write",
                summary=(
                    "Создаёт или изменяет поручение в журнале 1С и добавляет комментарий к задаче. "
                    "Требует подтверждения человека."
                ),
                title="Запись в журнал поручений",
                side_effect="write",
                requires_approval=True,
            ),
            Passport(
                "onec.download_artifact",
                summary=(
                    "Скачивает файл, приложенный к объекту 1С (вкладка «Файлы»), по GUID через HTTP-"
                    "сервис и сохраняет во временную папку. Дальше файл читают office.read_file или "
                    "excel.read_workbook."
                ),
                title="Скачать файл 1С",
                requires=["HTTP-сервис 1С hs/dtw/files"],
            ),
            Passport(
                "onec.incoming_correspondence",
                summary=(
                    "Возвращает справочник подразделений для регистрации входящей корреспонденции в "
                    "1С."
                ),
                title="Подразделения для входящей",
            ),
            Passport(
                "onec.incoming_correspondence_write",
                summary=(
                    "Создаёт документ «Входящая корреспонденция» в 1С через OData: подразделение, "
                    "тема, отправитель, текст и приложенное письмо .msg. Требует подтверждения "
                    "человека."
                ),
                title="Регистрация входящей корреспонденции",
                side_effect="write",
                requires_approval=True,
            ),
            Passport(
                "onec.erp_write_probe",
                summary=(
                    "Проверяет, может ли агент писать в нужные сущности 1С: создаёт тестовый объект "
                    "CONSTRUCTOR_PROBE, изменяет и удаляет его. Для настройки прав, не для рабочих "
                    "данных."
                ),
                title="Проба записи в 1С",
                side_effect="write",
            ),
            Passport(
                "onec.docflow_tasks",
                summary="Возвращает задачи пользователя из 1С:Документооборот за период; ФИО — из сессии.",
                title="Задачи Документооборота",
                requires=[
                    "1С:Документооборот: DOCFLOW_ODATA_USERNAME, DOCFLOW_ODATA_PASSWORD; DOK_HTTP_*",
                ],
            ),
            Passport(
                "onec.meeting_protocols",
                summary=(
                    "Читает протоколы совещаний 1С по виду (РК или СД/ПСД), дате или номеру; по "
                    "ref_key — полную карточку со всеми табличными частями. По умолчанию — черновики "
                    "на проверке."
                ),
                title="Протоколы совещаний",
            ),
            Passport(
                "onec.meeting_protocol_write",
                summary=(
                    "Создаёт или перезаписывает черновик протокола совещания в 1С: шапка, "
                    "присутствующие, повестка, решения и задачи с исполнителями и сроками. ФИО сервер"
                    " сам сопоставляет со ссылками 1С; проведённые протоколы не трогает. Требует "
                    "подтверждения человека."
                ),
                title="Запись протокола совещания",
                side_effect="write",
                requires_approval=True,
                replaces=["create_protocol"],
            ),
        ],
    ),
    PassportGroup(
        id="onec_meetings",
        title="Совещания в 1С:ERP",
        summary=(
            "Подготовка совещаний в 1С:ERP: темы и их участники, служебные записки, удаление "
            "протоколов, напоминания на рабочий стол 1С."
        ),
        requires=[
            "1С OData: ONEC_ODATA_URL, ONEC_ODATA_USER, ONEC_ODATA_PASSWORD, ONEC_ODATA_TIMEOUT",
        ],
        tools=[
            Passport(
                "get_meeting_topics_registry",
                summary=(
                    "Ищет темы совещаний в справочнике 1С по названию, коду, виду совещания или GUID;"
                    " можно оставить только незакрытые и подтянуть ФИО руководителя и подразделение."
                ),
                title="Реестр тем совещаний",
            ),
            Passport(
                "get_meeting_topic_participants",
                summary=(
                    "Возвращает участников темы совещания из регистра соответствия тем и участников "
                    "1С."
                ),
                title="Участники темы совещания",
            ),
            Passport(
                "check_meeting_topic_similar",
                summary=(
                    "Проверяет, нет ли у руководителя похожей активной темы совещания, ничего не "
                    "создавая. Возвращает найденную тему и участников из служебной записки, которых в"
                    " ней нет, чтобы спросить пользователя: взять её или создать новую."
                ),
                title="Поиск похожей темы",
            ),
            Passport(
                "resolve_meeting_topic",
                summary=(
                    "Выполняет решение пользователя после check_meeting_topic_similar: use_existing —"
                    " берёт найденную тему и добавляет в неё недостающих участников, create_new — "
                    "создаёт новую тему со всеми реквизитами."
                ),
                title="Решение по теме совещания",
                side_effect="write",
            ),
            Passport(
                "create_meeting_topic",
                summary=(
                    "Создаёт тему совещания в справочнике 1С с руководителем, видом совещания, "
                    "участниками и прочими реквизитами. Обычно вызывается через "
                    "resolve_meeting_topic; есть dry_run."
                ),
                title="Создание темы совещания",
                side_effect="write",
            ),
            Passport(
                "create_service_memo",
                summary="Создаёт служебную записку в 1С:ERP и задачу исполнителю, найденному по ФИО.",
                title="Создание служебной записки",
                side_effect="write",
            ),
            Passport(
                "approve_service_memo",
                summary=(
                    "Проверяет служебную записку о совещании на соответствие СТО и возвращает чек-"
                    "лист и рекомендацию для сотрудника УД. Автоматическое согласование сейчас "
                    "отключено — документ в 1С не меняется."
                ),
                title="Проверка служебной записки по СТО",
            ),
            Passport(
                "confirm_service_memo",
                summary=(
                    "Кнопка «Утвердить» на служебной записке об организации совещания: ставит признак "
                    "«Утверждено начальником УД». После этого в 1С открывается «Оформить протокол "
                    "совещания». Статус согласования не меняет. Есть dry_run."
                ),
                title="Утверждение служебной записки",
                side_effect="write",
            ),
            Passport(
                "reject_service_memo",
                summary=(
                    "Отклоняет служебную записку о совещании (статус «Отклонена», причина — в "
                    "комментарии) и отправляет инициатору напоминание на рабочий стол 1С. Есть "
                    "dry_run."
                ),
                title="Отклонение служебной записки",
                side_effect="write",
            ),
            Passport(
                "delete_protocol",
                summary="Удаляет протокол совещания в 1С:ERP по Ref_Key или номеру. Действие необратимо.",
                title="Удаление протокола",
                side_effect="dangerous",
            ),
            Passport(
                "send_desktop_notification",
                summary=(
                    "Отправляет сотрудникам по ФИО напоминание на рабочий стол 1С (запись в регистр "
                    "напоминаний пользователя) с привязкой к объекту-источнику и сроку."
                ),
                title="Напоминание на рабочий стол 1С",
                side_effect="write",
                requires=["ONEC_NOTIFICATION_SOURCE_USER_FIO"],
            ),
        ],
    ),
    PassportGroup(
        id="turboproject",
        title="TurboProject",
        summary=(
            "Проекты MS Project, связанные с 1С: поиск по индексу, портфели сотрудников, карточки, "
            "задачи, метрики и сводки по портфелю."
        ),
        requires=[
            "TurboProject API: TURBOPROJECT_API_BASE, TURBOPROJECT_EMAIL, TURBOPROJECT_PASSWORD",
        ],
        tools=[
            Passport(
                "turboproject",
                summary=(
                    "Совместимый вход в TurboProject из ранних версий: по запросу, руководителю или "
                    "file_id возвращает индекс проектов с 1С. Для новых сценариев есть "
                    "специализированные turboproject.*."
                ),
            ),
            Passport(
                "turboproject.list",
                summary=(
                    "Совместимый список проектов с привязкой к 1С (file_id, название, даты, люди из "
                    "1С). Для новых сценариев — search_projects или get_user_portfolio."
                ),
            ),
            Passport(
                "turboproject.get",
                summary=(
                    "Совместимая карточка одного проекта по file_id: даты MS Project и 1С, статистика"
                    " задач, просрочки, ресурсы. Для новых сценариев — get_project."
                ),
            ),
            Passport(
                "turboproject.search_projects",
                summary=(
                    "Ищет проекты по индексу, не читая карточек: по названию, статусу, руководителю, "
                    "сотруднику, подразделению и датам, с пагинацией и сортировкой. Возвращает "
                    "руководителя, куратора, заказчика и участников."
                ),
                replaces=["list_turbo_projects"],
            ),
            Passport(
                "turboproject.get_user_portfolio",
                summary=(
                    "Возвращает все проекты сотрудника одним вызовом — где он руководитель, куратор, "
                    "заказчик или заместитель. Без карточек."
                ),
            ),
            Passport(
                "turboproject.get_project",
                summary=(
                    "Возвращает подробности одного проекта по project_id; нужные блоки выбираются "
                    "через fields: даты, данные 1С (в том числе рабочая группа), статистика задач, "
                    "просрочки, ресурсы, бюджет, решения."
                ),
                replaces=["get_turbo_project", "get_turbo_project_working_group"],
            ),
            Passport(
                "turboproject.get_project_tasks",
                summary=(
                    "Возвращает задачи одного проекта с фильтрами по статусу, исполнителю и "
                    "просрочке."
                ),
            ),
            Passport(
                "turboproject.get_project_metrics",
                summary="Возвращает компактные метрики по небольшому списку проектов.",
            ),
            Passport(
                "turboproject.get_overdue_projects",
                summary=(
                    "Считает задержку (delay_days) по заранее выбранным проектам: до 20 project_ids "
                    "или фильтр по руководителю. Весь портфель без сужения не сканирует."
                ),
            ),
            Passport(
                "turboproject.get_projects_with_blocked_tasks",
                summary=(
                    "Находит проблемные и зависшие задачи в заранее выбранных проектах. Если явного "
                    "признака блокировки нет, возвращает частичный результат."
                ),
            ),
            Passport(
                "turboproject.get_workload_summary",
                summary="Группирует задачи и просрочки по сотрудникам — для вопросов о загрузке людей.",
            ),
            Passport(
                "turboproject.get_project_portfolio_summary",
                summary="Сводка портфеля: группирует проекты по статусу, подразделению или руководителю.",
            ),
        ],
    ),
]

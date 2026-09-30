"""Playbook and tool bundle for «Подготовка заседаний Совета директоров» (ПЛ-34-242)."""

from __future__ import annotations

from typing import Any

_SD_TITLE_HINTS = (
    "заседаний совета",
    "заседания совета",
    "подготовка заседаний совета",
    "совета директоров",
    "сд гк",
    "пл-34-242",
    "пл 34-242",
    "пл34-242",
)

_PACKAGE_ITEMS = (
    "резюме",
    "опу",
    "ддс",
    "инвестиц",
    "продаж",
    "дз",
    "производств",
    "ниокр",
    "риск",
    "персонал",
    "поручен",
    "решения класса а",
    "приложение а",
    "приложение б",
)


def is_sd_meeting_agent(*parts: str) -> bool:
    blob = " ".join(str(part or "") for part in parts).casefold()
    return any(hint in blob for hint in _SD_TITLE_HINTS)


def sd_runtime_tools() -> list[str]:
    return [
        "outlook.read_calendar",
        "calendar.show_meetings",
        "onec.meeting_service_notes",
        "onec.meeting_protocols",
        "onec.search_documents",
        "onec.get_document_card",
        "onec.list_attachments",
        "onec.read_attachment",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.docflow_tasks",
        "excel.list_files",
        "excel.read_workbook",
        "office.read_file",
        "report.build_meeting_summary",
        "report.export_document",
        "onec.meeting_protocol_write",
        "users.current",
        "users.list",
        "chat.send_direct",
    ]


def sd_playbook_draft() -> dict[str, Any]:
    checklist = "; ".join(_PACKAGE_ITEMS)
    return {
        "status": "verified",
        "title": "Подготовка заседаний Совета директоров",
        "goal": (
            "Проверить комплект материалов заседания СД ГК по ПЛ-34-242 (версия 03), "
            "собрать недостающее из 1С и вложений запуска, подготовить сводку "
            "комплектности, создать в 1С черновик протокола следующего заседания на основе "
            "протокола прошлого и разослать каждому исполнителю личное сообщение в чате "
            "с итогами проверки по его задачам."
        ),
        "result": (
            "Сводка комплектности, список пробелов, карточки для устного доклада; "
            "черновик протокола следующего заседания в 1С (статус «Подготовлен»); "
            "личные сообщения исполнителям в чате Constructor; "
            "при Word-расшифровке — черновик протокола, Decision Log и Action Tracker."
        ),
        "when_to_run": (
            "За 2 рабочих дня до заседания СД ГК и по кнопке с материалами заседания; "
            "после заседания — по кнопке с Word-расшифровкой."
        ),
        "run_inputs": [
            {
                "id": "agenda",
                "label": "Повестка заседания",
                "required": True,
                "accept": [".docx", ".pdf", ".xlsx"],
            },
            {
                "id": "completeness_table",
                "label": "Таблица комплектности",
                "required": True,
                "accept": [".xlsx", ".docx"],
            },
            {
                "id": "transcript",
                "label": "Word-расшифровка заседания",
                "required": False,
                "accept": [".docx"],
            },
        ],
        "steps": [
            {
                "id": "s1",
                "title": "Найти заседание в календаре",
                "system": "outlook",
                "entity": "calendar_event",
                "operation": "list",
                "required_params": [],
                "done_when": "Есть тема, дата/время, участники и замещения по СД ГК.",
            },
            {
                "id": "s2",
                "title": "Служебные записки и карточки 1С по СД",
                "system": "onec",
                "entity": "service_note",
                "operation": "list",
                "required_params": [],
                "done_when": "Собраны темы/карточки «Совет директоров по ГК» и связанные СЗ.",
            },
            {
                "id": "s2b",
                "title": "Протоколы СД на проверку",
                "system": "onec",
                "entity": "protocol",
                "operation": "list",
                "required_params": ["meeting_kind"],
                "done_when": "Найдены протоколы Document_ТД_Протокол с префиксом ПСД/СПГ/СД за период заседания.",
            },
            {
                "id": "s3",
                "title": "Вложения 1С к карточкам",
                "system": "onec",
                "entity": "file",
                "operation": "list",
                "required_params": ["document_ref"],
                "done_when": "Получены имена и тексты вложений из 1С (PDF/DOCX/XLSX).",
            },
            {
                "id": "s4",
                "title": "Материалы запуска",
                "system": "desktop",
                "entity": "file",
                "operation": "list",
                "required_params": [],
                "done_when": "Прочитаны повестка, таблица комплектности и Word-расшифровка (если есть).",
            },
            {
                "id": "s5",
                "title": "Проверка комплектности по п. 6.4 ПЛ-34-242",
                "system": "constructor",
                "entity": "checklist",
                "operation": "read",
                "required_params": [],
                "done_when": f"Сверены пункты пакета: {checklist}.",
            },
            {
                "id": "s6",
                "title": "Сводка и файлы результата",
                "system": "desktop",
                "entity": "report",
                "operation": "export",
                "required_params": ["filename"],
                "done_when": "Сформированы сводка комплектности и при расшифровке — протокол/Decision Log/Action Tracker.",
            },
            {
                "id": "s7",
                "title": "Протокол следующего заседания",
                "system": "onec",
                "entity": "protocol",
                "operation": "create",
                "required_params": ["source_ref_key"],
                "done_when": (
                    "В 1С создан черновик протокола следующего заседания СД ГК на основе прошлого: "
                    "шапка, присутствующие, повестка и задачи на контроль исполнения."
                ),
            },
            {
                "id": "s8",
                "title": "Итоги исполнителям в чат",
                "system": "constructor",
                "entity": "chat_message",
                "operation": "notify",
                "required_params": ["text"],
                "done_when": (
                    "Каждый исполнитель задач прошлого протокола получил личное сообщение: его задачи, "
                    "какие файлы есть и каких нет, результат проверки; ненайденные получатели — в пробелах."
                ),
            },
        ],
        "runtime": {
            "kind": "board_meeting",
            "tools": sd_runtime_tools(),
        },
    }


def sd_playbook_instructions() -> str:
    checklist = "\n".join(f"- {item}" for item in _PACKAGE_ITEMS)
    return (
        "Агент «Подготовка заседаний Совета директоров» (ПЛ-34-242, версия 03).\n"
        "Порядок работы на каждый запуск:\n"
        "1. Outlook: найди заседание СД ГК (тема, дата, участники, замещения) — "
        "`outlook.read_calendar`, при необходимости `calendar.show_meetings`.\n"
        "2. 1С: служебные записки — `onec.meeting_service_notes`; карточки тем/документов СД — "
        "`onec.search_documents` + `onec.get_document_card` (запрос «совет директоров по гк»).\n"
        "3. Протоколы на проверку: только `onec.meeting_protocols` с meeting_kind=sd и датой "
        "заседания (или date_from/date_to). Номера СД ГК: префикс ПСД_001_О_* (не только СПГ/СД). "
        "Не собирай фильтр вручную через onec.odata_get. Карточку — `onec.odata_get` по ref_key "
        "из ответа meeting_protocols.\n"
        "4. Вложения 1С: для каждой найденной карточки — `onec.list_attachments`, "
        "затем `onec.read_attachment` или `onec.download_artifact` + `office.read_file` "
        "(Word/PDF/картинки; сканы — OCR). Excel — `excel.read_workbook`. "
        "Встроенные Read и Grep для этих файлов не вызывай.\n"
        "5. Материалы запуска: `excel.list_files` → Excel: `excel.read_workbook`; "
        "Word/PDF/картинки: `office.read_file`.\n"
        "6. Сверь обязательный пакет п. 6.4 ПЛ-34-242:\n"
        f"{checklist}\n"
        "7. Если пункта нет — зафиксируй пробел, не выдумывай. Без Word-расшифровки "
        "не готовь протокол, Decision Log и Action Tracker.\n"
        "8. Результат: сводка комплектности + `report.export_document` "
        "(при расшифровке — протокол и таблицы решений/поручений). Материалы не утверждай.\n"
        "8a. Протокол следующего заседания: возьми прошлый протокол СД ГК из шага 3 "
        "(последний по дате; `onec.meeting_protocols` с ref_key — его форма с задачами) и один раз "
        "вызови `onec.meeting_protocol_write` с action=next и source_ref_key. Дата — из поля "
        "«Дата следующего совещания» прошлого протокола или из календаря (date YYYY-MM-DD). "
        "Сервер сам скопирует шапку, присутствующих, повестку и перенесёт задачи на контроль. "
        "Если черновик на эту дату уже есть — не создавай второй, укажи его номер.\n"
        "8b. Рассылка итогов: для каждого исполнителя задач прошлого протокола — одно "
        "`chat.send_direct` (fio как в протоколе, либо user_id из `users.list`). В тексте: "
        "его задачи и сроки; по каждой — какие файлы найдены (имя файла) и каких не хватает "
        "по п. 6.4; итог проверки («комплект полный» / «не хватает: …»); номер протокола "
        "следующего заседания. Без оценок и выдуманных фактов. Если в ответе sent=false — "
        "впиши получателя и note в пробелы и не повторяй вызов.\n"
        "9. Почту не ищи: не вызывай outlook.search_mail и imap.*. "
        "Заседание — один вызов outlook.read_calendar; если календарь уже выгружен в JSON — "
        "прочитай этот файл один раз и не ищи его снова.\n"
        "10. Протоколы ищи только через `onec.meeting_protocols` (ПСД/СПГ/СД), "
        "не через произвольный odata_get с фильтром startswith(Number,'СД'). "
        "1С читай через OData read-only (meeting_service_notes, meeting_protocols, search_documents); "
        "пишешь в 1С только протокол через onec.meeting_protocol_write (шаг 8a) — "
        "не вызывай onec.odata_post, onec.odata_patch, onec.attach_file; "
        "не крути onec.odata_catalog без сущности и фильтра "
        "и не повторяй тот же поиск. Зафиксируй пробел и сразу ## WORK_RESULT. "
        "После WORK_RESULT инструменты не вызывай."
    )


def sd_local_playbook(*, title: str, demo_text: str = "", answered_scope: str = "") -> dict[str, Any]:
    scope = (answered_scope or "").strip()
    scope_line = f"Объём запуска:\n{scope}\n\n" if scope else ""
    summary = (demo_text or sd_playbook_instructions()).strip()
    if len(summary) > 2500:
        summary = summary[:2500] + "…"
    return {
        "instructions": f"{scope_line}{sd_playbook_instructions()}",
        "example_run": summary,
        "demo_ok": True,
        "tools": sd_runtime_tools(),
        "name": title or "Подготовка заседаний Совета директоров",
        "expected_result": sd_playbook_draft()["result"],
        "triggers": [],
        "steps": sd_playbook_draft()["steps"],
    }


def apply_sd_config(local_run: dict[str, Any] | None, *, title: str, notes: str) -> dict[str, Any]:
    """Patch local_run for SD agent: playbook, draft, runtime tools."""
    local = dict(local_run or {})
    blob = f"{title} {notes}"
    if not is_sd_meeting_agent(blob):
        return local
    draft = sd_playbook_draft()
    playbook = sd_local_playbook(title=title or draft["title"], demo_text=notes)
    local["playbook"] = playbook
    local["playbook_draft"] = draft
    local["runtime"] = str(local.get("runtime") or "mcp")
    local["tools"] = sd_runtime_tools()
    local["ui_mode"] = "chat"
    return local


def apply_sd_plan_runtime(plan_data: dict[str, Any] | None, *, title: str, notes: str) -> dict[str, Any]:
    plan = dict(plan_data or {})
    if not is_sd_meeting_agent(title, notes, plan.get("goal") or ""):
        return plan
    seed = sd_playbook_draft()
    runtime = dict(plan.get("runtime") or {})
    runtime["kind"] = "board_meeting"
    runtime["tools"] = sd_runtime_tools()
    plan["runtime"] = runtime
    plan["steps"] = seed["steps"]
    if not (plan.get("goal") or "").strip():
        plan["goal"] = seed["goal"]
    if not (plan.get("title") or "").strip():
        plan["title"] = title or seed["title"]
    return plan

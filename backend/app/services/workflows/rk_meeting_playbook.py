"""Playbook and tool bundle for «Подготовка заседаний Ревизионной комиссии» (ПЛ-01-001)."""

from __future__ import annotations

from typing import Any

_RK_TITLE_HINTS = (
    "ревизионной комиссии",
    "ревизионная комиссия",
    "заседаний ревизион",
    "заседания ревизион",
    "пл-01-001",
    "пл 01-001",
    "пл01-001",
)

_CHECKLIST_ITEMS = (
    "проект повестки",
    "открытые поручения",
    "просрочки",
    "предписания",
    "сроки служебных расследований",
    "документы на закрытие",
    "вопросы руководителю рк",
)

_RK_SHARE_HINT = (
    r"\\192.168.1.198\Files\24.Ревизионная комиссия\Отдел\8. Планы работ и реестр"
)
_RK_REGISTRY_HINT = (
    r"\\192.168.1.198\Files\24.Ревизионная комиссия\Отдел\10. Секретарь РК\РЕЕСТР ПОРУЧЕНИЙ"
)


def is_rk_meeting_agent(*parts: str) -> bool:
    blob = " ".join(str(part or "") for part in parts).casefold()
    if any(hint in blob for hint in ("совета директоров", "пл-34-242", "пл 34-242")):
        return False
    return any(hint in blob for hint in _RK_TITLE_HINTS)


def rk_runtime_tools() -> list[str]:
    return [
        "outlook.read_calendar",
        "calendar.show_meetings",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.docflow_tasks",
        "onec.meeting_protocols",
        "onec.search_documents",
        "onec.get_document_card",
        "onec.list_attachments",
        "onec.read_attachment",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "excel.list_files",
        "excel.read_workbook",
        "report.build_task_report",
        "report.build_meeting_summary",
        "report.export_document",
        "workspace.powershell_run",
        "users.current",
    ]


def rk_schedule_draft() -> dict[str, Any]:
    return {
        "name": "Подготовка заседаний Ревизионной комиссии",
        "goal": rk_playbook_draft()["goal"],
        "triggers": [
            {
                "kind": "interval",
                "message": (
                    "Еженедельная подготовка: понедельник 09:00–10:00 "
                    "перед вторничным заседанием РК"
                ),
                "interval_value": 10,
                "interval_unit": "minutes",
                "weekdays": [0],
                "window_start": "09:00",
                "window_end": "10:00",
                "once": False,
            }
        ],
    }


def rk_playbook_draft() -> dict[str, Any]:
    checklist = "; ".join(_CHECKLIST_ITEMS)
    return {
        "status": "verified",
        "title": "Подготовка заседаний Ревизионной комиссии",
        "goal": (
            "К каждому вторничному заседанию РК собрать проект повестки и фактические "
            "перечни: открытые поручения, просрочки, предписания, сроки расследований, "
            "документы на закрытие и вопросы Руководителю РК. После заседания — "
            "черновик протокола только из Word-расшифровки."
        ),
        "result": (
            "Проект повестки, перечни поручений/просрочек/предписаний/расследований "
            "и документов на закрытие; вопросы Руководителю РК; при расшифровке — "
            "черновик протокола."
        ),
        "when_to_run": (
            "Каждый понедельник 09:00–10:00 (перед вторничным заседанием РК) "
            "и по кнопке с материалами / Word-расшифровкой."
        ),
        "run_inputs": [
            {
                "id": "work_plan",
                "label": "План работ РК",
                "required": False,
                "accept": [".docx", ".pdf", ".xlsx"],
            },
            {
                "id": "assignments_registry",
                "label": "Excel-реестр поручений Секретаря РК",
                "required": False,
                "accept": [".xlsx", ".xlsm"],
            },
            {
                "id": "transcript",
                "label": "Word-расшифровка после заседания",
                "required": False,
                "accept": [".docx"],
            },
        ],
        "steps": [
            {
                "id": "s1",
                "title": "Дата заседания РК в Outlook",
                "system": "outlook",
                "entity": "calendar_event",
                "operation": "list",
                "required_params": [],
                "done_when": "Подтверждена дата ближайшего вторничного заседания РК (тема, время).",
            },
            {
                "id": "s2",
                "title": "Поручения и задачи 1С",
                "system": "onec",
                "entity": "task",
                "operation": "list",
                "required_params": [],
                "done_when": "Собраны открытые поручения, просрочки и задачи документооборота из 1С.",
            },
            {
                "id": "s2b",
                "title": "Протоколы РК на проверку",
                "system": "onec",
                "entity": "protocol",
                "operation": "list",
                "required_params": ["meeting_kind"],
                "done_when": "Найдены протоколы Document_ТД_Протокол с префиксом РК за период заседания.",
            },
            {
                "id": "s3",
                "title": "Документы и вложения 1С по РК",
                "system": "onec",
                "entity": "document",
                "operation": "search",
                "required_params": [],
                "done_when": "Найдены карточки/вложения по предписаниям и закрытию поручений.",
            },
            {
                "id": "s4",
                "title": "Реестр поручений Excel",
                "system": "desktop",
                "entity": "spreadsheet",
                "operation": "read",
                "required_params": ["filename"],
                "done_when": "Прочитан реестр из materials/attachments или сетевой папки.",
            },
            {
                "id": "s5",
                "title": "Сверка 1С и Excel",
                "system": "constructor",
                "entity": "checklist",
                "operation": "read",
                "required_params": [],
                "done_when": "Расхождения показаны обеими датами, Excel не изменён.",
            },
            {
                "id": "s6",
                "title": "Повестка и отчёты",
                "system": "desktop",
                "entity": "report",
                "operation": "export",
                "required_params": ["filename"],
                "done_when": f"Готов проект повестки и перечни по чек-листу §15: {checklist}.",
            },
        ],
        "runtime": {
            "kind": "revision_commission",
            "tools": rk_runtime_tools(),
        },
    }


def rk_playbook_instructions() -> str:
    checklist = "\n".join(f"- {item}" for item in _CHECKLIST_ITEMS)
    return (
        "Агент «Подготовка заседаний Ревизионной комиссии» (ПЛ-01-001).\n"
        "Порядок работы на каждый запуск:\n"
        "1. Outlook: найди ближайшее вторничное заседание РК (`outlook.read_calendar`, "
        "фильтр по теме: ревизион, РК). Без подтверждённой даты — «Недостаточно данных», "
        "повестку с выдуманной датой не выпускай.\n"
        "2. 1С — поручения без фильтра по статусам ТЗ:\n"
        "   • `onec.erp_tasks_current` — открытые сейчас;\n"
        "   • `onec.erp_tasks_period` — за период (date_from/date_to);\n"
        "   • `onec.docflow_tasks` — документооборот;\n"
        "   • при необходимости `onec.search_documents` / `onec.get_document_card` по РК.\n"
        "3. Протоколы на проверку: `onec.meeting_protocols` с meeting_kind=rk и датой заседания "
        "(или date_from/date_to). Карточку — `onec.odata_get` по ref_key из ответа.\n"
        "4. Вложения 1С: `onec.list_attachments` → `onec.read_attachment`.\n"
        "5. Excel-реестр: сначала `excel.list_files` + `excel.read_workbook` из "
        "materials/attachments; если файла нет — `workspace.powershell_run` только "
        f"для чтения/копирования из {_RK_REGISTRY_HINT} или {_RK_SHARE_HINT} "
        "(без записи в сеть и без правки Excel).\n"
        "6. Сверь чек-лист ТЗ §15:\n"
        f"{checklist}\n"
        "7. Расхождение 1С/Excel — покажи оба срока, Excel не правь. Нет пункта — пробел, "
        "не подставляй. Без Word-расшифровки протокол не готовь.\n"
        "8. Исключи из повестки тестовые пробы Constructor в 1С (номер/тема/комментарий "
        "содержит «Constructor», «проба Constructor», «тестовая проба»).\n"
        "9. Сбор данных — один проход: не перезапускай outlook/1С/Excel/сеть повторно "
        "и не пиши «данные устарели, собираю заново». Сетевую папку читай одной попыткой "
        "(лёгкий список файлов); при таймауте 90 с продолжай с 1С и materials/attachments.\n"
        "10. Если в Outlook нет вторничного заседания РК — в итоге явно «Недостаточно данных: "
        "дата заседания не найдена», но перечни по 1С/Excel всё равно выпусти.\n"
        "11. Сначала `report.export_document` (проект повестки и перечни), потом один блок "
        "## WORK_RESULT. Если даты вторника нет — файл всё равно выпусти, в итоге "
        "«Недостаточно данных». Промежуточный ход — только в thinking. "
        "Повестку и протокол не утверждай."
    )


def rk_local_playbook(*, title: str, demo_text: str = "", answered_scope: str = "") -> dict[str, Any]:
    scope = (answered_scope or "").strip()
    scope_line = f"Объём запуска:\n{scope}\n\n" if scope else ""
    summary = (demo_text or rk_playbook_instructions()).strip()
    if len(summary) > 2500:
        summary = summary[:2500] + "…"
    return {
        "instructions": f"{scope_line}{rk_playbook_instructions()}",
        "example_run": summary,
        "demo_ok": True,
        "tools": rk_runtime_tools(),
        "name": title or "Подготовка заседаний Ревизионной комиссии",
        "expected_result": rk_playbook_draft()["result"],
        "triggers": rk_schedule_draft()["triggers"],
        "when_to_run": rk_playbook_draft()["when_to_run"],
        "steps": rk_playbook_draft()["steps"],
    }


def apply_rk_config(local_run: dict[str, Any] | None, *, title: str, notes: str) -> dict[str, Any]:
    local = dict(local_run or {})
    blob = f"{title} {notes}"
    if not is_rk_meeting_agent(blob):
        return local
    draft = rk_playbook_draft()
    playbook = rk_local_playbook(title=title or draft["title"], demo_text=notes)
    local["playbook"] = playbook
    local["playbook_draft"] = draft
    local["schedule_draft"] = rk_schedule_draft()
    local["runtime"] = str(local.get("runtime") or "mcp")
    local["tools"] = rk_runtime_tools()
    local["ui_mode"] = "chat"
    return local


def apply_rk_plan_runtime(plan_data: dict[str, Any] | None, *, title: str, notes: str) -> dict[str, Any]:
    plan = dict(plan_data or {})
    if not is_rk_meeting_agent(title, notes, plan.get("goal") or ""):
        return plan
    seed = rk_playbook_draft()
    runtime = dict(plan.get("runtime") or {})
    runtime["kind"] = "revision_commission"
    runtime["tools"] = rk_runtime_tools()
    plan["runtime"] = runtime
    plan["steps"] = seed["steps"]
    if not (plan.get("goal") or "").strip():
        plan["goal"] = seed["goal"]
    if not (plan.get("title") or "").strip():
        plan["title"] = title or seed["title"]
    return plan

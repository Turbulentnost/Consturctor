"""Playbook for «Ежедневный контроль поручений по 1С ERP и Excel»."""

from __future__ import annotations

from typing import Any

CUSTOMER = "Амураль Игорь Борисович"

_TITLE_HINTS = (
    "ежедневный контроль поручений",
    "контроль поручений по 1с",
    "контроль поручений по 1c",
    "аст00 и action tracker",
)


def is_daily_assignment_agent(*parts: str) -> bool:
    blob = " ".join(str(part or "") for part in parts).casefold()
    from app.services.workflows.artifact_close_playbook import is_artifact_close_agent
    from app.services.workflows.rk_meeting_playbook import is_rk_meeting_agent
    from app.services.workflows.sd_meeting_playbook import is_sd_meeting_agent

    if is_artifact_close_agent(blob) or is_rk_meeting_agent(blob) or is_sd_meeting_agent(blob):
        return False
    return any(hint in blob for hint in _TITLE_HINTS)


def daily_assignment_runtime_tools() -> list[str]:
    return [
        "users.current",
        "excel.list_files",
        "excel.write_action_tracker",
        "onec.erp_assignments",
        "onec.meeting_protocols",
        "onec.erp_assignments_write",
    ]


def daily_assignment_playbook_draft() -> dict[str, Any]:
    return {
        "status": "verified",
        "title": "Ежедневный контроль поручений по 1С ERP и Excel",
        "goal": (
            "Снять все поручения АСТ00 заказчика Амураль Игорь Борисович "
            "и протоколы с пометкой ПСД, записать их в Action Tracker."
        ),
        "result": (
            "Action Tracker содержит все поручения журнала и все протоколы ПСД. "
            "Устный доклад: сколько записано, какие новые, какие просрочены."
        ),
        "when_to_run": "Каждое рабочее утро к 07:50; днём раз в час с 08:00 до 17:00.",
        "run_inputs": [],
        "recipient": CUSTOMER,
        "steps": [
            {
                "id": "s1",
                "title": "Оператор сессии",
                "required": True,
                "system": "constructor",
                "entity": "user",
                "operation": "read",
                "tool": "users.current",
                "data_expectation": "ФИО и id оператора сессии",
                "done_when": "Есть user.fio",
                "on_empty": "Остановить прогон: сессия пустая",
            },
            {
                "id": "s2",
                "title": "Найти файл Action Tracker",
                "required": True,
                "system": "desktop",
                "entity": "spreadsheet",
                "operation": "list",
                "tool": "excel.list_files",
                "data_expectation": "xlsx Action Tracker в рабочей папке, если он уже есть",
                "done_when": "Список файлов получен",
                "on_empty": "Файла нет — создать после выборки 1С",
            },
            {
                "id": "s4",
                "title": "Все поручения АСТ00",
                "required": True,
                "system": "onec",
                "entity": "assignment",
                "operation": "list",
                "tool": "onec.erp_assignments",
                "proven_call": {
                    "tool": "onec.erp_assignments",
                    "arguments": {
                        "action": "list",
                        "customer": CUSTOMER,
                        "include_all": True,
                        "only_open": False,
                        "limit": 100,
                    },
                },
                "data_expectation": (
                    f"Все поручения АСТ00 заказчика {CUSTOMER} — любые статусы, "
                    "не только открытые и просроченные: номер, статус, владелец, срок, формулировка"
                ),
                "done_when": "Получен полный список журнала этого заказчика",
                "on_empty": "Зафиксируй пустую выборку поручений и всё равно сними протоколы ПСД",
                "on_error": (
                    "Повтори тот же action=list с include_all=true и customer="
                    f"{CUSTOMER}; не сужай до only_open"
                ),
            },
            {
                "id": "s5",
                "title": "Протоколы с пометкой ПСД",
                "required": True,
                "system": "onec",
                "entity": "protocol",
                "operation": "list",
                "tool": "onec.meeting_protocols",
                "proven_call": {
                    "tool": "onec.meeting_protocols",
                    "arguments": {
                        "meeting_kind": "sd",
                        "psd_mark": True,
                        "review_only": False,
                        "include_closed": True,
                        "max_results": 100,
                    },
                },
                "data_expectation": (
                    "Протоколы Document_ТД_Протокол с пометкой ПСД "
                    "(номер начинается с ПСД). Все статусы, включая закрытые. "
                    "Не брать РК, СПГ и операционные СД без префикса ПСД. "
                    "Не фильтровать «открытые и просроченные»."
                ),
                "done_when": "Получен список протоколов ПСД",
                "on_empty": "Протоколов ПСД нет — в трекер идут только поручения",
                "on_error": "Повтори onec.meeting_protocols с psd_mark=true; не снимай все открытые протоколы",
            },
            {
                "id": "s6",
                "title": "Записать обе выборки в Action Tracker",
                "required": True,
                "system": "desktop",
                "entity": "spreadsheet",
                "operation": "export",
                "tool": "excel.write_action_tracker",
                "required_params": ["filename"],
                "proven_call": {
                    "tool": "excel.write_action_tracker",
                    "arguments": {"filename": "ActionTracker.xlsx"},
                },
                "data_expectation": (
                    "Один вызов без списка строк. Инструмент сам читает последние "
                    "tool_results поручений и протоколов и пишет все карточки в ActionTracker.xlsx. "
                    "count в ответе равен числу поручений и числу протоколов."
                ),
                "done_when": "Файл содержит все поручения s4 и все протоколы s5",
                "on_empty": "Если обе выборки пустые — файл только с шапкой",
                "on_error": "Не собирай строки сам и не открывай JSON. Повтори тот же вызов.",
            },
            {
                "id": "s7",
                "title": "Запись в 1С только при расхождении",
                "required": False,
                "system": "onec",
                "entity": "assignment",
                "operation": "update",
                "tool": "onec.erp_assignments_write",
                "data_expectation": (
                    "Только после подтверждения человека и только если есть что менять. "
                    "Закрытие «исполнено» — только после устного разрешения Амураля И.Б."
                ),
                "done_when": "Расхождения записаны либо их нет",
                "on_empty": "Расхождений нет — шаг пропустить",
            },
        ],
    }


def daily_assignment_instructions() -> str:
    return (
        "Цель: снять все поручения АСТ00 заказчика Амураль Игорь Борисович "
        "и протоколы с пометкой ПСД, записать их в Action Tracker.\n"
        "Заказчик журнала поручений всегда Амураль Игорь Борисович, не оператор сессии.\n"
        "Повтори проверенную цепочку. Не составляй новый маршрут.\n"
        "Поручения: один вызов `onec.erp_assignments` action=list "
        f"(customer={CUSTOMER}, include_all=true, only_open=false, серия кириллица АСТ00). "
        "Бери все статусы, не только открытые и просроченные.\n"
        "Протоколы: один вызов `onec.meeting_protocols` "
        "(meeting_kind=sd, psd_mark=true, review_only=false, include_closed=true). "
        "Пометка ПСД = номер начинается с «ПСД». Не снимай все открытые/просроченные протоколы, "
        "не бери РК и СПГ.\n"
        "Excel: после обеих выборок один вызов `excel.write_action_tracker` "
        "(filename=ActionTracker.xlsx). Строки не передавай. JSON result_file не открывай "
        "и не читай страницами: инструмент сам записывает все поручения и все протоколы ПСД. "
        "Число строк в ответе равно count выборок. Не читай старый ActionTracker.xlsx, "
        "картинки и вложения. Не вызывай excel.read_workbook, excel.create_workbook, "
        "excel.edit_workbook и office.read_file.\n"
        "Запись в 1С только onec.erp_assignments_write после подтверждения и только если есть что менять.\n"
        "Запрещено: Task, OCR, onec.erp_tasks_*, action=tasks, onec.odata_get, "
        "карточки по одной, Outlook, фильтр only_open по поручениям, "
        "фильтр «открытые/просроченные» по протоколам.\n"
        "Итог — трекер обновлён, устный доклад, затем ## WORK_RESULT."
    )


def daily_assignment_local_playbook(*, title: str = "") -> dict[str, Any]:
    draft = daily_assignment_playbook_draft()
    return {
        "name": title or draft["title"],
        "status": "verified",
        "demo_ok": True,
        "instructions": daily_assignment_instructions(),
        "example_run": (
            "## WORK_RESULT\n"
            "В журнал АСТ00 сняты все поручения заказчика Амураль И.Б., без отсечения "
            "открытых/просроченных. Протоколы — только с пометкой ПСД (номер ПСД_*). "
            "Обе выборки записаны в Action Tracker.\n"
            "TESTS: PASS"
        ),
        "expected_result": draft["result"],
        "when_to_run": draft["when_to_run"],
        "run_inputs": [],
        "triggers": [],
        "steps": draft["steps"],
        "tools": daily_assignment_runtime_tools(),
    }


def apply_daily_assignment_config(
    local_run: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    local = dict(local_run or {})
    if not is_daily_assignment_agent(title, notes):
        return local
    draft = daily_assignment_playbook_draft()
    playbook = daily_assignment_local_playbook(title=title or draft["title"])
    local["playbook"] = playbook
    local["playbook_draft"] = {**draft, "run_inputs": []}
    local["runtime"] = str(local.get("runtime") or "mcp")
    allowed = set(daily_assignment_runtime_tools())
    local["tools"] = daily_assignment_runtime_tools()
    invoked = local.get("live_tools_invoked")
    if isinstance(invoked, list):
        local["live_tools_invoked"] = [name for name in invoked if name in allowed]
    local["ui_mode"] = "chat"
    return local


def apply_daily_assignment_plan_runtime(
    plan_data: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    plan = dict(plan_data or {})
    if not is_daily_assignment_agent(title, notes, plan.get("goal") or ""):
        return plan
    seed = daily_assignment_playbook_draft()
    runtime = dict(plan.get("runtime") or {})
    runtime["kind"] = "onec"
    runtime["tools"] = daily_assignment_runtime_tools()
    plan["runtime"] = runtime
    plan["steps"] = seed["steps"]
    plan["run_inputs"] = []
    if not (plan.get("goal") or "").strip():
        plan["goal"] = seed["goal"]
    if not (plan.get("title") or "").strip():
        plan["title"] = title or seed["title"]
    return plan

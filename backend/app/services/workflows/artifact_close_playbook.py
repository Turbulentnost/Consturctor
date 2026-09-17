"""Playbook for «Проверка артефактов и предложение поручений к закрытию»."""

from __future__ import annotations

from typing import Any

_TITLE_HINTS = (
    "проверка артефактов",
    "предложение поручений к закрытию",
    "предложение к закрытию поручений",
)


def is_artifact_close_agent(*parts: str) -> bool:
    blob = " ".join(str(part or "") for part in parts).casefold()
    return any(hint in blob for hint in _TITLE_HINTS)


def artifact_close_runtime_tools() -> list[str]:
    return [
        "users.current",
        "onec.erp_assignments",
        "onec.erp_assignments_write",
        "onec.download_artifact",
        "office.read_file",
        "excel.list_files",
        "excel.read_workbook",
        "report.export_document",
    ]


def artifact_close_playbook_draft() -> dict[str, Any]:
    return {
        "status": "verified",
        "title": "Проверка артефактов и предложение поручений к закрытию",
        "goal": (
            "Снять все открытые поручения АСТ00, скачать исполнительские файлы "
            "из карточек 1С, сверить каждый файл с предметом поручения и решить: "
            "рекомендовать закрытие или нет."
        ),
        "result": (
            "Word: по каждому открытому поручению вывод «рекомендовать закрытие», "
            "«частично», «не подтверждает» или «недостаточно данных», с указанием файлов. "
            "Статус в 1С не менять без подтверждения человека."
        ),
        "when_to_run": "Рабочие дни 09:00–10:00 и по кнопке.",
        "run_inputs": [],
        "steps": [
            {
                "id": "s1",
                "title": "Оператор сессии",
                "required": True,
                "system": "constructor",
                "entity": "user",
                "operation": "read",
                "tool": "users.current",
                "done_when": "Есть user.fio",
            },
            {
                "id": "s2",
                "title": "Все открытые поручения АСТ00",
                "required": True,
                "system": "onec",
                "entity": "assignment",
                "operation": "list",
                "tool": "onec.erp_assignments",
                "proven_call": {
                    "tool": "onec.erp_assignments",
                    "arguments": {
                        "action": "list",
                        "only_open": True,
                        "include_files": True,
                        "limit": 100,
                    },
                },
                "data_expectation": (
                    "Все открытые карточки АСТ00: номер, статус, предмет, срок, "
                    "исполнитель, список файлов вкладки. Без фильтра по заказчику "
                    "и без фильтра по словам ТЗ."
                ),
                "done_when": "Получен полный список открытых поручений или пустой журнал.",
                "on_empty": (
                    "Зафиксируй: открытых поручений нет. Word с пустым списком. "
                    "Не ищи задачи исполнителя, протоколы, календарь и сетевые папки."
                ),
                "on_error": (
                    "Повтори тот же action=list; не переключайся на tasks, "
                    "odata_get, протоколы и Outlook."
                ),
            },
            {
                "id": "s3",
                "title": "Скачать исполнительские файлы карточек",
                "required": True,
                "system": "onec",
                "entity": "file",
                "operation": "read",
                "tool": "onec.download_artifact",
                "data_expectation": (
                    "Содержимое вложений каждой открытой карточки из s2.files. "
                    "Скан самой карточки и служебный .epf не считать артефактом."
                ),
                "done_when": (
                    "По каждой карточке с файлами вложения скачаны либо "
                    "зафиксировано, что файлов нет."
                ),
                "on_empty": (
                    "Нет файлов — по этой карточке «недостаточно данных», "
                    "закрытие не рекомендовать, перейти к следующей."
                ),
                "on_error": (
                    "По этой карточке «недостаточно данных», остальные продолжить."
                ),
            },
            {
                "id": "s4",
                "title": "Прочитать текст и сканы артефактов",
                "required": True,
                "system": "desktop",
                "entity": "file",
                "operation": "read",
                "tool": "office.read_file",
                "data_expectation": (
                    "Текст/OCR каждого скачанного файла. Word/PDF/картинки — "
                    "office.read_file, Excel — excel.read_workbook. "
                    "Встроенные Read и Grep для docx/pdf/xlsx/jpg не вызывать."
                ),
                "done_when": "По каждому скачанному файлу есть текст или явная ошибка чтения.",
                "on_empty": "Файл не читается — «недостаточно данных» по этой карточке.",
                "on_error": "Считать данные недостаточными по файлу, карточку не закрывать.",
            },
            {
                "id": "s5",
                "title": "Сверить артефакт с предметом поручения",
                "required": True,
                "system": "constructor",
                "entity": "checklist",
                "operation": "read",
                "data_expectation": (
                    "По каждой карточке: тема, даты, результат, подписи и критерий "
                    "приёмки совпадают с файлами исполнителя. Одного факта вложения мало."
                ),
                "done_when": (
                    "По каждому открытому поручению есть одно решение: "
                    "рекомендовать закрытие / частично / не подтверждает / недостаточно данных."
                ),
            },
            {
                "id": "s6",
                "title": "Word с решениями",
                "required": True,
                "system": "desktop",
                "entity": "report",
                "operation": "export",
                "tool": "report.export_document",
                "required_params": ["filename"],
                "done_when": "Выгружен Word со всеми открытыми поручениями и решениями.",
            },
            {
                "id": "s7",
                "title": "Запись «исполнено» только после HITL",
                "required": False,
                "system": "onec",
                "entity": "assignment",
                "operation": "update",
                "tool": "onec.erp_assignments_write",
                "data_expectation": (
                    "Статус «исполнено» только если артефакт подтвердил предмет "
                    "и человек подтвердил запись. Иначе шаг пропустить."
                ),
                "done_when": "Подтверждённые карточки обновлены либо менять было нечего.",
                "on_empty": "Подтверждения нет — статус не писать.",
                "on_error": "Не повторять запись наугад.",
            },
        ],
        "runtime": {
            "kind": "assignment_artifacts",
            "tools": artifact_close_runtime_tools(),
        },
    }


def artifact_close_instructions() -> str:
    return (
        "Агент «Проверка артефактов и предложение поручений к закрытию».\n"
        "Это не подготовка заседания РК и не контроль календаря.\n"
        "Порядок на каждый запуск:\n"
        "1. `users.current`.\n"
        "2. Все открытые поручения: один вызов `onec.erp_assignments` "
        "action=list, only_open=true, include_files=true, limit=100. "
        "Без customer, без фильтра по статусам ТЗ, без onec.erp_tasks_*, "
        "без onec.docflow_tasks, без onec.odata_get, без Outlook, "
        "без сетевых папок РК и без вопроса про Excel-реестр.\n"
        "3. По каждой карточке, где есть files: `onec.download_artifact` "
        "(file_id из списка). Скан карточки и `.epf` пропусти.\n"
        "4. Прочитай файлы: Word/PDF/картинки — `office.read_file`, "
        "Excel — `excel.read_workbook`. Не вызывай Read/Grep/OCR-скрипты.\n"
        "5. Сверь артефакт с предметом, датами, результатом и подписями. "
        "Решение по карточке: «рекомендовать закрытие» / «частично» / "
        "«не подтверждает» / «недостаточно данных». "
        "Без читаемого артефакта закрытие не рекомендуй (п. 6.4.5 и 6.6.5).\n"
        "6. `report.export_document` — Word со всеми открытыми поручениями "
        "и решениями. Потом один блок ## WORK_RESULT.\n"
        "7. `onec.erp_assignments_write` только после подтверждения человека "
        "и только по карточкам «рекомендовать закрытие». "
        "CLOSED / «Исполнено» сам не ставь.\n"
        "Запрещено: дата заседания, повестка, план работ РК, "
        "\\\\192.168.1.198\\Files\\24.Ревизионная комиссия, "
        "спрашивать реестр или файлы запуска, останавливаться из‑за "
        "«Недостаточно данных: дата заседания не найдена»."
    )


def artifact_close_local_playbook(*, title: str, demo_text: str = "") -> dict[str, Any]:
    summary = (demo_text or artifact_close_instructions()).strip()
    if len(summary) > 2500:
        summary = summary[:2500] + "…"
    draft = artifact_close_playbook_draft()
    return {
        "instructions": artifact_close_instructions(),
        "example_run": summary,
        "demo_ok": True,
        "tools": artifact_close_runtime_tools(),
        "name": title or draft["title"],
        "expected_result": draft["result"],
        "triggers": [],
        "when_to_run": draft["when_to_run"],
        "steps": draft["steps"],
        "run_inputs": [],
        "status": "verified",
    }


def apply_artifact_close_config(
    local_run: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    local = dict(local_run or {})
    if not is_artifact_close_agent(title, notes):
        return local
    draft = artifact_close_playbook_draft()
    playbook = artifact_close_local_playbook(title=title or draft["title"], demo_text=notes)
    local["playbook"] = playbook
    local["playbook_draft"] = {**draft, "run_inputs": []}
    local["runtime"] = str(local.get("runtime") or "mcp")
    local["tools"] = artifact_close_runtime_tools()
    local["ui_mode"] = "chat"
    return local


def apply_artifact_close_plan_runtime(
    plan_data: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    plan = dict(plan_data or {})
    if not is_artifact_close_agent(title, notes, plan.get("goal") or ""):
        return plan
    seed = artifact_close_playbook_draft()
    runtime = dict(plan.get("runtime") or {})
    runtime["kind"] = "assignment_artifacts"
    runtime["tools"] = artifact_close_runtime_tools()
    plan["runtime"] = runtime
    plan["steps"] = seed["steps"]
    plan["run_inputs"] = []
    if not (plan.get("goal") or "").strip():
        plan["goal"] = seed["goal"]
    if not (plan.get("title") or "").strip():
        plan["title"] = title or seed["title"]
    return plan

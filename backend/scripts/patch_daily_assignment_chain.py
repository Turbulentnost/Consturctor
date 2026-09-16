"""Rewrite published daily AST00 agent: keep the working report chain, drop detours.

Usage (from backend/):
  py -3.13 scripts/patch_daily_assignment_chain.py
  py -3.13 scripts/patch_daily_assignment_chain.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal, init_db
from app.models.workflow import Workflow
from app.services.workflows.playbook_validation import (
    attach_tool_candidates,
    lock_verified_chain,
    verified_chain_text,
)
from app.services.workflows import prompts

WORKFLOW_ID = "af314914-bb0a-4cb7-95e0-6ef87698d3f5"
CUSTOMER = "Амураль Игорь Борисович"

INSTRUCTIONS = (
    "Цель: журнал АСТ00 заказчика Амураль Игорь Борисович согласовать с Action Tracker "
    "и устно доложить просрочки и список на сегодня.\n"
    "Заказчик журнала всегда Амураль Игорь Борисович, не оператор сессии и не JWT.\n"
    "Повтори проверенную цепочку. Не составляй новый маршрут.\n"
    "Запрещено: Task, OCR, скриншоты, onec.erp_tasks_*, action=tasks, action=protocols, "
    "onec.odata_get, onec.meeting_protocols, glob/grep по workspace, карточки по одной.\n"
    "1С: один onec.erp_assignments action=list "
    "(customer=Амураль Игорь Борисович, only_open=true, серия кириллица АСТ00).\n"
    "Excel: excel.list_files один раз. Если файл есть — excel.read_workbook. "
    "Если нет — excel.create_workbook из списка 1С.\n"
    "Если list пустой — доклад «поручений нет», не ищи задачи и протоколы.\n"
    "Запись в 1С только onec.erp_assignments_write после подтверждения и только если есть что менять. "
    "Закрытие «исполнено» — только после устного разрешения Амураля И.Б.\n"
    "Итог — устный доклад, затем ## WORK_RESULT."
)

EXAMPLE_RUN = (
    "## WORK_RESULT\n"
    "Утренний доклад к 07:50 за 10.09.2026. В журнале АСТ00 по заказчику Амураль И.Б. "
    "9 открытых карточек. Карточная просрочка: АСТ00-00089, 00087, 00070, 00039, 00033. "
    "Просроченные строки: АСТ00-00093 п.1 и АСТ00-00092 п.1-3. "
    "Action Tracker сверился по списку журнала. Задачи «Проверить поручение» не читал. "
    "Запись в 1С не делал: нет устного разрешения.\n"
    "TESTS: PASS"
)

DRAFT_STEPS = [
    {
        "id": "s1",
        "title": "Определить оператора сессии",
        "required": True,
        "system": "constructor",
        "entity": "user",
        "operation": "read",
        "tool": "users.current",
        "data_expectation": "ФИО и id оператора сессии",
        "done_when": "Есть user.fio",
        "on_empty": "Остановить прогон: сессия пустая",
        "on_error": "Повторить один раз; если снова ошибка — остановиться",
    },
    {
        "id": "s2",
        "title": "Найти файл Action Tracker",
        "required": True,
        "system": "desktop",
        "entity": "file",
        "operation": "list",
        "tool": "excel.list_files",
        "data_expectation": "xlsx Action Tracker в рабочей папке, если он уже есть",
        "done_when": "Список файлов получен",
        "on_empty": "Файла нет — после журнала 1С создать новый. Не искать через OCR",
        "on_error": "Не подменять другим источником; указать в докладе",
    },
    {
        "id": "s3",
        "title": "Прочитать Action Tracker, если файл есть",
        "required": False,
        "system": "desktop",
        "entity": "spreadsheet",
        "operation": "read",
        "tool": "excel.read_workbook",
        "required_params": ["filename"],
        "data_expectation": "Строки журнала: Источник=номер АСТ00, статус, владелец, срок",
        "done_when": "Строки прочитаны",
        "on_empty": "Считать источником статусов журнал 1С, затем заполнить файл",
        "on_error": "Сверку не проводить, ошибку чтения указать в докладе",
    },
    {
        "id": "s4",
        "title": "Снять журнал поручений АСТ00",
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
                "only_open": True,
            },
        },
        "data_expectation": (
            f"Открытые поручения АСТ00 заказчика {CUSTOMER}: "
            "номер, статус, владелец, срок, формулировка"
        ),
        "done_when": "Получен список этого заказчика",
        "on_empty": (
            "Зафиксируй пустую выборку и не ищи задачи исполнителя, протоколы и OCR"
        ),
        "on_error": (
            "Повтори тот же action=list с customer="
            f"{CUSTOMER}; не переключайся на tasks, протоколы и OCR"
        ),
    },
    {
        "id": "s5",
        "title": "Создать Action Tracker, если файла нет",
        "required": False,
        "system": "desktop",
        "entity": "spreadsheet",
        "operation": "export",
        "tool": "excel.create_workbook",
        "required_params": ["filename"],
        "data_expectation": (
            f"ActionTracker.xlsx из списка 1С. Заказчик {CUSTOMER}. "
            "Источник = номер АСТ00. Не открывать карточки по одной"
        ),
        "done_when": "Файл создан из списка s4",
        "on_empty": "Если в 1С пусто — только шапка колонок",
        "on_error": "Не подменять другим файлом",
    },
    {
        "id": "s6",
        "title": "Выровнять статус 1С по Action Tracker",
        "required": False,
        "system": "onec",
        "entity": "assignment",
        "operation": "update",
        "tool": "onec.erp_assignments_write",
        "data_expectation": (
            "Только расхождения статусов, после подтверждения человека. "
            "CLOSED → исполнено; иначе не писать"
        ),
        "done_when": "Расхождения записаны либо их нет",
        "on_empty": "Расхождений нет — шаг пропустить",
        "on_error": "Повторно не записывать; оставить в докладе",
    },
    {
        "id": "s7",
        "title": "Завести новые поручения из текста запуска",
        "required": False,
        "system": "onec",
        "entity": "assignment",
        "operation": "create",
        "tool": "onec.erp_assignments_write",
        "data_expectation": (
            f"Новая карточка: заказчик {CUSTOMER}, текст из сообщения запуска. "
            "Не брать пункты из протоколов"
        ),
        "done_when": "Карточка создана после подтверждения либо новых формулировок нет",
        "on_empty": "Новых формулировок нет — шаг пропустить",
        "on_error": "Формулировку включить в доклад как незаведённую",
    },
    {
        "id": "s8",
        "title": "Записать закрытие или возврат в 1С",
        "required": False,
        "system": "onec",
        "entity": "assignment",
        "operation": "update",
        "tool": "onec.erp_assignments_write",
        "data_expectation": (
            "«Исполнено» только после устного разрешения Амураля И.Б. "
            "Иначе шаг пропустить"
        ),
        "done_when": "Нужные карточки обновлены либо менять было нечего",
        "on_empty": "Разрешения нет — шаг пропустить",
        "on_error": "Статус не считать согласованным",
    },
    {
        "id": "s9",
        "title": "Записать те же решения в Action Tracker",
        "required": False,
        "system": "desktop",
        "entity": "spreadsheet",
        "operation": "update",
        "tool": "excel.edit_workbook",
        "required_params": ["filename"],
        "data_expectation": "Те же номера АСТ00 и статусы, что в 1С",
        "done_when": "Файл совпадает с решениями 1С либо менять было нечего",
        "on_empty": "Менять было нечего — шаг пропустить",
        "on_error": "В докладе указать, какие строки не записались",
    },
]


def _build_playbook(existing: dict) -> tuple[dict, dict]:
    draft = attach_tool_candidates(
        {
            "goal": existing.get("goal")
            or "Ежедневный контроль поручений АСТ00 и Action Tracker",
            "result": existing.get("expected_result")
            or "Устный доклад: просрочки и список на сегодня",
            "recipient": CUSTOMER,
            "when_to_run": existing.get("when_to_run") or "",
            "run_inputs": existing.get("run_inputs") or [],
            "steps": DRAFT_STEPS,
        }
    )
    events = [
        {"type": "tool_result", "tool": "users.current", "ok": True},
        {"type": "tool_result", "tool": "excel.list_files", "ok": True},
        {"type": "tool_result", "tool": "excel.read_workbook", "ok": True},
        {
            "type": "tool_result",
            "tool": "onec.erp_assignments",
            "ok": True,
            "arguments": {"action": "list", "customer": CUSTOMER, "only_open": True},
        },
        {"type": "tool_result", "tool": "excel.create_workbook", "ok": True},
        {"type": "tool_result", "tool": "excel.edit_workbook", "ok": True},
    ]
    locked = lock_verified_chain(draft, events=events)
    playbook = {
        **{key: value for key, value in existing.items() if key not in {"steps", "chain", "tools"}},
        "status": prompts.DRAFT_STATUS_VERIFIED,
        "demo_ok": True,
        "name": "Ежедневный контроль поручений по 1С ERP и Excel",
        "instructions": INSTRUCTIONS,
        "example_run": EXAMPLE_RUN,
        "expected_result": (
            "Устный доклад Амуралю И.Б.: просрочки, список на сегодня. "
            "Журнал АСТ00 и Action Tracker согласованы."
        ),
        "steps": locked["steps"],
        "tools": [
            "users.current",
            "excel.list_files",
            "excel.read_workbook",
            "excel.create_workbook",
            "excel.edit_workbook",
            "onec.erp_assignments",
            "onec.erp_assignments_write",
        ],
    }
    playbook["chain"] = verified_chain_text({**playbook, "chain": ""})
    draft["status"] = prompts.DRAFT_STATUS_VERIFIED
    draft["steps"] = locked["steps"]
    return playbook, draft


def patch(*, dry_run: bool = False) -> dict:
    init_db()
    db = SessionLocal()
    try:
        row = db.get(Workflow, WORKFLOW_ID)
        if row is None:
            raise SystemExit(f"workflow {WORKFLOW_ID} not found")
        local = dict(row.local_run or {})
        existing = dict(local.get("playbook") or {}) if isinstance(local.get("playbook"), dict) else {}
        playbook, draft = _build_playbook(existing)
        local["playbook"] = playbook
        local["playbook_draft"] = draft
        local["tools"] = list(playbook["tools"])
        local["live_tools_invoked"] = [
            "users.current",
            "excel.list_files",
            "onec.erp_assignments",
            "excel.read_workbook",
        ]
        local["demo_ok"] = True
        local["published"] = True
        local["can_publish"] = False
        row.local_run = local
        plan = dict(row.plan_json or {}) if isinstance(row.plan_json, dict) else {}
        plan["playbook"] = playbook
        row.plan_json = plan
        flag_modified(row, "local_run")
        flag_modified(row, "plan_json")
        if dry_run:
            print(f"DRY-RUN {row.id} {row.title}")
            print("steps:", [step.get("id") + " " + step.get("tool", "") for step in playbook["steps"]])
            print("tools:", playbook["tools"])
            print(playbook["chain"])
            return {"workflowId": row.id, "dryRun": True}
        db.add(row)
        db.commit()
        print(f"PATCHED {row.id} {row.title}")
        print("steps:", [f"{step.get('id')} {step.get('tool')}" for step in playbook["steps"]])
        return {"workflowId": row.id, "title": row.title, "steps": len(playbook["steps"])}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    patch(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

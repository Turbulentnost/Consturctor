"""Seed published agent «Поручения АСТ00 по аудиозаписи совещания».

Отдельный агент, не протокол. Из аудиозаписи берёт только продиктованные поручения
(«поручаю», «поручение», «поручил», «поручено», «готовьте поручение») и создаёт
карточки Document_ТД_Поручения. Задачи протокола («нужно», «сделай» без этих слов)
не пишет.

Published to the Agent Library: phase=done, local_run.published=True,
status=published, purpose=functional.

The agent belongs to Ильченко Е.А. and runs on her computer (Orchestrator).
Agents never run on the server.

Usage (from backend/):
  py -3.13 scripts/seed_meeting_assignment_agent.py
  py -3.13 scripts/seed_meeting_assignment_agent.py --user <user-id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal, init_db
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.triggers.service import workflow_is_deleted

TITLE = "Поручения АСТ00 по аудиозаписи совещания"
OWNER_FIO = "Ильченко Екатерина Александровна"
OWNER_USER_ID = "A2DCC949FEDEC70D40318ABA83C618F4"

GOAL = (
    "Из аудиозаписи совещания создать карточки поручений АСТ00 только там, "
    "где поручение прямо диктуют. Исполнитель — ФИО из участников Outlook."
)

TOOLS = [
    "audio.transcribe",
    "audio.transcript",
    "onec.erp_assignments_write",
]

INSTRUCTIONS = """Ты — агент «Поручения АСТ00 по аудиозаписи совещания». Ты создаёшь карточки Document_ТД_Поручения (номер АСТ00). Протокол совещания не создаёшь и не дополняешь. Файлы расшифровки и протокола не пишешь. Уведомления не отправляешь.

Поручение — только реплика, в которой диктуют мероприятия карточки. Маркеры: «поручаю», «поручение», «поручил», «поручено», «готовьте поручение», «отдельным поручением». «Нужно», «надо», «сделай», «подготовь», «проверь», «задача» без этих слов — задача протокола, её не записывай. Доклад по уже выданному («было поручение», «поручение уже составлено», «согласно поручениям») — не новая карточка.

1. Возьми file_id аудио-вложения из задания. Если вложения нет — попроси приложить запись и остановись. Запомни данные совещания из Outlook, если они переданы: дата, организатор, участники. Участники — единственный список ФИО. Людей вне этого списка исполнителем не ставь и по фамилии в других справочниках не ищи.
2. Вызови audio.transcribe ровно один раз (file_id и names — ФИО участников Outlook, без строк «Совещания» и почтовых ящиков). Ответ — transcript_path, segment_count, parts, duration_sec. Повторно не вызывай. Если ошибка или segment_count=0 — в 1С не пиши и остановись: «расшифровка не получена».
3. Прочитай всю расшифровку: audio.transcript(transcript_path, part=1), затем part=2 … part=parts, без пропусков. Файл transcript_path напрямую не читай. После каждой части выпиши только продиктованные поручения: кто диктует, о чём, мероприятия, кому, срок, таймкод. Если в части маркеров нет — так и напиши.
4. Сведи поручения. Одно «поручаю» / «готовьте поручение» с несколькими действиями — одна карточка и несколько строк мероприятий. «Первое поручение», «второе поручение» и следующее «поручаю» про другой предмет — отдельные карточки. Повторы одной диктовки схлопни. Срок бери только произнесённый: «сегодня» и «завтра» — от даты совещания, «до 15-го» — 15-е число этого месяца (если день уже прошёл — следующего), «до конца недели» — пятница недели совещания, «месяц» — та же дата плюс месяц. Неназванный срок не выдумывай.
5. Исполнитель строки — точное ФИО из участников Outlook, если к этому человеку обратились по имени и отчеству или по фамилии и в списке он один. «Андрей Александрович» при одном таком участнике — его полное ФИО. Если тёзка не один, имя уменьшительное или человека нет в списке — поле исполнителя не передавай и напиши его в итоге как неразрешённого. Если диктующий тут же отменяет имя («какой Андрей, это вы разгребите») — это имя исполнителем не ставь.
6. Руководитель карточки (customer) — кто диктует поручение, если его ФИО есть среди участников или он организатор Outlook. Если говорящий не опознан — customer = организатор встречи из Outlook и так и скажи человеку. Без руководителя карточку не создавай.
7. Сразу после свода, в том же ходе, вызови onec.erp_assignments_write action="create" по одному разу на каждую карточку. Подтверждение человек даёт в карточке инструмента, в чате отдельного «да» не жди. Параметры:
   — topic — коротко, о чём поручение;
   — basis — «Устное поручение»;
   — customer — ФИО руководителя;
   — status — «Создано»;
   — due — общий срок YYYY-MM-DD, если он назван;
   — lines — мероприятия: {text, executor, due}. text — что сделать, без пересказа всей записи. executor и due строки не передавай, если их нет.
   Если инструмент не нашёл исполнителя в 1С — повтори эту карточку без executor и укажи ФИО в неразрешённых. Отклонённую человеком карточку не повторяй.
8. Итог: по каждой карточке номер АСТ00, тема, руководитель, строки (мероприятие, исполнитель или «не назван», срок). Затем, что не создано и почему. Если продиктованных поручений не было — так и напиши и в 1С ничего не отправляй.
"""

EXAMPLE_RUN = """Задача: аудио meeting.wav (file_id=f-1), дата совещания 2026-10-13, организатор Амураль Игорь Борисович, участники: Амураль Игорь Борисович, Долгих Андрей Александрович, Ильченко Екатерина Александровна.
1. Нашёл вложение f-1 и список Outlook.
2. audio.transcribe один раз → transcript_path, parts=2.
3. Часть 1: «готовьте поручение: подготовить приказ о запрете собеседований, срок сегодня» [32:40]. Часть 2: «Андрей Александрович, подбор земли, срок до 15-го» [01:19:46] — это второе поручение. «Нужно показать отчёт» без слова «поручение» не взял. «Поручение уже составлено» не взял.
4. Две карточки. Исполнитель подбора земли — Долгих Андрей Александрович, он один такой в списке. У приказа исполнитель не назван.
5. onec.erp_assignments_write action=create, customer=Амураль Игорь Борисович, basis=Устное поручение, topic=Запрет собеседований, due=2026-10-13, lines=[{text: Подготовить приказ о запрете собеседований в помещениях организации, due: 2026-10-13}].
   Второй вызов: topic=Подбор земли, due=2026-10-15, lines=[{text: Найти участок и договориться о покупке, executor: Долгих Андрей Александрович, due: 2026-10-15}].
6. Итог: АСТ00-… запрет собеседований, исполнитель не назван; АСТ00-… подбор земли, Долгих Андрей Александрович.
"""

STEPS = [
    {"id": "s1", "title": "Аудио и участники Outlook", "action": "file_id вложения и ФИО участников. Нет аудио — остановиться."},
    {"id": "s2", "title": "Расшифровка", "action": "audio.transcribe один раз. Повторно не вызывать."},
    {"id": "s3", "title": "Только продиктованные поручения", "action": "Читать все части. Брать реплики с «поручаю», «поручение», «поручил», «поручено», «готовьте поручение». Доклад по уже выданному и «нужно» без этих слов не брать."},
    {"id": "s4", "title": "Карточки и исполнители", "action": "Одно поручение — одна карточка, несколько мероприятий — строки. Исполнитель только точное ФИО из Outlook. Срок только произнесённый."},
    {"id": "s5", "title": "Запись АСТ00", "action": "onec.erp_assignments_write action=create на каждую карточку. Подтверждение — карточка инструмента. Назвать номера и кого не удалось поставить исполнителем."},
]


def _playbook() -> dict:
    return {
        "name": TITLE,
        "goal": GOAL,
        "instructions": INSTRUCTIONS.strip(),
        "example_run": EXAMPLE_RUN.strip(),
        "steps": STEPS,
        "tools": TOOLS,
    }


def _find_user(db, query: str) -> AppUser | None:
    query = (query or "").strip()
    if not query:
        return None
    user = db.get(AppUser, query)
    if user is not None:
        return user
    exact = db.query(AppUser).filter(AppUser.fio == query).all()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        preferred = next((item for item in exact if item.id == OWNER_USER_ID), None)
        return preferred or exact[0]
    return db.query(AppUser).filter(AppUser.fio.ilike(f"%{query.split()[0]}%")).first()


def _find_existing(db, user_id: str) -> Workflow | None:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.title == TITLE, Workflow.phase == "done")
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    for row in rows:
        if not workflow_is_deleted(row):
            return row
    return None


def _apply_playbook(row: Workflow) -> None:
    local = dict(row.local_run or {})
    local["playbook"] = _playbook()
    local["published"] = True
    local["status"] = "published"
    local["purpose"] = "functional"
    local["tools"] = TOOLS
    # Schedule fires on the owner's Orchestrator. Agents do not run on the server.
    local.pop("run_on_server", None)
    local.pop("kind", None)
    local.pop("unformed", None)
    row.local_run = local

    plan = dict(row.plan_json or {})
    plan["title"] = TITLE
    plan["goal"] = plan.get("goal") or GOAL
    runtime = dict(plan.get("runtime") or {})
    runtime["tools"] = TOOLS
    plan["runtime"] = runtime
    row.plan_json = plan

    row.phase = "done"
    if not (row.notes or "").strip():
        row.notes = GOAL
    flag_modified(row, "local_run")
    flag_modified(row, "plan_json")


def _adopted_copies(db, source_id: str) -> list[Workflow]:
    rows = (
        db.query(Workflow)
        .filter(Workflow.title == TITLE, Workflow.phase == "done", Workflow.id != source_id)
        .all()
    )
    out: list[Workflow] = []
    for row in rows:
        if workflow_is_deleted(row):
            continue
        local = row.local_run if isinstance(row.local_run, dict) else {}
        if str(local.get("library_source_id") or "").strip() == source_id:
            out.append(row)
    return out


def seed(*, user_query: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        if user_query:
            user = _find_user(db, user_query)
            if user is None:
                raise SystemExit(f"User not found: {user_query}")
        else:
            user = _find_user(db, OWNER_FIO)
            if user is None:
                raise SystemExit(f"User not found: {OWNER_FIO}")
        print(f"Owner: {user.fio} ({user.id})")

        row = _find_existing(db, user.id)
        created = row is None
        if row is None:
            row = Workflow(
                id=str(uuid4()),
                user_id=user.id,
                title=TITLE,
                phase="done",
                notes=GOAL,
            )
            db.add(row)

        row.title = TITLE
        _apply_playbook(row)
        db.flush()

        copies = _adopted_copies(db, row.id)
        for copy_row in copies:
            copy_row.title = TITLE
            _apply_playbook(copy_row)

        db.commit()
        db.refresh(row)
        print(f"workflow_id: {row.id}")
        print("created" if created else "updated")
        for copy_row in copies:
            print(f"adopted copy synced: {copy_row.id} (user {copy_row.user_id})")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed meeting assignment agent (published)")
    parser.add_argument(
        "--user",
        default="",
        help=f"Owner: user id or FIO (default: {OWNER_FIO})",
    )
    args = parser.parse_args()
    seed(user_query=args.user)


if __name__ == "__main__":
    main()

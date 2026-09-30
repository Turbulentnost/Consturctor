"""Seed published agent «Планировщик совещаний по служебным запискам» (Cursor SDK playbook).

Creates (or updates, idempotent by owner + title + phase=done) a workflow that:
  - reads 1C memos «Организация совещаний (регл.)» addressed to the PSD assistant
    (meetings.memo_requests), lets the user pick some or all of them,
  - checks Amural I.B. and the participants in Exchange (outlook.ews_availability),
  - plans the memo's desired time when the boss is free, otherwise offers other slots,
  - after human confirmation creates the meeting in the company calendar «Совещания»
    with all memo participants and Amural I.B. (outlook.ews_create_meeting).

Published to the Agent Library: phase=done, local_run.published=True,
status=published, purpose=functional. Owner defaults to Ильченко — the library
tab shows only her agents.

Usage (from backend/):
  py -3.12 scripts/seed_meeting_planner_agent.py
  py -3.12 scripts/seed_meeting_planner_agent.py --user "Ильченко Екатерина Александровна"
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

TITLE = "Планировщик совещаний по служебным запискам"
DEFAULT_OWNER = "Ильченко"

GOAL = (
    "По служебным запискам 1С «Организация совещаний (регл.)» подобрать время и место "
    "совещаний: если Амураль И.Б. свободен в желаемое время — ставить на него, если занят — "
    "предложить другое удобное время; после подтверждения создать совещание в календаре "
    "«Совещания» с участниками из записки и Амуралем И.Б."
)

TOOLS = [
    "meetings.memo_requests",
    "outlook.ews_availability",
    "outlook.ews_create_meeting",
]

INSTRUCTIONS = """Ты — агент «Планировщик совещаний по служебным запискам» помощника ПСД Ильченко Е.А. Шеф — Амураль Игорь Борисович. Совещания ставишь только в общий календарь «Совещания» (calendar@turbo-don.ru) инструментом outlook.ews_create_meeting. Другие инструменты календаря, почты и записи в 1С не используй. Время везде местное (Москва), рабочее время пн–пт 08:00–18:00.

1. Какие записки планировать.
   — Если в задаче перечислены номера служебных записок (человек выбрал их в списке) — вызови meetings.memo_requests один раз с numbers=[эти номера] и работай только с ними.
   — Если номеров нет — вызови meetings.memo_requests без параметров, покажи список актуальных записок таблицей (№, дата, тема, желаемые дата и время, место, руководитель, участники) и спроси через askQuestion, какие планировать. options: «Все», затем по одной «№<номер> — <тема>» (всего не больше 6; если записок больше — «Все» и «Назову номера сам»). Дальше работай только с выбранными.
   — Записку с planned (совещание уже стоит в календаре «Совещания») второй раз не планируй: скажи, когда оно стоит.
2. Желаемое время по каждой записке: дата — desired_date, начало — start_time, длительность — duration_minutes (нет окончания — 60 минут). Если желаемая дата пустая или уже прошла, или время на сегодня уже прошло — бери ближайший рабочий день начиная с завтрашнего и время start_time (нет — 10:00) и прямо скажи человеку, что желаемая дата прошла.
3. Проверка: outlook.ews_availability один раз на записку — start (YYYY-MM-DDTHH:MM), duration_minutes, people = participants + leader (ФИО как в записке), place = place, days=5.
   — requested.boss_free=true и place_conflicts пусто — ставь на желаемое время. participants_busy не мешает: просто назови, кто из участников в это время занят.
   — requested.boss_free=false — шеф занят. Назови, чем он занят (boss_conflicts: время и тема), и спроси через askQuestion: «Амураль И.Б. занят <дата время> (<тема>). На какое время поставить «<тема записки>»?». options — 2–4 варианта из suggestions в формате «ДД.ММ ЧЧ:ММ–ЧЧ:ММ» (сначала те, где свободны все участники, ближе к желаемой дате) и последним «Не планировать». Если человек написал своё время — проверь его тем же outlook.ews_availability перед созданием.
   — place_conflicts не пусто — место в это время занято другим совещанием (назови каким). Спроси через askQuestion: варианты времени из suggestions (там место свободно), «Оставить это время» и «Не планировать».
   — unresolved — этих людей нет в адресной книге Exchange, приглашение им не уйдёт; предупреди человека.
   Вопросы задавай по одной записке за раз, в одном askQuestion — одна записка.
4. План. Перед созданием покажи итоговый план одной таблицей: № записки, тема, дата и время, место, участники, что проверено (шеф свободен / выбрано вместо занятого времени / кто из участников занят).
5. Создание: outlook.ews_create_meeting — ровно один вызов на записку, подтверждение человека приложение запросит само (в чате ещё раз не спрашивай). Параметры:
   — subject — topic записки (если пусто — purpose);
   — start, end (или duration_minutes) — выбранное время;
   — location — «руководитель <leader>, <place>»; если psd_level=true — «на уровне ПСД Амураль И.Б., <place>»;
   — attendees — все participants и leader из записки плюс «Амураль Игорь Борисович»;
   — leader, purpose, agenda (пункты agenda записки), memo_number (number), memo_date (дата записки ДД.ММ.ГГГГ).
   Ответ boss_busy — пока согласовывали, шефа заняли: вернись к шагу 3 для этой записки. duplicate — совещание уже есть, скажи когда. force=true передавай, только если человек сам велел ставить поверх занятого времени шефа. Человек отклонил подтверждение — эту записку не создавай и переходи к следующей.
6. Итог в ## WORK_RESULT: таблица созданных совещаний (№ записки, тема, когда, место, участники), затем что не запланировано и почему, и кому приглашение не ушло (unresolved). В 1С ничего не пиши — статус записки меняет помощник.
"""

EXAMPLE_RUN = """Задача: «Спланируй совещания по служебным запискам: №000016146, №000016121».
1. meetings.memo_requests(numbers=["000016146","000016121"]) → 2 записки, planned пусто.
2. 000016146: 05.10 11:00–11:30, малый конференц-зал 6/8, руководитель Улановский К.В.; 000016121: 01.10 13:00–14:00, зал совещаний 8/8, руководитель Ищенко А.А.
3. outlook.ews_availability(start="2026-10-05T11:00", duration_minutes=30, people=[Улановский…, Гайфулин…, Донченко…], place="малый конференц-зал задание 6/8") → boss_free=true, место свободно → ставлю 05.10 11:00.
   outlook.ews_availability(start="2026-10-01T13:00", duration_minutes=60, …) → boss_free=false (13:00–13:30 «Продление полномочий…»). askQuestion «Амураль И.Б. занят 01.10 13:00 (Продление полномочий…). На какое время поставить «Анализ форм 03-19»?» options ["01.10 16:30–17:30","02.10 17:00–18:00","Не планировать"] → человек выбрал 01.10 16:30–17:30.
4. Показал план таблицей: 2 совещания, у второго время перенесено из-за занятости шефа.
5. outlook.ews_create_meeting(subject="РГ по обращению 194383 …", start="2026-10-05T11:00", end="2026-10-05T11:30", location="руководитель Улановский Константин Владимирович, малый конференц-зал задание 6/8", attendees=[Улановский…, Гайфулин…, Донченко…, "Амураль Игорь Борисович"], memo_number="000016146", memo_date="30.09.2026", …) → подтверждено, created=true. Второе — так же на 01.10 16:30.
6. ## WORK_RESULT: таблица двух созданных совещаний; не запланированных нет; все приглашения отправлены.
"""

STEPS = [
    {"id": "s1", "title": "Служебные записки", "action": "meetings.memo_requests: по номерам из задачи или список актуальных + askQuestion, какие планировать. planned — второй раз не ставить."},
    {"id": "s2", "title": "Желаемое время", "action": "desired_date + start_time, duration_minutes (нет — 60). Прошедшая дата — ближайший рабочий день, сказать человеку."},
    {"id": "s3", "title": "Занятость шефа и места", "action": "outlook.ews_availability на записку: шеф свободен и место свободно — желаемое время; занят — askQuestion с вариантами из suggestions; unresolved — предупредить."},
    {"id": "s4", "title": "План", "action": "Таблица плана: №, тема, когда, место, участники, что проверено."},
    {"id": "s5", "title": "Совещание в календаре «Совещания»", "action": "outlook.ews_create_meeting — один вызов на записку: участники записки + руководитель + Амураль И.Б., location «руководитель …, место», memo_number/memo_date. boss_busy — назад к s3."},
    {"id": "s6", "title": "Итог", "action": "## WORK_RESULT: созданные совещания, не запланированные и почему, кому приглашение не ушло."},
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
    user = db.query(AppUser).filter(AppUser.fio == query).first()
    if user is not None:
        return user
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
    """Library copies adopted from the source row get the same playbook and tool whitelist."""
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
        user = _find_user(db, user_query or DEFAULT_OWNER)
        if user is None:
            raise SystemExit(f"User not found: {user_query or DEFAULT_OWNER}")
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

        _apply_playbook(row)
        db.flush()

        copies = _adopted_copies(db, row.id)
        for copy_row in copies:
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
    parser = argparse.ArgumentParser(description="Seed meeting planner agent (published)")
    parser.add_argument(
        "--user",
        default="",
        help=f"Owner: user id or FIO (default: {DEFAULT_OWNER})",
    )
    args = parser.parse_args()
    seed(user_query=args.user)


if __name__ == "__main__":
    main()

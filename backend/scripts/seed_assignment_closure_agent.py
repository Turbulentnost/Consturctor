"""Seed published agent «Проверка поручений к закрытию» (Cursor SDK playbook).

Creates (or updates, idempotent by owner + title + phase=done) a workflow that:
  - reads open АСТ00 assignments with lines and files from 1C ERP (onec.erp_assignments),
  - downloads and reads the artifacts from the «Файлы» tab (onec.download_artifact,
    office.read_file, excel.read_workbook), one file at a time and with a page limit,
  - grades each assignment: ready to close / partially / no grounds, with a short reason,
  - saves the result as Проверка_артефактов_АСТ00_<date>.docx via report.export_document.

Read-only for 1C: the agent never changes assignment status.

Published to the Agent Library: phase=done, local_run.published=True,
status=published, purpose=functional.

Usage (from backend/):
  py -3.12 scripts/seed_assignment_closure_agent.py --user "Жалыбин Максим Дмитриевич"
  py -3.12 scripts/seed_assignment_closure_agent.py --user <user-id>
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
from app.services.app_users import is_admin_user
from app.services.triggers.service import workflow_is_deleted

TITLE = "Проверка поручений к закрытию"

GOAL = (
    "Проверить незакрытые поручения АСТ00 в 1С ERP: по файлам во вкладке «Файлы» "
    "оценить, есть ли основания для закрытия, и выдать отчёт Word "
    "«Проверка артефактов по незакрытым поручениям АСТ00»."
)

TOOLS = [
    "onec.erp_assignments",
    "onec.download_artifact",
    "office.read_file",
    "excel.read_workbook",
    "report.export_document",
    "users.current",
]

INSTRUCTIONS = """Ты — агент «Проверка поручений к закрытию». Проверь незакрытые поручения журнала АСТ00 в 1С ERP и выдай отчёт Word. В 1С ничего не меняй: статусы поручений не трогай, только читай.

1. Период и список. Если в задании указан период (даты с/по), бери поручения этого периода; иначе — все открытые. Вызови onec.erp_assignments action="list" с only_open=true, include_files=true, include_last_day=false, limit=100 (и date_from / date_to, если период передан). В ответе у каждого поручения есть number, date, status, topic, basis, reporter, due, overdue, lines (пункт, исполнитель, срок, просрочка) и files (name, extension, size, created, ref_key). Повторно список не запрашивай. Если 1С не ответила — один повтор; снова ошибка — напиши человеку «1С недоступна» и остановись, отчёт не создавай.
2. Отбор файлов. По каждому поручению разбери files до чтения:
   — дубли (одинаковые name и size) читай один раз;
   — «Лист Microsoft Excel» и сканы, созданные в день регистрации поручения (created в дату поручения), обычно бланк самого поручения — прочитай один такой файл на всё поручение, чтобы подтвердить, остальные не открывай;
   — .epf, .zip и прочие нечитаемые — не скачивай, только упомяни в отчёте;
   — поручение без файлов — сразу «Нет оснований», файлы не ищи.
3. Чтение артефактов. Для отобранного файла: onec.download_artifact(file_id=ref_key файла) → saved_path; затем по расширению: docx/pdf/jpg/png — office.read_file(filename=saved_path, max_pages=2, max_chars=8000); xlsx — excel.read_workbook(filename=saved_path). Читай по одному файлу за раз, не больше 3 файлов на поручение и не больше 25 файлов за запуск; сканы — не больше 2 страниц на файл. Встроенные Read / Grep / Glob для этих файлов не используй. Из каждого файла запиши 1–2 строки: что это за документ и что он подтверждает (дата, подпись, утверждение, номер).
4. Оценка. Сопоставь пункты поручения (lines) с тем, что подтверждают файлы, и дай одну оценку:
   — «Готово к закрытию» — все пункты подтверждены документами с результатом (утверждено, подписано, принято);
   — «Готово к закрытию (условно)» — результат приложен, но нет формального утверждения / отметки «Принято»;
   — «Сомнительное — частично» — подтверждена часть пунктов, либо документ фиксирует проблему (расхождение, отказ);
   — «Нет оснований» — во вкладке «Файлы» только бланк поручения, копии основания или ничего.
   Обоснование — 1–3 предложения: какие пункты закрыты каким документом, чего не хватает. Ничего не домысливай: только то, что есть в файлах и карточке 1С.
5. Отчёт Word. Вызови report.export_document один раз: filename="Проверка_артефактов_АСТ00_<сегодня YYYY-MM-DD>", format="docx", title="Проверка артефактов по незакрытым поручениям АСТ00". Структура:
   — kpis: [{label:"Всего открытых", value}, {label:"Готово к закрытию", value}, {label:"Частично", value}, {label:"Нет оснований", value}, {label:"Просрочено", value}, {label:"Без файлов", value}] — посчитай по своим оценкам и полю overdue;
   — summary: «Дата: <сегодня>. Источник: 1С ERP, Document_ТД_Поручения (серия АСТ00, статусы «Создано» и «В работе», N поручений) и вкладка «Файлы» каждого поручения. Период: <период или «все открытые»>.»;
   — sections[0] heading «Оценка по поручениям», body — markdown-таблица с колонками | Номер | Тема | Срок | Просрочка | Исполнители | Файлов | Что во вкладке «Файлы» | Оценка | Обоснование |, по строке на поручение; порядок: «Готово к закрытию», «Готово к закрытию (условно)», «Сомнительное — частично», «Нет оснований», внутри — по номеру по убыванию. Срок — ДД.ММ.ГГГГ или «не задан»; Просрочка — «да» / «нет» / «нет (п.1–2 просрочены)»; Исполнители — докладчик / исполнители пунктов, фамилия И.О.;
   — sections[1] heading «Приложение. Пункты поручений и файлы по данным 1С», body — по каждому поручению в том же порядке: строка «### <номер> от <ДД.ММ.ГГГГ> — <тема>», строка «**Статус:** <статус>; срок <срок>; докладчик <ФИО>; **оценка:** <оценка>», строка «Основание: <basis>» (если это не GUID), markdown-таблица | № | Пункт | Исполнитель | Срок | по lines (просроченный срок — «ДД.ММ.ГГГГ (просрочен)», пустой исполнитель — «не назначен»), затем строка «**Файлы:** имя.расширение (ДД.ММ.ГГГГ); …» или «**Файлы:** нет».
   Текст пиши полностью, без сокращений и без «…». Файл пиши только этим инструментом.
6. Итог человеку: покажи короткую сводку (сколько в каждой оценке, какие номера готовы к закрытию) и имя файла из ответа report.export_document. В блоке FILES итогового WORK_RESULT укажи только этот файл.
"""

EXAMPLE_RUN = """Задача: «Проверь незакрытые поручения АСТ00 за период 2026-03-25 — 2026-09-25».
1. onec.erp_assignments(action="list", only_open=true, include_files=true, include_last_day=false, limit=100, date_from="2026-03-25", date_to="2026-09-25") → 15 открытых поручений с пунктами и файлами.
2. Отбор: АСТ00-00097 — 14 файлов, из них 6 дублей и бланк; читаю письмо в ЖКХ и один скан. АСТ00-00094 — файлов нет → «Нет оснований». АСТ00-00039 — ТД_БДРНовая.epf не скачиваю.
3. АСТ00-00093: onec.download_artifact(file_id="106692b3-…") → Лист записи ЕГРЮЛ_ОКВЭД.pdf; office.read_file(filename=saved_path, max_pages=2) → «лист ЕГРЮЛ 15.09.2026, основной ОКВЭД 30.30 у ООО «ИТЦ»». Всего прочитано 19 файлов.
4. АСТ00-00093 — «Сомнительное — частично»: п.1–2 подтверждены распиской ИФНС и листом ЕГРЮЛ, п.3–6 без артефактов. АСТ00-00092 — «Готово к закрытию (условно)»: финальная редакция СТО-231 от 21.09, извещения и отметки «Принято» нет.
5. report.export_document(filename="Проверка_артефактов_АСТ00_2026-09-25", format="docx", title="Проверка артефактов по незакрытым поручениям АСТ00", kpis=[Всего 15, Готово 1, Частично 3, Нет оснований 11, Просрочено 7, Без файлов 4], summary=…, sections=[Оценка по поручениям (md-таблица 15 строк), Приложение (по поручению: ###, статус, пункты, файлы)]) → Проверка_артефактов_АСТ00_2026-09-25.docx.
6. Сводка человеку: готово к закрытию условно — АСТ00-00092; частично — 00093, 00096, 00033; остальные 11 без оснований. FILES: Проверка_артефактов_АСТ00_2026-09-25.docx.
"""

STEPS = [
    {"id": "s1", "title": "Открытые поручения АСТ00", "tool": "onec.erp_assignments", "action": "action=list, only_open=true, include_files=true, include_last_day=false, limit=100 (+ date_from/date_to периода). Один запрос; 1С недоступна — остановиться."},
    {"id": "s2", "title": "Отбор файлов", "action": "Дубли читать один раз; бланк поручения — один на поручение; .epf/.zip не скачивать; без файлов — сразу «Нет оснований»."},
    {"id": "s3", "title": "Чтение артефактов", "tool": "onec.download_artifact", "tool_candidates": ["office.read_file", "excel.read_workbook"], "action": "По одному файлу: download → office.read_file (max_pages=2, max_chars=8000) или excel.read_workbook. ≤3 файлов на поручение, ≤25 за запуск."},
    {"id": "s4", "title": "Оценка к закрытию", "action": "Готово / Готово (условно) / Сомнительное — частично / Нет оснований + обоснование 1–3 предложения по пунктам и документам."},
    {"id": "s5", "title": "Отчёт Проверка_артефактов_АСТ00_<дата>.docx", "tool": "report.export_document", "action": "kpis (итоги), summary (источник и период), раздел «Оценка по поручениям» (md-таблица 9 колонок), «Приложение» (пункты и файлы из 1С по каждому поручению)."},
    {"id": "s6", "title": "Итог человеку", "action": "Сводка по оценкам и имя docx; FILES — только созданный файл."},
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


def _first_admin(db) -> AppUser | None:
    for user in db.query(AppUser).order_by(AppUser.created_at.asc()).all():
        if is_admin_user(user.fio or ""):
            return user
    return None


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
    """Write the current playbook/tools into a workflow row (owner or adopted copy)."""
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
    """Library copies other users adopted from the source row (local_run.library_source_id)."""
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
            user = _first_admin(db)
            if user is None:
                raise SystemExit("No admin user found; pass --user explicitly")
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
    parser = argparse.ArgumentParser(description="Seed assignment closure check agent (published)")
    parser.add_argument(
        "--user",
        default="",
        help="Owner: user id or FIO (default: first admin from ADMIN_FIO_KEYS)",
    )
    args = parser.parse_args()
    seed(user_query=args.user)


if __name__ == "__main__":
    main()

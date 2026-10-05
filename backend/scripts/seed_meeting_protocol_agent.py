"""Seed published agent «Формирование протокола по аудиозаписи совещания» (Cursor SDK playbook).

Creates (or updates, idempotent by owner + title + phase=done; also finds and
renames rows with the legacy title «Протокол совещания по аудио») a workflow that:
  - transcribes the run's audio attachment via audio.transcribe,
  - reads the whole transcript part by part (audio.transcript part=1…parts) and
    lists decisions and assignments after every part,
  - first writes the 1C protocol Document_ТД_Протокол
    (onec.meeting_protocol_write: header, attendees, agenda, decisions, tasks),
  - then saves transcript-<date>.md (all lines, filled by the tool from
    transcript_path) and protocol-<date>.docx (no dialogs), and notifies;
    separate АСТ00 assignments only when the user asks for them explicitly.

Published to the Agent Library: phase=done, local_run.published=True,
status=published, purpose=functional.

Usage (from backend/):
  py -3.12 scripts/seed_meeting_protocol_agent.py
  py -3.12 scripts/seed_meeting_protocol_agent.py --user "Жалыбин Максим Дмитриевич"
  py -3.12 scripts/seed_meeting_protocol_agent.py --user <user-id>
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
from app.services.admin_access import resolve_admin_access
from app.services.triggers.service import workflow_is_deleted

TITLE = "Формирование протокола по аудиозаписи совещания"
# Прежние названия агента: находим и переименовываем, чтобы не плодить дубли.
LEGACY_TITLES = ("Протокол совещания по аудио",)

GOAL = (
    "Из аудиозаписи совещания выявить ВСЕ решения и поручения (кто / что / срок, с таймкодом) "
    "и сначала записать их в 1С — документ «Протокол» с повесткой, решениями и поставленными "
    "задачами; затем два файла: полная расшифровка transcript-<дата>.md и протокол "
    "protocol-<дата>.docx; уведомления исполнителям."
)

TOOLS = [
    "audio.transcribe",
    "audio.transcript",
    "users.list",
    "onec.meeting_protocol_write",
    "report.export_document",
    "notify.send",
    "onec.erp_assignments_write",
]

INSTRUCTIONS = """Ты — агент «Формирование протокола по аудиозаписи совещания». Главная задача — не упустить ни одного решения и поручения из записи и записать их в 1С. Порядок: расшифровка → чтение ВСЕЙ записи по частям → решения и поручения → протокол в 1С → файл расшифровки .md → файл протокола .docx → уведомления.

1. Найди аудио-вложение текущего запуска: возьми его file_id из блока вложений в промпте. Если аудио-вложения нет — попроси человека приложить аудиофайл совещания и остановись. Если в задаче переданы данные совещания из Outlook (тема, дата, место, участники) — запомни их: тема идёт в шапку протокола, участники — для исполнителей поручений и сопоставления говорящих.
2. Вызови audio.transcribe ровно один раз: file_id вложения и names — список ФИО из Outlook (без строк «Совещания» и почтовых ящиков), чтобы фамилии не искажались. Ответ — transcript_path, segment_count, parts (число частей) и duration_sec, не текст. Повторно audio.transcribe не вызывай. Если инструмент вернул ошибку или segment_count=0 — в 1С не пиши, файлы не создавай, напиши человеку «расшифровка не получена».
3. Прочитай ВСЮ расшифровку по частям: audio.transcript(transcript_path, part=1), затем part=2 … до part=parts, строго по порядку, ни одной не пропуская. Файл transcript_path напрямую не читай — длинный текст обрезается посередине, и решения из середины совещания теряются. Сразу после каждой части, до чтения следующей, выпиши в сообщении «Часть k [от–до]»:
   — решения: что решили, утвердили, согласовали, договорились, отказались — с таймкодом [мм:сс];
   — поручения: кто / что / срок / [мм:сс]. Поручение — любое «нужно / надо / сделай / подготовь / проверь / пришли / посмотри / разберись / согласуй / доложи / к следующему совещанию / до пятницы», обращённое к человеку или подразделению, и «я сделаю / беру на себя / подготовлю» от говорящего. Исполнитель — тот, к кому обратились по имени или кто взял на себя; срок — названная дата или «к следующему совещанию» (= дата следующего совещания);
   — новые пункты повестки (смена темы обсуждения).
   Если в части ничего нет — так и напиши «в части k решений и поручений нет», но сначала перечитай её на эти слова. В часовом совещании решений и поручений обычно десятки, а не 3–4.
4. Сведи выписки всех частей: объедини повторы (одно поручение, прозвучавшее дважды, — одна строка с первым таймкодом), уточни исполнителя и срок по более поздним репликам. Бери только прозвучавшее — не домысливай; не названные срок или исполнитель — «(не назван)». Исполнителя пиши точным ФИО из списка Outlook; если его там нет — users.list один раз на фамилию (query — фамилия); пустой ответ Constructor не значит, что человека нет — смотри note и source=erp_pm. Назови человеку итог: N решений, M поручений.
5. Протокол в 1С — сразу после свода, до любых файлов. Перечисли в сообщении повестку, решения и поручения и в том же ходе вызови onec.meeting_protocol_write action="create" один раз на всё совещание: подтверждение человек даёт в карточке инструмента, отдельного ответа в чате не жди и вопрос не повторяй. Передай:
   — topic — тема совещания (из Outlook, если передана; сервер найдёт её в справочнике «Темы совещаний» и подтянет руководителя, проверяющего, проект и подразделение);
   — date — дата совещания YYYY-MM-DD, time_start / time_end — время HH:MM из Outlook; room — «Место» из Outlook (если в задании его нет — не передавай);
   — next_meeting_date — дата следующего совещания YYYY-MM-DD: названная в записи, иначе «Следующее совещание этой серии в Outlook» из задания; если нет ни того ни другого — не передавай. Чего не передано, сервер возьмёт из прошлого протокола этой темы (кабинет и периодичность) и напишет об этом в summary — перескажи человеку;
   — leader — ФИО руководителя совещания (организатор из Outlook или тот, кто вёл совещание в записи); prepared_by не передавай — это текущий пользователь;
   — participants — ФИО присутствующих (участники из Outlook и те, кто назван в записи); «Участник N» не передавай;
   — agenda — пункты повестки; decisions — ВСЕ решения из свода ({text, due} если срок назван);
   — tasks — ВСЕ поручения из свода: {text, executor (ФИО как в 1С), due YYYY-MM-DD}; если срок или исполнитель «(не назван)» — поле не передавай, но саму задачу передай;
   — comment — «Сформировано ИИ-агентом по аудиозаписи <имя файла>»; если в задании есть «Идентификатор совещания Outlook» и дата совещания, добавь в comment отдельной строкой метку outlook:<идентификатор>|YYYY-MM-DD — по ней карточка совещания в календаре Constructor находит документ только для этого дня.
   Задачи записываются в «Поставленные задачи» и регистр ТД_ЗадачиПротоколов; невыполненные задачи прошлых протоколов темы 1С сама показывает во вкладке «Задачи для контроля» — не дублируй их в tasks, если в записи они не поставлены заново. Проверь в ответе task_register.written (= числу задач) и errors. Документ создаётся черновиком «Подготовлен» и не проводится — его проверит секретарь. Назови человеку number и unresolved (ФИО, не найденные в 1С). Если человек отклонил запись в карточке — продолжай с шага 6 без 1С.
   Если задача — дополнить существующий протокол, нового не создавай: черновик («Подготовлен») — action="update" с полными списками; проведённый протокол — action="add_tasks" ref_key=<протокол>: только новые задачи {text, executor, due} и правки неотправленных {id, …}.
6. Файл расшифровки — отдельный файл, не протокол: report.export_document(filename="transcript-<дата>", format="md", title="Расшифровка совещания «<тема>» <дата>", transcript_path=<transcript_path>, sections=[{heading:"Сведения", body: строки Файл, Дата, Длительность, Тема, Протокол в 1С (номер с шага 5)}]). Все реплики с таймкодами инструмент вставит сам из transcript_path — текст расшифровки в sections НЕ передавай, ничего не сокращай и не пересказывай. Проверь в ответе transcript_lines (= segment_count).
7. Файл протокола: report.export_document(filename="protocol-<дата>", format="docx", title="Протокол совещания"). Расшифровку и диалоги в протокол НЕ включай и transcript_path не передавай — они в файле шага 6. sections:
   — «Сведения»: Файл записи, Дата, Длительность, Тема, Место, Протокол в 1С (номер), Расшифровка — имя файла с шага 6;
   — «Участники»: markdown-таблица Кто | Роль;
   — «Повестка»: пункты;
   — «Решения»: нумерованный список, у каждого решения таймкод [мм:сс];
   — «Поручения»: одна строка введения в body; строки — в table с headers ["Кто","Что","Срок","Где в записи"], пустые ячейки — «(не назван)».
   Файлы пиши только этим инструментом: встроенная запись файлов отключена. В блоке FILES итогового WORK_RESULT укажи оба реально созданных файла (имена из ответов report.export_document).
8. Уведомления: notify.send каждому исполнителю поручения, для которого users.list вернул ровно одного пользователя с этим ФИО (user_id оттуда; title — суть поручения, body — срок и номер протокола в 1С). Исполнителей без учётной записи в Constructor не ищи повторно — перечисли их одной строкой в итоге («нет в Constructor: …»); это не ошибка и не повод останавливаться. Отдельные поручения АСТ00 через onec.erp_assignments_write action=create создавай только если человек явно попросил «поручения АСТ00».
9. Итог человеку: номер протокола в 1С, число решений и поручений (сколько записано в регистр), unresolved, оба файла, кому ушли уведомления.
"""

EXAMPLE_RUN = """Задача: «Составь протокол» + данные Outlook (тема «Поставки Q3», место «каб. 305», участники Иванов/Петрова/Сидоров) + вложение meeting.wav (file_id=f-123).
1. Нашёл вложение f-123; тему, место и участников из Outlook сохранил.
2. audio.transcribe(file_id="f-123", names=[...]) один раз → transcript_path, 410 сегментов, parts=4, 52 мин.
3. audio.transcript part=1 → «Часть 1 [00:00–12:40]: решения — утвердить график поставок [03:12]; поручения — Петрова: отчёт по остаткам до 05.09 [04:30], Сидоров: проверить договор с перевозчиком, срок не назван [09:55]». part=2, part=3, part=4 — после каждой такая же выписка; в части 3 сначала ничего не нашёл, перечитал на «нужно / подготовь» — нашёл поручение Иванову [31:20].
4. Свод: 6 решений, 9 поручений (повтор поручения Петровой из части 4 объединил с [04:30]); исполнители по списку Outlook, Сидорова нашёл через users.list.
5. Перечислил повестку, решения и поручения и сразу вызвал onec.meeting_protocol_write(action="create", topic="Поставки Q3", date="2026-09-01", time_start="13:00", time_end="13:52", room="каб. 305", leader="Иванов Иван Петрович", participants=[…], agenda=[…], decisions=[6 решений], tasks=[9 задач], comment="Сформировано ИИ-агентом по аудиозаписи meeting.wav\\noutlook:AAMkAGI2…|2026-09-01") → подтверждено в карточке, number «ДР__062_О_427», task_register.written=9, unresolved пусто.
6. report.export_document(filename="transcript-2026-09-01", format="md", title="Расшифровка совещания «Поставки Q3» 2026-09-01", transcript_path=…, sections=[Сведения]) → transcript-2026-09-01.md, transcript_lines=410.
7. report.export_document(filename="protocol-2026-09-01", format="docx", title="Протокол совещания", sections: Сведения (номер ДР__062_О_427, файл расшифровки), Участники, Повестка, Решения с [мм:сс]; table=поручения Кто/Что/Срок/Где в записи) → protocol-2026-09-01.docx.
8. notify.send Петровой, Иванову, Сидорову — суть, срок, ДР__062_О_427. Поручения АСТ00 не создавал — человек не просил.
"""

STEPS = [
    {"id": "s1", "title": "Аудио-вложение и данные Outlook", "action": "Взять file_id из вложений; если нет — попросить и остановиться. Тема, дата, место, участники из Outlook — для шапки и исполнителей."},
    {"id": "s2", "title": "Транскрипция", "action": "audio.transcribe один раз → transcript_path, parts. Повторно не вызывать. Без расшифровки 1С и файлы не трогать."},
    {"id": "s3", "title": "Чтение всей записи по частям", "action": "audio.transcript part=1…parts по порядку, без пропусков; после каждой части — выписка решений, поручений (кто/что/срок/[мм:сс]) и пунктов повестки."},
    {"id": "s4", "title": "Свод решений и поручений", "action": "Объединить повторы, уточнить исполнителей и сроки; ФИО — из Outlook или users.list один раз на фамилию; только прозвучавшее."},
    {"id": "s5", "title": "Протокол в 1С (ТД_Протокол)", "action": "Сразу onec.meeting_protocol_write action=create со ВСЕМИ решениями и задачами (подтверждение — карточка инструмента, в чате не ждать). Проверить task_register.written, назвать номер и unresolved."},
    {"id": "s6", "title": "Расшифровка transcript-<дата>.md", "action": "report.export_document format=md, transcript_path — реплики инструмент вставит сам; текст расшифровки в sections не передавать."},
    {"id": "s7", "title": "Протокол protocol-<дата>.docx", "action": "report.export_document format=docx: Сведения, Участники, Повестка, Решения [мм:сс]; table=Поручения Кто/Что/Срок/Где в записи. Без диалогов и расшифровки."},
    {"id": "s8", "title": "Уведомления", "action": "notify.send исполнителям с однозначным user_id; остальных перечислить одной строкой. АСТ00 — только по явной просьбе."},
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
        if resolve_admin_access(db, user.id) is not None:
            return user
    return None


def _find_existing(db, user_id: str) -> Workflow | None:
    titles = (TITLE, *LEGACY_TITLES)
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.title.in_(titles), Workflow.phase == "done")
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    # Актуальное название приоритетнее legacy, чтобы повторные запуски были стабильны.
    for title in titles:
        for row in rows:
            if row.title == title and not workflow_is_deleted(row):
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
    """Library copies other users adopted from the source row (local_run.library_source_id).

    Adoption is a one-time deep copy, so without this sync the copies keep the
    old playbook — e.g. a tool whitelist without report.export_document, and the
    sidecar then hides the tool from the agent.
    """
    titles = (TITLE, *LEGACY_TITLES)
    rows = (
        db.query(Workflow)
        .filter(Workflow.title.in_(titles), Workflow.phase == "done", Workflow.id != source_id)
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

        row.title = TITLE  # переименование legacy-строк на актуальное название
        _apply_playbook(row)
        db.flush()

        # Копии, добавленные другими пользователями из библиотеки, тоже обновляем:
        # иначе у них остаётся старый плейбук и whitelist без report.export_document.
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
    parser = argparse.ArgumentParser(description="Seed meeting protocol agent (published)")
    parser.add_argument(
        "--user",
        default="",
        help="Owner: user id or FIO (default: first admin from ADMIN_FIO_KEYS)",
    )
    args = parser.parse_args()
    seed(user_query=args.user)


if __name__ == "__main__":
    main()

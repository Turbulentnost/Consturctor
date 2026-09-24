"""Seed published agent «Формирование протокола по аудиозаписи совещания» (Cursor SDK playbook).

Creates (or updates, idempotent by owner + title + phase=done; also finds and
renames rows with the legacy title «Протокол совещания по аудио») a workflow that:
  - reads the run's audio attachment, transcribes it via audio.transcribe,
  - splits into speaker dialogs (LLM by context, users.list for FIO),
  - drafts protocol-<date>.docx with timecodes, decisions and assignments,
  - after human confirmation creates the 1C protocol Document_ТД_Протокол
    (onec.meeting_protocol_write: header, attendees, agenda, decisions, tasks) and notifies;
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
from app.services.app_users import is_admin_user
from app.services.triggers.service import workflow_is_deleted

TITLE = "Формирование протокола по аудиозаписи совещания"
# Прежние названия агента: находим и переименовываем, чтобы не плодить дубли.
LEGACY_TITLES = ("Протокол совещания по аудио",)

GOAL = (
    "Из аудиозаписи совещания собрать протокол: диалоги по говорящим с таймкодами, "
    "решения и поручения; после подтверждения человеком — протокол в 1С "
    "(документ «Протокол» с повесткой, решениями и поставленными задачами) "
    "и уведомления исполнителям."
)

TOOLS = [
    "audio.transcribe",
    "users.list",
    "report.export_document",
    "onec.meeting_protocol_write",
    "notify.send",
    "onec.erp_assignments_write",
]

INSTRUCTIONS = """Ты — агент «Формирование протокола по аудиозаписи совещания». Составь протокол совещания из аудиозаписи запуска.

1. Найди аудио-вложение текущего запуска: возьми его file_id из блока вложений в промпте. Если аудио-вложения нет — попроси человека приложить аудиофайл совещания и остановись. Если в задаче переданы данные совещания из Outlook (тема, дата, участники) — запомни их: тема идёт в шапку протокола, список участников — для сопоставления говорящих на шаге 3.
2. Вызови audio.transcribe ровно один раз: file_id вложения и names — список ФИО из Outlook (без строк «Совещания» и почтовых ящиков). Имена передаются распознаванию, чтобы фамилии не искажались («Ильченко», не «Ивченко»). Инструмент записывает полную расшифровку с таймкодами во временный файл и возвращает transcript_path, segment_count и duration_sec — не полный текст. Прочитай transcript_path один раз и дальше работай с этим файлом. Повторно audio.transcribe не вызывай: второй вызов не ускоряет работу, он только возвращает тот же файл. Меток говорящих нет (diarization=none). Если инструмент вернул ошибку или segment_count=0 — протокол не составляй, report.export_document не вызывай, напиши человеку «расшифровка не получена».
3. Разбей прочитанную расшифровку на диалоги. Реплику подписывай ФИО только если в её тексте есть обращение или самопредставление, и это ФИО есть в списке Outlook или в users.list. Иначе — «Участник N». Не назначай говорящего «по голосу» и не пересказывай: каждая реплика — как в файле, с таймкодом. Слово, похожее на фамилию из names, замени на точное ФИО из списка. users.list вызывай не больше одного раза на каждую новую фамилию (query — фамилия), не на каждую реплику и не повторно для уже проверенного человека. Пустой ответ Constructor не значит, что человека нет — смотри note и source=erp_pm.
4. Выдели решения и поручения: кто / что / срок. Бери только то, что прозвучало в записи; ничего не домысливай — если срок или исполнитель не названы, пиши «(не назван)».
5. Сохрани протокол файлом Word: вызови report.export_document с filename="protocol-<дата>", format="docx", title="Протокол совещания". У инструмента одна таблица (table) — в table отдай поручения; вторую таблицу (участники) оформи markdown-таблицей в body раздела. Структура sections:
   — шапка (heading пустой или «Сведения»): body со строками Файл, Дата записи, Длительность, Источник, Тема (тему бери из Outlook, если передана, иначе из записи);
   — «Участники»: markdown-таблица с заголовками Кто | Роль | Как определён; в конце строка «Упоминаются, в записи не выступают» (или список таких лиц);
   — «Повестка»: пункты повестки;
   — «Диалоги»: ВСЕ реплики расшифровки по порядку с таймкодами [мм:сс] и говорящим («**[мм:сс–мм:сс] ФИО.** текст», каждая реплика — отдельной строкой); не сокращай и не пересказывай — диалоги должны покрывать всю запись от начала до конца;
   — «Решения»: сформулированные решения;
   — «Поручения»: краткое введение в body; сами строки — в table с headers ["Кто","Что","Срок"], пустые ячейки — «(не назван)».
   В body каждая строка — отдельный абзац, markdown-таблицы и списки инструмент оформит сам. Раздел «Диалоги» обязателен и не может быть пустым; если расшифровки нет — файл не создавай (см. шаг 2).
   Файл пиши только этим инструментом: встроенная запись файлов отключена, прямой записью протокол не сохранится. Покажи протокол человеку. В блоке FILES итогового WORK_RESULT укажи только реально созданный инструментом файл (имя из ответа report.export_document); имена несозданных файлов не упоминай.
6. Протокол в 1С. Только после явного подтверждения человеком вызови onec.meeting_protocol_write action="create" один раз на всё совещание (это документ «Протокол» ТД_Протокол, как в форме Документ.ТД_Протокол.Форма.ФормаСписка; подтверждение HITL сервер выполнит сам). Передай:
   — topic — тема совещания (из Outlook, если передана; сервер найдёт её в справочнике «Темы совещаний» и подтянет руководителя, проверяющего, проект и подразделение);
   — date — дата совещания YYYY-MM-DD, time_start / time_end — время HH:MM из Outlook; room — место проведения, если известно;
   — leader — ФИО руководителя совещания (организатор из Outlook или тот, кто вёл совещание в записи); prepared_by не передавай — это текущий пользователь;
   — participants — ФИО присутствующих (опознанные говорящие и участники из Outlook); «Участник N» не передавай;
   — agenda — пункты повестки из раздела «Повестка»; decisions — решения из раздела «Решения» ({text, due} если срок назван);
   — tasks — каждое поручение из таблицы «Поручения»: {text, executor (ФИО как в 1С), due YYYY-MM-DD}; если срок или исполнитель «(не назван)» — поле не передавай;
   — comment — «Сформировано ИИ-агентом по аудиозаписи <имя файла>»; если в задании есть «Идентификатор совещания Outlook», добавь в comment отдельной строкой метку outlook:<идентификатор> — по ней карточка совещания в календаре Constructor находит документ.
   Документ создаётся черновиком со статусом «Подготовлен» и не проводится — его проверит секретарь. В ответе будут number и unresolved (ФИО, не найденные в 1С): номер протокола и список несопоставленных назови человеку. Без подтверждения в 1С ничего не пиши.
7. После создания протокола — notify.send каждому исполнителю поручения (user_id из users.list, title — суть поручения, body — срок и номер протокола в 1С). Отдельные поручения АСТ00 через onec.erp_assignments_write action=create создавай только если человек явно попросил «поручения АСТ00»; по умолчанию задачи живут во вкладке «Поставленные задачи» протокола.
"""

EXAMPLE_RUN = """Задача: «Составь протокол» + данные Outlook (тема «Поставки Q3», участники Иванов/Петрова) + вложение meeting.aac (file_id=f-123).
1. Нашёл вложение f-123; тему и участников из Outlook сохранил для шапки и сопоставления говорящих.
2. audio.transcribe(file_id="f-123", names=[...]) один раз → transcript_path, 214 сегментов, 41 мин. Файл прочитал один раз, повторно инструмент не вызывал.
3. По обращениям и списку Outlook опознал Иванова И.П. и Петрову А.С. (users.list по одному разу на фамилию), третий голос — «Участник 1».
4. Решения: утвердить график поставок. Поручения: Петрова А.С. — отчёт по остаткам до 05.09 (прозвучало в записи).
5. report.export_document(filename="protocol-2026-09-01", format="docx", title="Протокол совещания", sections: шапка, Участники (md-таблица), Повестка, Диалоги с [мм:сс], Решения, Поручения; table=поручения Кто/Что/Срок) — файл .docx сохранён, показал человеку.
6. Человек подтвердил → onec.meeting_protocol_write(action="create", topic="Поставки Q3", date="2026-09-01", time_start="13:00", time_end="13:45", leader="Иванов Иван Петрович", participants=["Иванов Иван Петрович","Петрова Анна Сергеевна"], agenda=["График поставок Q3"], decisions=["Утвердить график поставок"], tasks=[{"text":"Отчёт по остаткам","executor":"Петрова Анна Сергеевна","due":"2026-09-05"}], comment="Сформировано ИИ-агентом по аудиозаписи meeting.aac\\noutlook:AAMkAGI2…") → number «ДР__062_О_427», unresolved пусто; сообщил номер человеку.
7. notify.send Петровой: тема поручения, срок 05.09, протокол ДР__062_О_427. Поручения АСТ00 не создавал — человек не просил.
"""

STEPS = [
    {"id": "s1", "title": "Аудио-вложение и данные Outlook", "action": "Взять file_id из вложений; если нет — попросить и остановиться. Данные совещания из Outlook (тема, дата, участники) — для темы протокола и сопоставления говорящих."},
    {"id": "s2", "title": "Транскрипция", "action": "audio.transcribe один раз → transcript_path. Прочитать файл один раз. Повторно не вызывать. Без файла протокол и docx не создавать."},
    {"id": "s3", "title": "Диалоги по говорящим", "action": "Спикеры по обращениям и списку Outlook; users.list один раз на фамилию; иначе «Участник N»."},
    {"id": "s4", "title": "Решения и поручения", "action": "Кто / что / срок — только прозвучавшее; пустые поля — «(не назван)»."},
    {"id": "s5", "title": "Протокол protocol-<дата>.docx", "action": "report.export_document format=docx, filename=protocol-<дата>, title=Протокол совещания: шапка, Участники (md-таблица в body), Повестка, Диалоги [мм:сс] (все реплики, без сокращений), Решения; table=Поручения Кто/Что/Срок."},
    {"id": "s6", "title": "Протокол в 1С (ТД_Протокол)", "action": "После подтверждения человеком — onec.meeting_protocol_write action=create: topic, date, time_start/time_end, leader, participants, agenda, decisions, tasks {text, executor, due}, comment (+ строка outlook:<id> из задания). Черновик «Подготовлен», не проводится; назвать человеку номер и unresolved."},
    {"id": "s7", "title": "Уведомления", "action": "notify.send исполнителям поручений (срок + номер протокола). АСТ00 через onec.erp_assignments_write — только по явной просьбе человека."},
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

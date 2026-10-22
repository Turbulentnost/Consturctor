"""Серверный агент процессов и задач по утверждённым документам.

Раз в 30 минут берёт файлы базы знаний, созданные или изменённые с прошлого
запуска, и запускает конфигурацию 2. Агент определяет тип документа. Если это
утверждённый регламент, инструкция или другой документ о работе сотрудников,
он находит участников процессов, сверяет их обязанности с уже поставленными
задачами и при пробеле ставит задачу в платформе и публикует новость на «Сегодня».
Что изменилось, агент видит по истории git папки владельца.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.explorer import ExplorerEntry, ExplorerFileKey, ExplorerHistoryRepo
from app.models.explorer_access import ExplorerAccessAgentState
from app.services import explorer, explorer_history
from app.services.server_agents import access_advisor, process_tools, sources

logger = logging.getLogger(__name__)

AGENT_KEY = "process-tasks"
HISTORY_AGENT_ID = "server-process-tasks"
AGENT_TITLE = "Процессы и задачи по документам"
INTERVAL_S = 30 * 60
FIRST_DELAY_S = 300
BATCH = 8
DIFF_LIMIT = 6_000
DOC_TEXT_LIMIT = 120_000
MAX_PAGE_ATTACHMENTS = 12
RUNNING = "running"
RUN_LEASE = timedelta(minutes=45)
_LOCK = threading.Lock()

WORK_ROOT = access_advisor.BACKEND_DIR / "var" / "server-agents" / "process-tasks"
_SENTENCE = re.compile(r"(?<=[^\d\s][.;:!?])\s+|\s+(?=\d{1,2}(?:\.\d{1,2})*\.?\s+[А-ЯЁA-Z])")


@dataclass
class ChangedDoc:
    file_id: str
    name: str
    owner_user_id: str
    owner_fio: str
    owner_folder: str
    text: str
    created: bool
    updated_at: datetime
    previous_text: str = ""
    has_history: bool = False
    folder_log: list[str] = field(default_factory=list)
    pages: list[tuple[int, bytes]] = field(default_factory=list)


def tick_process_agent() -> None:
    if not _LOCK.acquire(blocking=False):
        return
    try:
        _tick()
    except Exception:
        logger.exception("process agent tick failed")
    finally:
        _LOCK.release()


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(text or "") if part and part.strip()]


def text_diff(old: str, new: str, limit: int = DIFF_LIMIT) -> str:
    """Добавленные и убранные фразы. «+» — появилось, «-» — исчезло."""
    rows = [
        line
        for line in difflib.ndiff(sentences(old), sentences(new))
        if line.startswith(("+ ", "- "))
    ]
    text = "\n".join(rows)
    return text if len(text) <= limit else text[:limit] + "\n…"


def _tick() -> None:
    _sweep()
    problem = access_advisor.runner_problem()
    if problem:
        logger.warning("process agent skipped: %s", problem)
        return
    db = SessionLocal()
    try:
        since, docs = _claim(db)
    finally:
        db.close()
    if not docs:
        return
    run_id = str(uuid.uuid4())
    workspace = WORK_ROOT / run_id
    try:
        try:
            result = _execute(run_id, workspace, docs, since)
        finally:
            for folder in process_tools.generated_assets(workspace):
                shutil.rmtree(folder, ignore_errors=True)
    except Exception as exc:
        logger.exception("process agent run failed")
        _remember_failure(docs, exc)
        access_advisor._remember_history(
            run_id=run_id,
            prompt="",
            plan="",
            status="error",
            error=str(exc)[:2000],
            sdk_agent_id="",
            events=[],
            agent_id=HISTORY_AGENT_ID,
            agent_title=AGENT_TITLE,
        )
        return
    actions = process_tools._actions(workspace)
    db = SessionLocal()
    try:
        state = db.get(ExplorerAccessAgentState, AGENT_KEY)
        if state is not None:
            state.watermark = max(doc.updated_at for doc in docs)
            state.fail_count = 0
            state.last_status = "ok"
            state.last_error = ""
            state.last_plan = str(result.get("plan") or "")[:20_000]
            state.last_run_id = run_id
            state.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    access_advisor._remember_history(
        run_id=run_id,
        prompt=str(result.get("prompt") or ""),
        plan=str(result.get("plan") or ""),
        status="finished",
        error="",
        sdk_agent_id=str(result.get("agent_id") or ""),
        events=list(result.get("events") or []),
        agent_id=HISTORY_AGENT_ID,
        agent_title=AGENT_TITLE,
    )
    logger.info(
        "process agent run %s: files=%s tasks=%s control=%s news=%s",
        run_id,
        len(docs),
        sum(1 for item in actions if item.get("kind") == "task"),
        sum(1 for item in actions if item.get("kind") == "control"),
        sum(1 for item in actions if item.get("kind") == "news"),
    )


def _claim(db: Session) -> tuple[datetime, list[ChangedDoc]]:
    now = datetime.now(timezone.utc)
    state = db.get(ExplorerAccessAgentState, AGENT_KEY, with_for_update=True)
    if state is None:
        state = ExplorerAccessAgentState(id=AGENT_KEY, watermark=now - timedelta(minutes=30), updated_at=now)
        db.add(state)
        db.flush()
    since = _utc(state.watermark)
    if state.last_status == RUNNING and _utc(state.updated_at) > now - RUN_LEASE:
        db.rollback()
        return since, []
    rows = db.scalars(
        select(ExplorerEntry)
        .where(ExplorerEntry.kind == "file", ExplorerEntry.updated_at > state.watermark)
        .order_by(ExplorerEntry.updated_at.asc())
        .limit(BATCH)
    ).all()
    if not rows:
        state.watermark = now
        state.updated_at = now
        db.commit()
        return since, []
    ids = [row.id for row in rows]
    keys = {key.file_id: key.key for key in db.scalars(select(ExplorerFileKey).where(ExplorerFileKey.file_id.in_(ids))).all()}
    repos = {
        repo.owner_folder: repo.key
        for repo in db.scalars(
            select(ExplorerHistoryRepo).where(ExplorerHistoryRepo.owner_folder.in_({row.owner_folder for row in rows}))
        ).all()
    }
    docs: list[ChangedDoc] = []
    for row in rows:
        text_value = ""
        pages: list[tuple[int, bytes]] = []
        if row.id in keys:
            try:
                data = explorer._read_encrypted(explorer._abs(row.rel_path), keys[row.id])
                text_value = sources.extract_text(row.name, data, DOC_TEXT_LIMIT)
                if row.name.lower().endswith(".pdf"):
                    pages = sources.pdf_page_images(data)
            except Exception:
                logger.info("process agent cannot read %s", row.id, exc_info=True)
        doc = ChangedDoc(
            file_id=row.id,
            name=row.name,
            owner_user_id=row.owner_user_id,
            owner_fio=row.owner_fio or "",
            owner_folder=row.owner_folder,
            text=text_value,
            created=_utc(row.created_at) > since,
            updated_at=row.updated_at,
            pages=pages,
        )
        _attach_history(doc, row, repos.get(row.owner_folder, ""), since)
        docs.append(doc)
    state.last_status = RUNNING
    state.updated_at = datetime.now(timezone.utc)
    db.commit()
    return since, docs


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _attach_history(doc: ChangedDoc, row: ExplorerEntry, repo_key: str, since: datetime) -> None:
    if not repo_key:
        return
    owner_dir = explorer._abs(row.owner_folder)
    path = explorer._repo_relative(row)
    try:
        found = explorer_history.versions(owner_dir, repo_key, path, limit=10)
        doc.folder_log = explorer_history.recent_log(owner_dir, int(since.timestamp()), limit=15)
    except Exception:
        logger.info("process agent: no git history for %s", row.id, exc_info=True)
        return
    doc.has_history = bool(found)
    cutoff = since.timestamp()
    before = next((version for version in found if version.at <= cutoff), None)
    if before is None and not doc.created and len(found) > 1:
        before = found[-1]
    if before is not None:
        doc.previous_text = sources.extract_text(row.name, before.data, DOC_TEXT_LIMIT)


def _execute(run_id: str, workspace: Path, docs: list[ChangedDoc], since: datetime) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    for folder in ("texts", "diffs", "decisions", "pages"):
        (workspace / folder).mkdir(exist_ok=True)
    manifest = []
    attachments: list[dict[str, Any]] = []
    for doc in docs:
        text_file = diff_file = ""
        page_files = []
        for number, png in doc.pages:
            name = f"{doc.file_id}-p{number}.png"
            (workspace / "pages" / name).write_bytes(png)
            page_files.append(f"pages/{name}")
            if len(attachments) < MAX_PAGE_ATTACHMENTS:
                attachments.append(
                    {"path": str(workspace / "pages" / name), "name": name, "image": True, "mime": "image/png"}
                )
        if doc.text:
            (workspace / "texts" / f"{doc.file_id}.txt").write_text(doc.text, encoding="utf-8")
            text_file = f"texts/{doc.file_id}.txt"
        if doc.previous_text and doc.text:
            diff = text_diff(doc.previous_text, doc.text)
            (workspace / "diffs" / f"{doc.file_id}.txt").write_text(diff or "Текст не изменился.", encoding="utf-8")
            diff_file = f"diffs/{doc.file_id}.txt"
        manifest.append(
            {
                "file_id": doc.file_id,
                "name": doc.name,
                "owner_fio": doc.owner_fio,
                "owner_user_id": doc.owner_user_id,
                "change": "создан" if doc.created else "изменён",
                "readable": bool(doc.text),
                "text_file": text_file,
                "diff_file": diff_file,
                "page_images": page_files,
                "git_history": doc.has_history,
                "folder_changes": doc.folder_log,
            }
        )
    (workspace / "recent.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    launcher = _write_launcher(workspace)
    prompt = _task_prompt(workspace, docs, launcher)
    model, params = access_advisor._model()
    store = str(access_advisor.SDK_STORE)
    access_advisor.SDK_STORE.mkdir(parents=True, exist_ok=True)
    base = {
        "type": "run",
        "sessionId": run_id,
        "attachments": [],
        "title": AGENT_TITLE,
        "model": model,
        "modelParams": params,
        "cwd": str(workspace),
        "python": sys.executable,
        "storeDir": store,
    }
    (workspace / "phase.txt").write_text("plan", encoding="utf-8")
    plan_events = access_advisor._turn(
        base | {"mode": "plan", "prompt": prompt, "resumeAgentId": "", "attachments": attachments}
    )
    plan = access_advisor._plan_text(plan_events) or prompt
    (workspace / "phase.txt").write_text("act", encoding="utf-8")
    try:
        agent_events = access_advisor._turn(
            base
            | {
                "mode": "agent",
                "prompt": _run_prompt(workspace, plan, launcher),
                "resumeAgentId": access_advisor._agent_id(plan_events),
            }
        )
    finally:
        (workspace / "phase.txt").write_text("done", encoding="utf-8")
    return {
        "prompt": prompt,
        "plan": plan,
        "agent_id": access_advisor._agent_id(agent_events) or access_advisor._agent_id(plan_events),
        "events": access_advisor._history_events(prompt, plan_events, agent_events),
    }


def _write_launcher(workspace: Path) -> str:
    python = sys.executable
    backend = access_advisor.BACKEND_DIR
    if sys.platform == "win32":
        path = workspace / "tool.cmd"
        path.write_text(
            "@echo off\r\n"
            f'set "PYTHONPATH={backend}"\r\n'
            f'set "{process_tools.WORKSPACE_ENV}={workspace}"\r\n'
            "set PYTHONIOENCODING=utf-8\r\n"
            f'"{python}" -m app.services.server_agents %*\r\n',
            encoding="utf-8",
        )
        return str(path)
    path = workspace / "tool.sh"
    path.write_text(
        "#!/bin/sh\n"
        f'export PYTHONPATH="{backend}" {process_tools.WORKSPACE_ENV}="{workspace}" PYTHONIOENCODING=utf-8\n'
        f'exec "{python}" -m app.services.server_agents "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def _task_prompt(workspace: Path, docs: list[ChangedDoc], tool: str) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")
    files = "\n".join(
        f"- {doc.file_id} | {doc.name} | {'создан' if doc.created else 'изменён'} | "
        f"текст: {'texts/' + doc.file_id + '.txt' if doc.text else 'не читается, решений нет'}"
        f"{' | что изменилось: diffs/' + doc.file_id + '.txt' if doc.previous_text and doc.text else ''}"
        f"{' | страницы: ' + ', '.join(f'pages/{doc.file_id}-p{n}.png' for n, _ in doc.pages) if doc.pages else ''}"
        for doc in docs
    )
    return f"""Ты серверный агент процессов. Люди тебя не видят и ответить не могут. Ничего не спрашивай.
Сейчас {now}. Файлы базы знаний, созданные или изменённые за последние 30 минут, лежат в `{workspace}`.
recent.json — список; texts/<file_id>.txt — полный текст; diffs/<file_id>.txt — что поменялось по истории git
(«+» появилось, «-» убрано); folder_changes — последние изменения в этой папке.

{files}

Порядок работы по каждому файлу:
1. Определи тип документа по тексту: регламент, инструкция, положение, приказ, порядок, письмо, черновик и т.д.
   Дальше идут только документы, которые описывают процессы и обязанности работников.
2. Подтверждён ли документ. Подтверждён — если есть «УТВЕРЖДАЮ» с должностью, подписью и датой,
   «Утверждено приказом №…», «введено в действие». Проект, черновик, «на согласовании» — не подтверждён.
   PDF обычно скан: текст в texts/ распознан с печатного слоя, а рукописные подпись, дата и печать в нём
   выглядят как пустые «_____». Поэтому для PDF решай по изображениям страниц pages/ (они приложены к сообщению):
   есть ли у грифа «УТВЕРЖДАЮ» подпись и рукописная дата, печать или штамп «Действующий», подписи в листе
   согласования. Пустые строки в тексте при подписи на изображении — не причина считать документ неутверждённым.
   Запиши, на какой странице и что именно видно. Не уверен в изображении — открой файл страницы ещё раз.
3. Какие процессы описывает документ и кто в них участвует. Процесс — порядок действий из самого документа.
   Участник — названная должность или фамилия с инициалами. Должность важнее имени.
4. Полное ФИО каждого участника:
   `{tool} position "должность как в документе"` — кто её занимает;
   `{tool} people "фамилия"` — подтвердить человека по фамилии;
   `{tool} department "отдел"`; `{tool} norm "отдел"` — положение об отделе, его круг ответственности;
   `{tool} manager "Полное ФИО"` — данные для поиска руководителя: подразделение, руководители
   цепочки подразделений 1С (unit_chain_heads, от ближнего к верхнему) и руководящие должности его отдела.
5. Круг ответственности: что документ поручает этому человеку. Может быть, документ даёт ему новую обязанность.
   Если документ изменён, смотри diffs: новые обязанности — это строки с «+».
6. Какие задачи у него уже есть: `{tool} tasks "Полное ФИО"` (задачи платформы, вместе с периодическими)
   и `{tool} onec-tasks "Полное ФИО"` (открытые задачи 1С:Документооборота, только для сверки).
7. Если обязанности уже покрыты задачами или для человека ничего не изменилось — ничего не делай.
   Если есть пробел — поставь задачу. Регулярная обязанность («ежемесячно», «каждую пятницу», «ежеквартально») —
   периодическая задача: recurrence daily | weekly | monthly | quarterly | yearly.
   Задачу можно поставить только сотруднику с учётной записью (user_id не пустой).
8. Контроль. Если исполнителю ставится задача, определи, кто её контролирует:
   - если документ сам назначает контролирующего («контроль возложить на…», «контролирует…») — его;
   - иначе непосредственного руководителя исполнителя. Смотри `{tool} manager`: ближний руководитель в
     unit_chain_heads; если подразделение в 1С не заполнено — начальник его отдела из department_leaders
     (не заместитель, если есть сам начальник). Сверь с должностью из документа и здравым смыслом:
     у начальника отдела руководитель — директор направления, а не он сам.
   - контроль не нужен, если исполнитель — первый руководитель или документ прямо говорит, что он отчитывается сам.
   Если руководителя нельзя определить уверенно или у него нет учётной записи — контроль не ставь, напиши почему.
   В плане по каждой задаче укажи контролирующего и почему именно он.

Всё нужное — в рабочем каталоге и в командах {tool}. Исходный код системы, тесты и другие каталоги не читай.
Не читай .env, не меняй файлы базы и доступы, не ставь задачи в 1С. Всех сотрудников подряд не выгружай.

На первом шаге только план: тип каждого документа, подтверждён ли он и какой фразой, участники и их ФИО,
что им поручено и какие задачи нужны, будет ли новость и нужна ли к ней картинка (и что на ней).
Команды task и news на этом шаге отказывают — не вызывай их, картинки тоже пока не генерируй.
"""


def _run_prompt(workspace: Path, plan: str, tool: str) -> str:
    return f"""Выполни план. Человека нет, ничего не спрашивай.
Задача ставится только по подтверждённому документу. Запиши JSON в decisions/ и вызови:

`{tool} task decisions/task-1.json`
{{"file_id":"...","approval_quote":"УТВЕРЖДАЮ Генеральный директор ... (фраза из текста)",
"approval_page":"для PDF — pages/<file_id>-pN.png, где видна подпись и дата","approval_seen":"что видно: подпись, дата 28.11.2024, печать",
"assignee_fio":"Фамилия Имя Отчество","position":"должность как в документе",
"process_quote":"фраза из текста, где этому участнику поручена обязанность",
"description":"Что сделать и какой результат нужен","due_at":"ISO 8601 с часовым поясом",
"priority":"normal","recurrence":"","recurrence_until":"",
"basis":"Пункт документа и почему задача нужна: какой обязанности не было в задачах",
"control_fio":"ФИО контролирующего или пусто","control_reason":"почему он: руководитель отдела / назначен п. 7.2",
"control_due_at":"срок контроля, если отличается от срока исполнителя, иначе пусто"}}
Задача на контроль ставится той же командой. Система проверит, что контролирующий — руководитель исполнителя
по оргструктуре или назван в документе. В ответе поле control — создана ли она и почему нет.

После задач по документу — одна новость на «Сегодня» об изменении процесса:
`{tool} news decisions/news-<file_id>.json`
{{"file_id":"...","approval_quote":"та же фраза","approval_page":"та же страница","title":"Изменился процесс: ...",
"body":"Что поменялось в процессе, кого касается и какие задачи поставлены","show_until":"ISO 8601, обычно через 7 дней",
"recipients":["ФИО участников, которых касается изменение"],"image":""}}
Новость — только если процесс по документу новый или изменился. Владелец документа, исполнители задач
и их руководители получат её сами.

Картинка к новости. Реши сам, нужна ли она:
- нужна, если документ вводит новый процесс или заметно меняет существующий, касается нескольких людей
  или отдела и суть можно показать образом: маршрут документа, этапы, контроль, сроки, передача между отделами;
- не нужна, если это мелкая правка, уточнение срока или формулировки, одна задача одному человеку,
  кадровая, дисциплинарная или конфиденциальная тема.
Если нужна — вызови встроенный generateImage один раз до команды news. description на английском:
flat corporate vector illustration, 16:9, calm blue-teal palette, white background, abstract metaphor of the process;
no text, no letters, no digits, no logos, no real people or faces, no readable documents.
В поле image запиши filePath, который вернул generateImage. Без картинки оставь image пустым.
Если news отказала из-за картинки — опубликуй новость без неё.
Если команда ответила refused — прочитай причину, исправь JSON или откажись от решения. Не обходи проверку.
В конце коротко напиши: по каждому файлу тип, подтверждён ли, что поставлено или почему ничего.

{plan}"""


def _remember_failure(docs: list[ChangedDoc], exc: Exception) -> None:
    db = SessionLocal()
    try:
        state = db.get(ExplorerAccessAgentState, AGENT_KEY)
        if state is None:
            return
        state.fail_count = int(state.fail_count or 0) + 1
        state.last_status = "error"
        state.last_error = str(exc)[:2000]
        state.updated_at = datetime.now(timezone.utc)
        if state.fail_count >= 2 and docs:
            state.watermark = max(doc.updated_at for doc in docs)
            state.fail_count = 0
        db.commit()
    finally:
        db.close()


def _sweep() -> None:
    if not WORK_ROOT.is_dir():
        return
    cutoff = time.time() - 7 * 86400
    for child in WORK_ROOT.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue

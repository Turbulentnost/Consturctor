"""Инструменты агента процессов: задачи сотрудника, постановка задачи и новость на «Сегодня».

Агент вызывает их из своего рабочего каталога через tool.cmd. Ставить задачи и
публиковать новости можно только на шаге выполнения, только по файлу из этого
запуска и только если в самом тексте есть отметка об утверждении.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_task import PlatformTask
from app.models.user import AppUser
from app.services import platform_tasks, today_news
from app.services.org_structure import fio_key
from app.services.server_agents import sources

AGENT_SOURCE = "server-process-tasks"
AUTHOR_LABEL = "Оркестратор"
WORKSPACE_ENV = "PROCESS_AGENT_WORKSPACE"
MAX_TASKS_PER_FILE = 10
MAX_NEWS_DAYS = 30
_APPROVAL = re.compile(r"утвержд|утвердил|введ[её]н\w* в действие|ввод\w* в действие|вступа\w* в силу")
COMMANDS = {"tasks", "onec-tasks", "task", "news"}


class ToolRefused(RuntimeError):
    pass


def approval_ok(quote: str, text: str) -> bool:
    """Фраза об утверждении взята из самого документа."""
    needle = fio_key(quote)
    return len(needle) >= 8 and needle in fio_key(text) and bool(_APPROVAL.search(needle))


def quote_in(quote: str, text: str) -> bool:
    needle = fio_key(quote)
    return len(needle) >= 8 and needle in fio_key(text)


# ---------- рабочий каталог запуска ----------


def _workspace() -> Path:
    raw = os.environ.get(WORKSPACE_ENV, "").strip()
    if not raw:
        raise ToolRefused("Инструмент запускается только из рабочего каталога агента")
    return Path(raw)


def _phase(workspace: Path) -> str:
    try:
        return (workspace / "phase.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _manifest(workspace: Path) -> dict[str, dict[str, Any]]:
    try:
        rows = json.loads((workspace / "recent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolRefused("Нет recent.json запуска") from exc
    return {str(row.get("file_id")): row for row in rows if isinstance(row, dict)}


def _doc_text(workspace: Path, doc: dict[str, Any]) -> str:
    name = str(doc.get("text_file") or "")
    if not name:
        return ""
    try:
        return (workspace / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _actions(workspace: Path) -> list[dict[str, Any]]:
    path = workspace / "actions.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _remember(workspace: Path, item: dict[str, Any]) -> None:
    with (workspace / "actions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_payload(raw: str, workspace: Path) -> dict[str, Any]:
    path = Path(raw.strip().strip('"'))
    if not path.is_absolute():
        path = workspace / path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolRefused(f"Не прочитан JSON {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolRefused("JSON должен быть объектом")
    return data


def _approved_doc(workspace: Path, payload: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    if _phase(workspace) != "act":
        raise ToolRefused("На шаге плана ничего не ставится и не публикуется")
    file_id = str(payload.get("file_id") or "").strip()
    doc = _manifest(workspace).get(file_id)
    if doc is None:
        raise ToolRefused("file_id не из этого запуска")
    text = _doc_text(workspace, doc)
    if not text:
        raise ToolRefused("Текст файла не прочитан — решения по нему не выносятся")
    approval = " ".join(str(payload.get("approval_quote") or "").split())
    if not approval_ok(approval, text):
        raise ToolRefused(
            "Документ не подтверждён: approval_quote должна быть фразой из текста с отметкой "
            "«утверждаю», «утверждено», «введено в действие»"
        )
    pages = [str(item) for item in doc.get("page_images") or []]
    if pages:
        page = str(payload.get("approval_page") or "").strip().replace("\\", "/")
        if page not in pages:
            raise ToolRefused(
                "Это скан: approval_page — изображение страницы из page_images, где видны подпись и дата утверждения"
            )
        seen = " ".join(str(payload.get("approval_seen") or "").split())
        number = page.rsplit("-p", 1)[-1].removesuffix(".png")
        approval = f"{approval} (скан, стр. {number}: {seen[:200] or 'подпись и дата'})"
    return doc, text, approval


def _linked_person(db: Session, fio: str, phrase: str, text: str, name: str) -> dict[str, str]:
    from app.services.server_agents.access_advisor import person_mentioned, position_in_text, position_matches

    post_in_text = bool(phrase) and position_in_text(phrase, text, name)
    holders = [
        holder
        for holder in (sources.position_holders(db, phrase) if post_in_text else [])
        if position_matches(holder.get("position") or "", phrase)
    ]
    surname = (fio_key(fio).split() or [""])[0]
    if fio.strip():
        named = sources.resolve_person(db, fio)
        people = [named] if named is not None else []
        people += [item for item in holders if surname and (fio_key(item.get("fio") or "").split() or [""])[0] == surname]
    elif len(holders) > 1:
        raise ToolRefused("Должность занимают несколько сотрудников — укажите assignee_fio")
    else:
        people = holders
    for person in people:
        if not person.get("user_id"):
            continue
        by_name = person_mentioned(person.get("fio") or "", text, name)
        by_post = post_in_text and position_matches(person.get("position") or "", phrase)
        if by_name or by_post:
            return person
    raise ToolRefused(
        "Сотрудник не связан с документом: в тексте нет его фамилии с именем или инициалами "
        "и нет его должности, либо у него нет учётной записи"
    )


def _sender(db: Session, owner_id: str) -> str:
    support = db.scalar(select(AppUser.id).where(AppUser.is_support.is_(True)).limit(1))
    return support or owner_id


def _same_task(db: Session, assignee_id: str, file_id: str, description: str) -> bool:
    rows = db.scalars(
        select(PlatformTask).where(
            PlatformTask.assignee_user_id == assignee_id,
            PlatformTask.source == AGENT_SOURCE,
            PlatformTask.source_ref == file_id,
        )
    ).all()
    wanted = fio_key(description)
    return any(difflib.SequenceMatcher(None, fio_key(row.description), wanted).ratio() >= 0.8 for row in rows)


# ---------- команды ----------


def person_tasks(db: Session, fio: str) -> dict[str, Any]:
    person = sources.resolve_person(db, fio)
    if person is None:
        return {"ok": False, "error": "Сотрудник не найден или под строку подходят несколько. Уточните ФИО"}
    user_id = person.get("user_id") or ""
    rows = (
        db.scalars(
            select(PlatformTask)
            .where(PlatformTask.assignee_user_id == user_id)
            .order_by(PlatformTask.due_at.desc())
            .limit(200)
        ).all()
        if user_id
        else []
    )
    latest_series: set[str] = set()
    items = []
    for task in rows:
        if task.recurrence:
            series = task.series_id or task.id
            if series in latest_series:
                continue
            latest_series.add(series)
        elif task.status != "open":
            continue
        items.append(
            {
                "description": task.description[:500],
                "due_at": task.due_at.isoformat() if task.due_at else "",
                "status": task.status,
                "recurrence": task.recurrence,
                "basis": task.basis[:300],
                "author": task.author_fio,
            }
        )
        if len(items) >= 40:
            break
    return {"ok": True, "person": person, "platform_tasks": items}


def person_onec_tasks(fio: str) -> dict[str, Any]:
    from app.tools.onec.dok_soap import fetch_user_inbox_tasks

    try:
        payload = fetch_user_inbox_tasks(fio, since_days=90, only_open=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"1С:Документооборот не ответил: {exc}"}
    rows = payload.get("rows") if isinstance(payload, dict) else None
    items = [
        {key: str(row.get(key) or "")[:300] for key in ("title", "step", "author", "begin", "due")}
        for row in (rows if isinstance(rows, list) else [])[:40]
        if isinstance(row, dict)
    ]
    return {"ok": True, "onec_tasks": items}


def create_task(db: Session, workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    doc, text, approval = _approved_doc(workspace, payload)
    file_id, name = str(doc["file_id"]), str(doc.get("name") or "")
    quote = " ".join(str(payload.get("process_quote") or "").split())
    if not quote_in(quote, text):
        raise ToolRefused("process_quote — непрерывная фраза из текста, где описана обязанность")
    phrase = " ".join(str(payload.get("position") or "").split())
    person = _linked_person(db, str(payload.get("assignee_fio") or ""), phrase, text, name)
    evidence = fio_key(quote)
    surname = fio_key(person["fio"]).split()[0]
    if surname not in evidence and not (phrase and fio_key(phrase) in evidence):
        raise ToolRefused("В process_quote нет ни фамилии исполнителя, ни его должности")
    done = [item for item in _actions(workspace) if item.get("kind") == "task" and item.get("file_id") == file_id]
    if len(done) >= MAX_TASKS_PER_FILE:
        raise ToolRefused(f"По одному документу не больше {MAX_TASKS_PER_FILE} задач за запуск")
    description = str(payload.get("description") or "").strip()
    if _same_task(db, person["user_id"], file_id, description):
        raise ToolRefused("Такая задача по этому документу у сотрудника уже есть")
    why = " ".join(str(payload.get("basis") or "").split())
    basis = f"Утверждённый документ «{name}»: {approval[:300]}"
    if why:
        basis = f"{basis}\n{why[:1200]}"
    try:
        task = platform_tasks.create_agent_task(
            db,
            source=AGENT_SOURCE,
            source_ref=file_id,
            author_label=f"{AUTHOR_LABEL} · по документу «{name}»"[:512],
            notify_sender_id=_sender(db, str(doc.get("owner_user_id") or "")),
            assignee_user_id=person["user_id"],
            description=description,
            basis=basis,
            due_at=platform_tasks.parse_due(str(payload.get("due_at") or "")),
            priority=str(payload.get("priority") or "normal"),
            recurrence=str(payload.get("recurrence") or ""),
            recurrence_until=platform_tasks.parse_optional_moment(str(payload.get("recurrence_until") or "")),
        )
    except platform_tasks.PlatformTaskError as exc:
        raise ToolRefused(exc.message) from exc
    _remember(
        workspace,
        {
            "kind": "task",
            "file_id": file_id,
            "task_id": task["id"],
            "assignee": person["fio"],
            "user_id": person["user_id"],
            "description": description[:400],
            "recurrence": task["recurrence"],
        },
    )
    result = {"ok": True, "task_id": task["id"], "assignee": person["fio"], "due_at": task["due_at"]}
    controller = " ".join(str(payload.get("control_fio") or "").split())
    if controller:
        why = " ".join(str(payload.get("control_reason") or "").split())
        due = str(payload.get("control_due_at") or task["due_at"])
        result["control"] = _control_task(db, workspace, doc, text, person, task, basis, controller, why, due)
    return result


def _control_task(
    db: Session,
    workspace: Path,
    doc: dict[str, Any],
    text: str,
    person: dict[str, str],
    task: dict[str, Any],
    basis: str,
    controller: str,
    why: str,
    due: str,
) -> dict[str, Any]:
    """Задача на контроль тому, кого выбрал агент: руководителю исполнителя или контролёру из документа."""
    from app.services.server_agents.access_advisor import person_mentioned

    file_id, name = str(doc["file_id"]), str(doc.get("name") or "")
    boss = sources.resolve_person(db, controller)
    if boss is None:
        return {"created": False, "reason": "Контролирующий не найден или под ФИО подходят несколько"}
    if not boss.get("user_id"):
        return {"created": False, "manager": boss["fio"], "reason": "У контролирующего нет учётной записи в системе"}
    if boss["user_id"] == person["user_id"]:
        return {"created": False, "reason": "Исполнитель не может контролировать сам себя"}
    if not (sources.is_superior(db, person["fio"], boss["fio"]) or person_mentioned(boss["fio"], text, name)):
        return {
            "created": False,
            "manager": boss["fio"],
            "reason": "Он не руководитель исполнителя по оргструктуре и не назван в документе",
        }
    description = f"Контроль: {person['fio']} — {task['description']}"
    if _same_task(db, boss["user_id"], file_id, description):
        return {"created": False, "manager": boss["fio"], "reason": "Такая задача на контроль уже есть"}
    post = f", {person['position']}" if person.get("position") else ""
    try:
        control = platform_tasks.create_agent_task(
            db,
            source=AGENT_SOURCE,
            source_ref=file_id,
            author_label=f"{AUTHOR_LABEL} · по документу «{name}»"[:512],
            notify_sender_id=_sender(db, str(doc.get("owner_user_id") or "")),
            assignee_user_id=boss["user_id"],
            description=description,
            basis=(
                f"{basis}\nКонтроль исполнения задачи подчинённого: {person['fio']}{post}"
                + (f"\n{why[:400]}" if why else "")
            )[: platform_tasks.MAX_BASIS_CHARS],
            due_at=platform_tasks.parse_due(due),
            priority=str(task.get("priority") or "normal"),
            recurrence=str(task.get("recurrence") or ""),
            recurrence_until=platform_tasks.parse_optional_moment(str(task.get("recurrence_until") or "")),
        )
    except platform_tasks.PlatformTaskError as exc:
        return {"created": False, "manager": boss["fio"], "reason": exc.message}
    _remember(
        workspace,
        {
            "kind": "control",
            "file_id": file_id,
            "task_id": control["id"],
            "controls": task["id"],
            "assignee": boss["fio"],
            "user_id": boss["user_id"],
            "description": description[:400],
        },
    )
    return {"created": True, "task_id": control["id"], "manager": boss["fio"]}


def generated_assets(workspace: Path) -> list[Path]:
    """Папки, куда встроенный generateImage кладёт картинки этого запуска."""
    root = Path.home() / ".cursor" / "projects"
    if not root.is_dir():
        return []
    run = workspace.name.lower()
    return [item / "assets" for item in root.iterdir() if item.is_dir() and item.name.lower().endswith(run)]


def _news_image(workspace: Path, raw: str) -> bytes | None:
    raw = raw.strip().strip('"')
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    allowed = [(workspace / "images").resolve(), *(folder.resolve() for folder in generated_assets(workspace))]
    if not any(path.is_relative_to(folder) for folder in allowed):
        raise ToolRefused("image — только файл, который вернул generateImage в этом запуске")
    if not path.is_file():
        raise ToolRefused(f"Картинка {path.name} не найдена")
    if path.stat().st_size > today_news.MAX_IMAGE_BYTES:
        raise ToolRefused("Картинка больше 8 МБ")
    return path.read_bytes()


def publish_news(db: Session, workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    doc, text, _approval = _approved_doc(workspace, payload)
    file_id, name = str(doc["file_id"]), str(doc.get("name") or "")
    if any(item.get("kind") == "news" and item.get("file_id") == file_id for item in _actions(workspace)):
        raise ToolRefused("Новость по этому документу в этом запуске уже опубликована")
    try:
        until = today_news.parse_until(str(payload.get("show_until") or ""))
    except today_news.NewsError as exc:
        raise ToolRefused(exc.message) from exc
    if until > datetime.now(timezone.utc) + timedelta(days=MAX_NEWS_DAYS):
        raise ToolRefused(f"Новость агента показывается не дольше {MAX_NEWS_DAYS} дней")
    tasks = [
        item for item in _actions(workspace) if item.get("kind") in {"task", "control"} and item.get("file_id") == file_id
    ]
    recipients = {str(item.get("user_id")) for item in tasks if item.get("user_id")}
    owner = str(doc.get("owner_user_id") or "")
    if owner:
        recipients.add(owner)
    skipped: list[str] = []
    for fio in payload.get("recipients") or []:
        try:
            person = _linked_person(db, str(fio), "", text, name)
        except ToolRefused:
            skipped.append(str(fio))
            continue
        recipients.add(person["user_id"])
    image = _news_image(workspace, str(payload.get("image") or ""))
    try:
        news = today_news.publish(
            db,
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
            show_until=until,
            user_ids=sorted(recipients),
            kind="process_change",
            source=AGENT_SOURCE,
            author_label=AUTHOR_LABEL,
            file_id=file_id,
            file_name=name,
            task_ids=[str(item.get("task_id")) for item in tasks],
            image=image,
        )
    except today_news.NewsError as exc:
        raise ToolRefused(exc.message) from exc
    with_image = bool(news.get("image_url"))
    _remember(
        workspace,
        {"kind": "news", "file_id": file_id, "news_id": news["id"], "title": news["title"], "image": with_image},
    )
    return {"ok": True, "news_id": news["id"], "recipients": len(recipients), "image": with_image, "not_linked": skipped}


def main(argv: list[str]) -> int:
    command, rest = argv[0], " ".join(argv[1:]).strip()
    if command == "onec-tasks":
        sources._emit(person_onec_tasks(rest))
        return 0
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if command == "tasks":
            sources._emit(person_tasks(db, rest))
            return 0
        workspace = _workspace()
        payload = _load_payload(rest, workspace)
        result = create_task(db, workspace, payload) if command == "task" else publish_news(db, workspace, payload)
        sources._emit(result)
        return 0
    except ToolRefused as exc:
        sources._emit({"ok": False, "refused": True, "error": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 — агент видит причину, а не трассировку с адресом базы
        sources._emit({"ok": False, "error": str(exc) or exc.__class__.__name__})
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

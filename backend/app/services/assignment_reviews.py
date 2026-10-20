"""Снимки поручений АСТ00 и вердикты агента проверки к закрытию."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.assignment_review import AssignmentReview, AssignmentReviewTask, AssignmentReviewVerdict

logger = logging.getLogger(__name__)

LiveLoader = Callable[[str, str], dict[str, Any] | None]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _latest_verdict(rows: list[AssignmentReviewVerdict]) -> AssignmentReviewVerdict | None:
    if not rows:
        return None
    return max(rows, key=lambda row: row.created_at)


def _file_view(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _text(item.get("id") or item.get("ref_key")),
        "name": _text(item.get("name")),
        "extension": _text(item.get("extension")),
        "size": _text(item.get("size")),
        "created": _text(item.get("created")),
        "uploaded_by": _text(item.get("uploaded_by")),
    }


def _comment_view(item: dict[str, Any]) -> dict[str, str]:
    return {
        "step": _text(item.get("step")),
        "performer": _text(item.get("performer")),
        "begin": _text(item.get("begin")),
        "comment": _text(item.get("comment") or item.get("report")),
    }


def _task_from_docflow(task: dict[str, Any], n: int) -> dict[str, Any]:
    history = task.get("history") if isinstance(task.get("history"), list) else []
    comments = [_comment_view(step) for step in history if isinstance(step, dict) and step.get("report")]
    if not comments and task.get("executor_report"):
        comments = [_comment_view({"comment": task.get("executor_report"), "performer": task.get("performer")})]
    files = [_file_view(item) for item in (task.get("files") or []) if isinstance(item, dict)]
    task_id = (
        _text(task.get("open_execute_task_id"))
        or _text(task.get("open_check_task_id"))
        or _text((history[0] or {}).get("task_id") if history else "")
        or _text(task.get("task_id") or task.get("id"))
    )
    return {
        "n": n,
        "task_id": task_id,
        "chain": _text(task.get("chain")),
        "performer": _text(task.get("performer")),
        "author": _text(task.get("author")),
        "text": _text(task.get("text") or task.get("title") or task.get("task")),
        "begin": _text(task.get("begin"))[:32],
        "due": _text(task.get("due"))[:32],
        "state": _text(task.get("label") or task.get("state") or task.get("task_state")),
        "returns": int(task.get("returns") or 0),
        "comments": comments,
        "files": files,
        "open_check_task_id": _text(task.get("open_check_task_id") or (task.get("task_id") if task.get("action") else "")),
        "open_execute_task_id": _text(task.get("open_execute_task_id") or task.get("open_task_id")),
    }


def _task_from_agent(item: dict[str, Any]) -> dict[str, Any]:
    n = int(item.get("n") or 1)
    action = _text(item.get("action")).casefold()
    return {
        "n": n,
        "task_id": _text(item.get("task_id") or item.get("open_task_id")),
        "chain": "",
        "performer": _text(item.get("performer") or item.get("executor")),
        "author": "",
        "text": _text(item.get("task") or item.get("title") or item.get("text")),
        "begin": "",
        "due": "",
        "state": _text(item.get("task_state")),
        "returns": 0,
        "comments": [],
        "files": [],
        "open_check_task_id": _text(item.get("task_id")) if action in {"close", "return"} else "",
        "open_execute_task_id": _text(item.get("open_task_id")),
        "verdict": _text(item.get("conclusion")),
        "comment": _text(item.get("comment")),
        "evidence": _text(item.get("evidence")),
        "advice": _text(item.get("advice")),
        "action": action if action in {"close", "return"} else "",
    }


def load_live_assignment(ref_key: str, number: str) -> dict[str, Any] | None:
    """Шапка, файлы и задачи ДО на момент записи снимка. Сбой 1С не должен сорвать сохранение вердикта."""
    from app.services.erp_assignments import AssignmentError, _get_assignment

    args: dict[str, Any] = {"include_tasks": True}
    if ref_key:
        args["ref_key"] = ref_key
    elif number:
        args["number"] = number
    else:
        return None
    try:
        payload = _get_assignment(args)
    except (AssignmentError, Exception) as exc:  # noqa: BLE001
        logger.warning("assignment review snapshot failed: %s", str(exc)[:240])
        return None
    item = payload.get("assignment")
    return item if isinstance(item, dict) else None


def _merge_task(live: dict[str, Any] | None, agent: dict[str, Any]) -> dict[str, Any]:
    base = dict(live or {})
    overlay = _task_from_agent(agent)
    for field in ("n", "performer", "text", "state", "task_id", "open_check_task_id", "open_execute_task_id"):
        if overlay.get(field) and not base.get(field):
            base[field] = overlay[field]
    if not base.get("n"):
        base["n"] = overlay["n"]
    for field in ("verdict", "comment", "evidence", "advice", "action"):
        base[field] = overlay.get(field) or ""
    return base


def _apply_header(row: AssignmentReview, live: dict[str, Any] | None, item: dict[str, Any]) -> None:
    src = live or {}
    row.number = _text(src.get("number") or item.get("number"))
    row.ref_key = _text(src.get("ref_key") or item.get("target_id") or row.ref_key)
    row.status = _text(src.get("status") or row.status)
    opened = src.get("open")
    row.open = bool(opened) if opened is not None else row.open
    row.date = _text(src.get("date") or row.date)[:32]
    row.topic = _text(src.get("topic") or row.topic)
    row.basis = _text(src.get("basis") or row.basis)
    row.manager = _text(src.get("customer") or src.get("manager") or row.manager)
    row.organization = _text(src.get("organization") or row.organization)
    row.reporter = _text(src.get("reporter") or row.reporter)
    row.secretary = _text(src.get("secretary") or row.secretary)
    row.due = _text(src.get("due") or row.due)[:32]
    row.weekly_report_date = _text(src.get("weekly_report_date") or row.weekly_report_date)[:32]
    row.final_report_date = _text(src.get("final_report_date") or row.final_report_date)[:32]
    if isinstance(src.get("lines"), list):
        row.lines_json = src.get("lines") or []
    if isinstance(src.get("files"), list):
        row.files_json = [_file_view(item) for item in src["files"] if isinstance(item, dict)]
    row.conclusion = _text(item.get("conclusion"))
    row.reason = _text(item.get("reason"))
    row.done = int(item.get("done") or 0)
    row.total = int(item.get("total") or 0)
    row.source = "open" if row.open else "closed"


def _upsert_task(db: Session, review: AssignmentReview, data: dict[str, Any]) -> AssignmentReviewTask:
    n = int(data.get("n") or 1)
    row = next((task for task in review.tasks if task.n == n), None)
    if row is None:
        row = AssignmentReviewTask(id=str(uuid4()), review_id=review.id, n=n)
        db.add(row)
        review.tasks.append(row)
    row.task_id = _text(data.get("task_id"))
    row.chain = _text(data.get("chain"))
    row.performer = _text(data.get("performer"))
    row.author = _text(data.get("author"))
    row.text = _text(data.get("text"))
    row.begin = _text(data.get("begin"))[:32]
    row.due = _text(data.get("due"))[:32]
    row.state = _text(data.get("state"))
    row.returns = int(data.get("returns") or 0)
    row.comments_json = data.get("comments") or []
    row.files_json = data.get("files") or []
    row.open_check_task_id = _text(data.get("open_check_task_id"))
    row.open_execute_task_id = _text(data.get("open_execute_task_id"))
    return row


def _verdict_view(task: AssignmentReviewTask, verdict: AssignmentReviewVerdict | None) -> dict[str, Any]:
    payload = {
        "n": task.n,
        "task_id": task.task_id,
        "chain": task.chain,
        "performer": task.performer,
        "author": task.author,
        "title": task.text,
        "text": task.text,
        "begin": task.begin,
        "due": task.due,
        "state": task.state,
        "returns": task.returns,
        "executed": task.state == "принято проверяющим",
        "comments": task.comments_json or [],
        "files": task.files_json or [],
        "open_check_task_id": task.open_check_task_id,
        "open_execute_task_id": task.open_execute_task_id,
        "result": next((item.get("comment") for item in (task.comments_json or []) if item.get("comment")), ""),
        "conclusion": "",
        "comment": "",
        "evidence": "",
        "advice": "",
        "action": "",
        "reason": "",
        "open_task_id": task.open_execute_task_id,
    }
    if verdict:
        payload.update(
            {
                "conclusion": verdict.verdict,
                "comment": verdict.comment,
                "evidence": verdict.evidence,
                "advice": verdict.advice,
                "action": verdict.action,
                "reason": verdict.comment,
                "task_state": task.state,
                "task": task.text,
            }
        )
        if verdict.action in {"close", "return"}:
            payload["task_id"] = task.open_check_task_id or task.task_id
    return payload


def review_view(row: AssignmentReview) -> dict[str, Any]:
    by_task: dict[str, list[AssignmentReviewVerdict]] = {}
    for verdict in row.verdicts:
        by_task.setdefault(verdict.task_row_id, []).append(verdict)
    tasks = sorted(row.tasks, key=lambda task: task.n)
    task_views = [_verdict_view(task, _latest_verdict(by_task.get(task.id, []))) for task in tasks]
    return {
        "id": row.id,
        "ref_key": row.ref_key,
        "number": row.number,
        "status": row.status,
        "open": row.open,
        "date": row.date,
        "topic": row.topic,
        "basis": row.basis,
        "manager": row.manager,
        "customer": row.manager,
        "organization": row.organization,
        "reporter": row.reporter,
        "secretary": row.secretary,
        "due": row.due,
        "weekly_report_date": row.weekly_report_date,
        "final_report_date": row.final_report_date,
        "lines": row.lines_json or [],
        "files": row.files_json or [],
        "conclusion": row.conclusion,
        "reason": row.reason,
        "done": row.done,
        "total": row.total,
        "source": row.source,
        "checked_at": row.checked_at.isoformat() if row.checked_at else "",
        "run_id": row.run_id,
        "tasks": task_views,
        "target_id": row.ref_key,
    }


def _with_parts(stmt):
    return stmt.options(selectinload(AssignmentReview.tasks), selectinload(AssignmentReview.verdicts))


def get_review(db: Session, *, ref_key: str = "", number: str = "") -> dict[str, Any] | None:
    stmt = _with_parts(select(AssignmentReview))
    if ref_key:
        stmt = stmt.where(AssignmentReview.ref_key == ref_key)
    elif number:
        stmt = stmt.where(AssignmentReview.number == number)
    else:
        return None
    row = db.scalars(stmt).first()
    return review_view(row) if row else None


def list_reviews(db: Session, *, date_from: str = "", date_to: str = "") -> list[dict[str, Any]]:
    stmt = _with_parts(select(AssignmentReview)).order_by(
        AssignmentReview.date.desc(), AssignmentReview.number.desc()
    )
    views = []
    for row in db.scalars(stmt).unique().all():
        view = review_view(row)
        day = (view.get("date") or "")[:10]
        if date_from and day and day < date_from[:10]:
            continue
        if date_to and day and day > date_to[:10]:
            continue
        views.append(view)
    return views


def list_reviewed_keys(db: Session) -> dict[str, Any]:
    keys: list[str] = []
    numbers: list[str] = []
    closed: list[str] = []
    for row in db.scalars(select(AssignmentReview)).all():
        if row.ref_key:
            keys.append(row.ref_key)
        if row.number:
            numbers.append(row.number)
        if not row.open and row.number:
            closed.append(row.number)
    return {
        "summary": f"Проверено поручений: {len(numbers)}",
        "count": len(numbers),
        "ref_keys": keys,
        "numbers": numbers,
        "closed_numbers": closed,
        "source": "db",
    }


def save_reviews(
    db: Session,
    items: list[dict[str, Any]],
    *,
    user_id: str = "",
    workflow_id: str = "",
    run_id: str = "",
    live_loader: LiveLoader | None = None,
) -> dict[str, Any]:
    loader = live_loader if live_loader is not None else load_live_assignment
    saved: list[str] = []
    skipped: list[str] = []
    for item in items:
        number = _text(item.get("number"))
        ref_key = _text(item.get("target_id") or item.get("ref_key"))
        if not number and not ref_key:
            continue
        row = None
        if ref_key:
            row = db.scalars(
                _with_parts(select(AssignmentReview).where(AssignmentReview.ref_key == ref_key))
            ).first()
        if row is None and number:
            row = db.scalars(
                _with_parts(select(AssignmentReview).where(AssignmentReview.number == number))
            ).first()
        elif row is not None:
            row = db.scalars(_with_parts(select(AssignmentReview).where(AssignmentReview.id == row.id))).first()
        live = None
        if row is None or row.open:
            live = loader(ref_key, number)
        if row is None:
            row = AssignmentReview(
                id=str(uuid4()),
                ref_key=ref_key or _text((live or {}).get("ref_key")) or number,
                number=number,
                user_id=user_id,
            )
            db.add(row)
            db.flush()
        if not row.open and row.checked_at and live is None and row.tasks:
            # Закрытое уже снято: вердикты не переписываем повторной проверкой.
            skipped.append(row.number)
            continue
        _apply_header(row, live, item)
        row.user_id = user_id or row.user_id
        row.workflow_id = workflow_id or row.workflow_id
        row.run_id = run_id or row.run_id
        row.checked_at = _now()
        live_tasks = live.get("docflow_tasks") if isinstance(live, dict) else None
        agent_tasks = [task for task in (item.get("tasks") or []) if isinstance(task, dict)]
        for index, agent in enumerate(agent_tasks, start=1):
            live_task = None
            if isinstance(live_tasks, list) and index <= len(live_tasks) and isinstance(live_tasks[index - 1], dict):
                live_task = _task_from_docflow(live_tasks[index - 1], index)
            merged = _merge_task(live_task, agent)
            merged["n"] = int(agent.get("n") or index)
            task_row = _upsert_task(db, row, merged)
            db.flush()
            db.add(
                AssignmentReviewVerdict(
                    id=str(uuid4()),
                    review_id=row.id,
                    task_row_id=task_row.id,
                    run_id=run_id,
                    verdict=_text(agent.get("conclusion")),
                    comment=_text(agent.get("comment")),
                    evidence=_text(agent.get("evidence")),
                    advice=_text(agent.get("advice")),
                    action=_text(agent.get("action")).casefold()
                    if _text(agent.get("action")).casefold() in {"close", "return"}
                    else "",
                    created_at=_now(),
                )
            )
        saved.append(row.number)
    db.commit()
    return {"saved": saved, "skipped": skipped, "count": len(saved)}

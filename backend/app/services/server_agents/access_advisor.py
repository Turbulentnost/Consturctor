"""Серверный агент доступа к базе знаний.

Раз в 30 минут, и только если изменился файл, запускается конфигурация 2
(тот же runner, модель и запись в turbotest.runs). Человек этого хода не видит.
Агент предлагает ключ лишь когда человек или отдел прямо названы в документе.
Ключ выдаётся, когда владелец на «Сегодня» нажимает галочку.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal, engine
from app.models.explorer import ExplorerEntry, ExplorerFileKey, ExplorerKeyGrant
from app.models.explorer_access import ExplorerAccessAgentState, ExplorerAccessSuggestion
from app.models.user import AppUser
from app.services import explorer
from app.services.explorer import ExplorerError
from app.services.org_structure import fio_key
from app.services.server_agents import sources

logger = logging.getLogger(__name__)

AGENT_KEY = "explorer-access"
AGENT_TITLE = "Доступ к файлам базы знаний"
CONFIG_ID = "02-plan-instruction"
INTERVAL_S = 30 * 60
FIRST_DELAY_S = 90
BATCH = 12
TURN_TIMEOUT_S = 15 * 60
_LOCK = threading.Lock()

_HERE = Path(__file__).resolve()
BACKEND_DIR = _HERE.parents[3]
CONFIG_DIR = (
    _HERE.parents[4]
    / "orchestrator"
    / "agent-platform"
    / "platform"
    / "configs"
    / CONFIG_ID
)
WORK_ROOT = BACKEND_DIR / "var" / "server-agents" / "explorer-access"
SDK_STORE = BACKEND_DIR / "var" / "server-agents" / "sdk-store"

PERM_RU = {"read": "чтение", "write": "запись"}


@dataclass
class GrantView:
    kind: str
    grantee_id: str
    grantee_label: str
    permission: str


@dataclass
class DocumentView:
    file_id: str
    name: str
    owner_user_id: str
    owner_fio: str
    mode: str
    text: str
    updated_at: datetime
    grants: list[GrantView] = field(default_factory=list)


@dataclass
class Draft:
    file_id: str
    file_name: str
    owner_user_id: str
    document_kind: str
    kind: str
    grantee_id: str
    grantee_label: str
    position: str
    department: str
    permission: str
    reason: str
    quote: str


def tick_access_advisor() -> None:
    if not _LOCK.acquire(blocking=False):
        return
    try:
        _tick()
    except Exception:
        logger.exception("access advisor tick failed")
    finally:
        _LOCK.release()


def list_pending(db: Session, user_id: str) -> list[dict[str, str]]:
    rows = db.scalars(
        select(ExplorerAccessSuggestion)
        .where(
            ExplorerAccessSuggestion.owner_user_id == user_id,
            ExplorerAccessSuggestion.status == "pending",
        )
        .order_by(ExplorerAccessSuggestion.created_at.desc())
    ).all()
    return [suggestion_out(row) for row in rows]


def suggestion_out(row: ExplorerAccessSuggestion) -> dict[str, str]:
    return {
        "id": row.id,
        "file_id": row.file_id,
        "file_name": row.file_name,
        "document_kind": row.document_kind,
        "kind": row.kind,
        "label": row.grantee_label,
        "position": row.position,
        "department": row.department,
        "permission": row.permission,
        "quote": row.quote,
        "reason": row.reason,
    }


def decide(db: Session, user_id: str, suggestion_id: str, accept: bool) -> None:
    row = db.get(ExplorerAccessSuggestion, suggestion_id)
    if row is None or row.owner_user_id != user_id:
        raise ExplorerError("Предложение не найдено", 404)
    if row.status != "pending":
        raise ExplorerError("Это предложение уже разобрано", 409)
    if accept:
        grant_access(db, row)
    row.status = "accepted" if accept else "dismissed"
    row.decided_at = datetime.now(timezone.utc)
    db.commit()


def grant_access(db: Session, row: ExplorerAccessSuggestion) -> None:
    entry = db.get(ExplorerEntry, row.file_id)
    if entry is None or entry.kind != "file":
        raise ExplorerError("Файл уже удалён", 404)
    if entry.owner_user_id != row.owner_user_id:
        raise ExplorerError("Файл принадлежит другому человеку", 403)
    key = db.get(ExplorerFileKey, entry.id)
    if key is None:
        raise ExplorerError("У файла нет ключа", 409)
    if row.kind == "private":
        db.execute(delete(ExplorerKeyGrant).where(ExplorerKeyGrant.file_id == entry.id))
        key.access_mode = "private"
        return
    permission = row.permission if row.permission in {"read", "write"} else "read"
    if row.kind == "all":
        _upsert_grant(db, entry.id, "all", "", "Все сотрудники", permission, "")
        key.access_mode = "all"
        return
    if row.kind == "department":
        name = row.grantee_label or row.department
        _upsert_grant(db, entry.id, "department", name, name, permission, "")
        if key.access_mode in {"private", "users"}:
            key.access_mode = "department"
        return
    _upsert_grant(db, entry.id, "user", row.grantee_id, row.grantee_label, permission, row.department)
    if key.access_mode == "private":
        key.access_mode = "users"


def judge_suggestions(
    docs: list[DocumentView],
    payload: object,
    resolve_person: Callable[[str], dict[str, str] | None],
    resolve_department: Callable[[str], str],
    resolve_position: Callable[[str], list[dict[str, str]]] | None = None,
) -> list[Draft]:
    """Оставляет только те рекомендации, где связь написана в самом документе."""
    by_id = {doc.file_id: doc for doc in docs}
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return []
    holders = resolve_position or (lambda _phrase: [])
    drafts: list[Draft] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        doc = by_id.get(str(item.get("file_id") or "").strip())
        kind_name = " ".join(str(item.get("document_kind") or "").split())
        if doc is None or not doc.text.strip() or len(kind_name) < 3:
            continue
        suggestions = item.get("suggestions")
        if not isinstance(suggestions, list):
            continue
        for raw in suggestions:
            if not isinstance(raw, dict):
                continue
            for draft in _one(doc, kind_name, raw, resolve_person, resolve_department, holders):
                marker = (draft.file_id, draft.kind, fio_key(draft.grantee_label), draft.permission)
                if marker in seen:
                    continue
                seen.add(marker)
                drafts.append(draft)
    return drafts


def person_mentioned(fio: str, text: str, filename: str) -> bool:
    """Фамилия и имя, либо фамилия и инициал: «И.В. Хозуян» — тот же Хозуян Иван."""
    parts = fio_key(fio).split()
    if len(parts) < 2:
        return False
    words = re.findall(r"\w+", fio_key(f"{filename}\n{text}"))
    surname_at = {index for index, word in enumerate(words) if _inflected(word, parts[0])}
    name_at = {index for index, word in enumerate(words) if _inflected(word, parts[1]) and index not in surname_at}
    if surname_at and name_at:
        return True
    return _initial_near(words, parts[0], parts[1][0])


def position_in_text(position: str, text: str, filename: str) -> bool:
    needle = fio_key(position)
    return len(needle) >= 8 and needle in fio_key(f"{filename}\n{text}")


def position_matches(holder_position: str, phrase: str) -> bool:
    holder = fio_key(holder_position)
    needle = fio_key(phrase)
    return len(needle) >= 8 and bool(holder) and (needle in holder or holder in needle)


def _initial_near(words: list[str], surname: str, initial: str) -> bool:
    if not initial:
        return False
    for index, word in enumerate(words):
        if not _inflected(word, surname):
            continue
        window = words[max(0, index - 3) : index] + words[index + 1 : index + 4]
        if any(item == initial for item in window):
            return True
    return False


def department_mentioned(name: str, text: str, filename: str) -> bool:
    tokens = [part for part in fio_key(name).split() if len(part) >= 4] or fio_key(name).split()
    if not tokens:
        return False
    words = re.findall(r"\w+", fio_key(f"{filename}\n{text}"))
    return all(any(_inflected(word, token) for word in words) for token in tokens)


def _inflected(word: str, token: str) -> bool:
    if word == token:
        return True
    cut = 2 if len(token) >= 7 else 1 if len(token) >= 5 else 0
    stem = token[: len(token) - cut]
    if len(stem) < 4:
        return False
    return word.startswith(stem) and abs(len(word) - len(token)) <= 1


def quote_in(quote: str, text: str, filename: str) -> bool:
    needle = fio_key(quote)
    if len(needle) < 8:
        return False
    return needle in fio_key(text) or needle in fio_key(filename)


def runner_problem() -> str:
    if not (CONFIG_DIR / "runner.mjs").is_file():
        return f"нет runner.mjs в {CONFIG_DIR}"
    if not (CONFIG_DIR / "node_modules" / "@cursor" / "sdk").exists():
        return "нет node_modules конфигурации 2"
    if not shutil.which("node"):
        return "не найден node"
    if not (os.environ.get("CURSOR_API_KEY") or settings.cursor_api_key.strip()):
        return "нет CURSOR_API_KEY"
    return ""


def _tick() -> None:
    _sweep()
    db = SessionLocal()
    try:
        last_plan, docs = _claim(db)
    finally:
        db.close()
    if not docs:
        return
    problem = runner_problem()
    if problem:
        logger.warning("access advisor skipped: %s", problem)
        return
    run_id = str(uuid.uuid4())
    workspace = WORK_ROOT / run_id
    try:
        result = _execute(run_id, workspace, docs, last_plan)
    except Exception as exc:
        logger.exception("access advisor run failed")
        _remember_failure(docs, exc)
        _remember_history(
            run_id=run_id,
            prompt=_task_prompt(workspace, docs, last_plan),
            plan="",
            status="error",
            error=str(exc)[:2000],
            sdk_agent_id="",
            events=[],
        )
        return
    db = SessionLocal()
    try:
        drafts = judge_suggestions(
            docs,
            result["recommendations"],
            lambda fio: sources.resolve_person(db, fio),
            lambda name: sources.resolve_department(db, name),
            lambda phrase: sources.position_holders(db, phrase),
        )
        saved = _store(db, drafts, run_id)
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
        _notify(db, saved)
    finally:
        db.close()
    _remember_history(
        run_id=run_id,
        prompt=str(result.get("prompt") or ""),
        plan=str(result.get("plan") or ""),
        status="finished",
        error="",
        sdk_agent_id=str(result.get("agent_id") or ""),
        events=list(result.get("events") or []),
    )
    logger.info("access advisor run %s: files=%s suggestions=%s", run_id, len(docs), len(saved))


def _claim(db: Session) -> tuple[str, list[DocumentView]]:
    now = datetime.now(timezone.utc)
    state = db.get(ExplorerAccessAgentState, AGENT_KEY)
    if state is None:
        state = ExplorerAccessAgentState(
            id=AGENT_KEY,
            watermark=now - timedelta(minutes=30),
            updated_at=now,
        )
        db.add(state)
        db.flush()
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
        return state.last_plan or "", []
    ids = [row.id for row in rows]
    keys = {
        key.file_id: key
        for key in db.scalars(select(ExplorerFileKey).where(ExplorerFileKey.file_id.in_(ids))).all()
    }
    grants: dict[str, list[GrantView]] = {item_id: [] for item_id in ids}
    for grant in db.scalars(select(ExplorerKeyGrant).where(ExplorerKeyGrant.file_id.in_(ids))).all():
        grants.setdefault(grant.file_id, []).append(
            GrantView(
                kind=grant.grantee_kind,
                grantee_id=grant.grantee_id or "",
                grantee_label=grant.grantee_label or "",
                permission=(grant.permission or "write").strip().lower() or "write",
            )
        )
    docs: list[DocumentView] = []
    for row in rows:
        key = keys.get(row.id)
        text_value = ""
        if key is not None:
            try:
                data = explorer._read_encrypted(explorer._abs(row.rel_path), key.key)
                text_value = sources.extract_text(row.name, data)
            except Exception:
                logger.info("access advisor cannot read %s", row.id, exc_info=True)
                text_value = ""
        docs.append(
            DocumentView(
                file_id=row.id,
                name=row.name,
                owner_user_id=row.owner_user_id,
                owner_fio=row.owner_fio or "",
                mode=key.access_mode if key is not None else "private",
                text=text_value,
                updated_at=row.updated_at,
                grants=grants.get(row.id, []),
            )
        )
    last_plan = state.last_plan or ""
    db.commit()
    return last_plan, docs


def _execute(run_id: str, workspace: Path, docs: list[DocumentView], last_plan: str) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    texts = workspace / "texts"
    texts.mkdir(exist_ok=True)
    manifest = []
    for doc in docs:
        text_file = ""
        if doc.text:
            target = texts / f"{doc.file_id}.txt"
            target.write_text(doc.text, encoding="utf-8")
            text_file = f"texts/{doc.file_id}.txt"
        manifest.append(
            {
                "file_id": doc.file_id,
                "name": doc.name,
                "owner_fio": doc.owner_fio,
                "access_mode": doc.mode,
                "grants": [
                    {"kind": grant.kind, "label": grant.grantee_label, "permission": grant.permission}
                    for grant in doc.grants
                ],
                "readable": bool(doc.text),
                "text_file": text_file,
            }
        )
    (workspace / "recent.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    launcher = _write_launcher(workspace)
    prompt = _task_prompt(workspace, docs, last_plan, launcher)
    model, params = _model()
    store = str(SDK_STORE)
    SDK_STORE.mkdir(parents=True, exist_ok=True)
    plan_events = _turn(
        {
            "type": "run",
            "sessionId": run_id,
            "mode": "plan",
            "prompt": prompt,
            "attachments": [],
            "title": AGENT_TITLE,
            "model": model,
            "modelParams": params,
            "cwd": str(workspace),
            "resumeAgentId": "",
            "python": sys.executable,
            "storeDir": store,
        }
    )
    plan = _plan_text(plan_events) or prompt
    agent_events = _turn(
        {
            "type": "run",
            "sessionId": run_id,
            "mode": "agent",
            "prompt": _run_prompt(workspace, plan),
            "attachments": [],
            "title": AGENT_TITLE,
            "model": model,
            "modelParams": params,
            "cwd": str(workspace),
            "resumeAgentId": _agent_id(plan_events),
            "python": sys.executable,
            "storeDir": store,
        }
    )
    answer = "".join(str(item.get("text") or "") for item in agent_events if item.get("type") == "assistant")
    recommendations = _load_json(workspace / "recommendations.json", answer)
    return {
        "prompt": prompt,
        "plan": plan,
        "agent_id": _agent_id(agent_events) or _agent_id(plan_events),
        "recommendations": recommendations,
        "events": _history_events(prompt, plan_events, agent_events),
    }


def _turn(request: dict[str, Any]) -> list[dict[str, Any]]:
    node = shutil.which("node") or "node"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [node, str(CONFIG_DIR / "runner.mjs")],
        cwd=str(CONFIG_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
        creationflags=flags,
    )
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        out, err = proc.communicate(payload, timeout=TURN_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        _kill(proc)
        raise TimeoutError("ход конфигурации 2 не уложился в 15 минут") from exc
    events = []
    for line in out.decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    done = next((item for item in reversed(events) if item.get("type") == "done"), {})
    if str(done.get("status") or "") != "finished":
        detail = str(done.get("result") or "") or err.decode("utf-8", errors="replace")[-1500:]
        raise RuntimeError(detail or "ход конфигурации 2 не завершился")
    return events


def _store(db: Session, drafts: list[Draft], run_id: str) -> list[Draft]:
    saved: list[Draft] = []
    for draft in drafts:
        exists = db.scalar(
            select(ExplorerAccessSuggestion.id)
            .where(
                ExplorerAccessSuggestion.file_id == draft.file_id,
                ExplorerAccessSuggestion.kind == draft.kind,
                ExplorerAccessSuggestion.grantee_label == draft.grantee_label,
                ExplorerAccessSuggestion.permission == draft.permission,
            )
            .limit(1)
        )
        if exists:
            continue
        db.add(
            ExplorerAccessSuggestion(
                id=uuid.uuid4().hex,
                file_id=draft.file_id,
                file_name=draft.file_name,
                owner_user_id=draft.owner_user_id,
                document_kind=draft.document_kind,
                kind=draft.kind,
                grantee_id=draft.grantee_id,
                grantee_label=draft.grantee_label,
                position=draft.position,
                department=draft.department,
                permission=draft.permission,
                reason=draft.reason,
                quote=draft.quote,
                status="pending",
                run_id=run_id,
            )
        )
        saved.append(draft)
    return saved


def _notify(db: Session, saved: list[Draft]) -> None:
    if not saved:
        return
    from app.schemas.notification import NotificationCreate
    from app.services.notifications.service import create_notification

    names: dict[str, list[str]] = {}
    for draft in saved:
        names.setdefault(draft.owner_user_id, [])
        if draft.file_name not in names[draft.owner_user_id]:
            names[draft.owner_user_id].append(draft.file_name)
    support = db.scalar(select(AppUser.id).where(AppUser.is_support.is_(True)).limit(1))
    for owner_id, files in names.items():
        sender = support or owner_id
        listed = ", ".join(f"«{name}»" for name in files[:6])
        try:
            create_notification(
                db,
                sender_user_id=sender,
                payload=NotificationCreate(
                    recipient_user_id=owner_id,
                    title="База знаний: кому открыть доступ",
                    body=(
                        f"По файлам {listed} есть предложения. "
                        "Они на вкладке «Сегодня»: галочка выдаёт ключ, крестик отклоняет."
                    ),
                ),
            )
        except Exception:
            logger.exception("access advisor notification failed for %s", owner_id)


def _remember_failure(docs: list[DocumentView], exc: Exception) -> None:
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


def _one(
    doc: DocumentView,
    document_kind: str,
    raw: dict[str, Any],
    resolve_person: Callable[[str], dict[str, str] | None],
    resolve_department: Callable[[str], str],
    resolve_position: Callable[[str], list[dict[str, str]]],
) -> list[Draft]:
    kind = str(raw.get("kind") or "").strip().lower()
    quote = " ".join(str(raw.get("quote") or "").split())
    if kind not in {"user", "department", "all", "private"} or not quote_in(quote, doc.text, doc.name):
        return []
    if kind in {"user", "department", "all"}:
        permission = str(raw.get("permission") or "").strip().lower()
        if permission not in {"read", "write"}:
            return []
    else:
        permission = ""
    if kind == "user":
        return _users_from_process(doc, document_kind, raw, quote, permission, resolve_person, resolve_position)
    if kind == "department":
        name = resolve_department(str(raw.get("department") or ""))
        if not name or not department_mentioned(name, doc.text, doc.name) or not department_mentioned(name, quote, ""):
            return []
        if _covered(doc, kind="department", user_id="", fio="", department=name, permission=permission):
            return []
        return [
            Draft(
                file_id=doc.file_id,
                file_name=doc.name,
                owner_user_id=doc.owner_user_id,
                document_kind=document_kind,
                kind="department",
                grantee_id="",
                grantee_label=name,
                position="весь отдел",
                department=name,
                permission=permission,
                quote=quote[:1000],
                reason=f"В документе прямо назван отдел «{name}». Предлагаю {PERM_RU[permission]} всему отделу. «{quote[:240]}»",
            )
        ]
    why = " ".join(str(raw.get("why") or "").split())
    if len(why) < 40:
        return []
    if kind == "all":
        if _covered(doc, kind="all", user_id="", fio="", department="", permission=permission):
            return []
        return [
            Draft(
                file_id=doc.file_id,
                file_name=doc.name,
                owner_user_id=doc.owner_user_id,
                document_kind=document_kind,
                kind="all",
                grantee_id="",
                grantee_label="Все сотрудники",
                position="открыть всем",
                department="",
                permission=permission,
                quote=quote[:1000],
                reason=why,
            )
        ]
    if doc.mode == "private" and not doc.grants:
        return []
    return [
        Draft(
            file_id=doc.file_id,
            file_name=doc.name,
            owner_user_id=doc.owner_user_id,
            document_kind=document_kind,
            kind="private",
            grantee_id="",
            grantee_label="Сделать приватным",
            position="закрыть доступ остальным",
            department="",
            permission="",
            quote=quote[:1000],
            reason=why,
        )
    ]


def _users_from_process(
    doc: DocumentView,
    document_kind: str,
    raw: dict[str, Any],
    quote: str,
    permission: str,
    resolve_person: Callable[[str], dict[str, str] | None],
    resolve_position: Callable[[str], list[dict[str, str]]],
) -> list[Draft]:
    phrase = " ".join(str(raw.get("position") or "").split())
    people: list[dict[str, str]] = []
    named = resolve_person(" ".join(str(raw.get("fio") or "").split()))
    if named is not None:
        people.append(named)
    if position_in_text(phrase, doc.text, doc.name) and position_in_text(phrase, quote, ""):
        for holder in resolve_position(phrase):
            if position_matches(holder.get("position") or "", phrase) and not any(
                fio_key(holder.get("fio") or "") == fio_key(item.get("fio") or "") for item in people
            ):
                people.append(holder)
    drafts: list[Draft] = []
    evidence = fio_key(quote)
    for person in people:
        fio = person.get("fio") or ""
        if not fio or not _linked_to_file(person, phrase, doc):
            continue
        surname = fio_key(fio).split()[0]
        if surname not in evidence and fio_key(phrase) not in evidence and fio_key(person.get("position") or "") not in evidence:
            continue
        if _covered(doc, kind="user", user_id=person.get("user_id") or "", fio=fio, department=person.get("department") or "", permission=permission):
            continue
        place = person.get("position") or phrase or "должность не указана"
        drafts.append(
            Draft(
                file_id=doc.file_id,
                file_name=doc.name,
                owner_user_id=doc.owner_user_id,
                document_kind=document_kind,
                kind="user",
                grantee_id=person.get("user_id") or "",
                grantee_label=fio,
                position=person.get("position") or phrase,
                department=person.get("department") or "",
                permission=permission,
                quote=quote[:1000],
                reason=_why_included(raw, person, phrase, quote, permission),
            )
        )
    return drafts


def _why_included(raw: dict[str, Any], person: dict[str, str], phrase: str, quote: str, permission: str) -> str:
    """Описание агента, почему человек включён. Если агент его не дал — собираем по роли в цитате."""
    fio = person.get("fio") or ""
    place = person.get("position") or phrase or "должность не указана"
    written = " ".join(str(raw.get("why") or "").split())
    blob = fio_key(written)
    surname = fio_key(fio).split()[:1]
    mentions = (surname and surname[0] in blob) or (phrase and fio_key(phrase) in blob) or (fio_key(place) in blob)
    if len(written) >= 40 and mentions:
        return written[:1000]
    named = bool(surname) and _surname_in_text(quote, surname[0])
    low = fio_key(quote)
    if "внесение изменений" in low or "вносить изменения" in low:
        role = f"инструкция поручает должности «{phrase or place}» вносить в неё изменения"
    elif "разработал" in low:
        role = "в листе согласования указан как разработчик документа"
    elif "проверил" in low:
        role = "в листе согласования проверял документ"
    elif "согласовал" in low:
        role = f"согласовал документ как {phrase or place}"
    elif "утверждаю" in low:
        role = "утверждает документ"
    else:
        role = "участвует в процессе, который описывает документ"
    if named:
        head = f"{fio}, {place}: {role}."
    else:
        head = f"В тексте названа должность «{phrase or place}», её занимает {fio}. {role[:1].upper() + role[1:]}."
    return f"{head} Поэтому предлагается {PERM_RU[permission]}."


def _surname_in_text(text: str, surname: str) -> bool:
    return any(_inflected(word, surname) for word in re.findall(r"\w+", fio_key(text)))


def _linked_to_file(person: dict[str, str], phrase: str, doc: DocumentView) -> bool:
    fio = person.get("fio") or ""
    if person_mentioned(fio, doc.text, doc.name):
        return True
    if phrase and position_in_text(phrase, doc.text, doc.name) and position_matches(person.get("position") or "", phrase):
        return True
    org_position = person.get("position") or ""
    surname = fio_key(fio).split()[:1]
    if surname and _surname_in(doc, surname[0]) and position_in_text(org_position, doc.text, doc.name):
        return True
    return False


def _surname_in(doc: DocumentView, surname: str) -> bool:
    words = re.findall(r"\w+", fio_key(f"{doc.name}\n{doc.text}"))
    return any(_inflected(word, surname) for word in words)


def _covered(doc: DocumentView, *, kind: str, user_id: str, fio: str, department: str, permission: str) -> bool:
    if kind == "private":
        return doc.mode == "private" and not doc.grants
    if kind == "user" and fio_key(fio) and fio_key(fio) == fio_key(doc.owner_fio):
        return True
    need = 2 if permission == "write" else 1
    for grant in doc.grants:
        have = 2 if grant.permission == "write" else 1 if grant.permission == "read" else 0
        if have < need:
            continue
        if grant.kind == "all":
            return True
        if kind == "user" and grant.kind == "user" and (
            (user_id and grant.grantee_id == user_id) or fio_key(grant.grantee_label) == fio_key(fio)
        ):
            return True
        if kind == "user" and grant.kind == "department" and fio_key(grant.grantee_id) == fio_key(department):
            return True
        if kind == "department" and grant.kind == "department" and fio_key(grant.grantee_id or grant.grantee_label) == fio_key(department):
            return True
        if kind == "all" and grant.kind == "all":
            return True
    return False


def _upsert_grant(
    db: Session,
    file_id: str,
    kind: str,
    grantee_id: str,
    label: str,
    permission: str,
    department: str,
) -> None:
    rows = db.scalars(select(ExplorerKeyGrant).where(ExplorerKeyGrant.file_id == file_id)).all()
    for grant in rows:
        same_user = kind == "user" and grant.grantee_kind == "user" and (
            (grantee_id and grant.grantee_id == grantee_id) or fio_key(grant.grantee_label) == fio_key(label)
        )
        same_dept = kind == "department" and grant.grantee_kind == "department" and fio_key(grant.grantee_id or grant.grantee_label) == fio_key(label)
        same_all = kind == "all" and grant.grantee_kind == "all"
        if not (same_user or same_dept or same_all):
            continue
        if permission == "write" and (grant.permission or "") != "write":
            grant.permission = "write"
        return
    db.add(
        ExplorerKeyGrant(
            id=uuid.uuid4().hex,
            file_id=file_id,
            grantee_kind=kind,
            grantee_id=grantee_id,
            grantee_label=label,
            permission=permission,
            source_department=department if kind == "user" else "",
        )
    )


def _task_prompt(workspace: Path, docs: list[DocumentView], last_plan: str, launcher: str = "") -> str:
    files = "\n".join(
        f"- {doc.file_id} | {doc.name} | сейчас: {doc.mode} | текст: {'texts/' + doc.file_id + '.txt' if doc.text else 'не читается, рекомендацию не давать'}"
        for doc in docs
    )
    previous = (
        "\nПрошлый план не переноси: должность участника процесса важнее полного имени. "
        "Инициалы при фамилии достаточны, поиск по должности обязателен.\n"
        if last_plan.strip()
        else ""
    )
    tool = launcher or "lookup.cmd"
    return f"""Ты серверный агент доступа к базе знаний. Люди тебя не видят и ответить не могут. Ничего не спрашивай.
Изменённые файлы уже лежат в `{workspace}`. Список — recent.json, полный текст понятного документа — texts/<file_id>.txt.

{files}
{previous}
Откуда брать людей, должности и процессы. Всех подряд не выгружай:
1. Должность — `{tool} position "должность из документа"`. Это сотрудники с этой должностью в org_members. Если ответ too_many, должность слишком общая: возьми формулировку из текста целиком, например «главный конструктор», а не «директор».
2. Фамилия — `{tool} people "фамилия"`, когда нужно подтвердить человека. Не больше 15 строк.
3. Отдел — `{tool} department "название из документа"`.
4. Чем отдел занимается — один файл из `{sources.NORMS_DIR}`, команда `{tool} norm "название отдела"`. Всю папку не обходи.
Процесс — это порядок, который описывает сам документ: его назначение и действия участников. Другого справочника процессов нет. Участник процесса — человек, чья должность в этом порядке названа, или кто стоит в листе разработки, проверки, согласования и утверждения.
Не читай .env, не ходи в 1С, почту и чужие папки, не меняй файлы базы и доступы. Единственный записываемый результат — recommendations.json на втором шаге.

Связь с файлом есть, и рекомендация обязательна, если выполнено хотя бы одно:
- в тексте названа должность участника процесса («главный конструктор», «специалист по процессному управлению»);
- названы фамилия и имя или фамилия с инициалами («И.В. Хозуян»).
Должность важнее полного имени: «Главный конструктор И.В. Хозуян» — это Хозуян, его нужно найти командой position и включить в рекомендации.
Цитата quote — непрерывный фрагмент текста, где есть эта должность или фамилия.
«Разработал», «проверил», «согласовал», «утверждаю», «ознакомить», «исполнить», «внести изменения» означают, что этот участник связан с файлом. Чтение — участвует в процессе. Запись — ему поручено менять сам документ.
Не оставляй files пустым, если такая должность или фамилия есть и lookup нашёл сотрудника.
Не предлагай владельца и тех, у кого доступ уже есть (grants в recent.json).
Не открывай файл всем только потому, что «все сотрудники должны соблюдать» инструкцию: это не список получателей.
Сходство темы без названной должности, фамилии или отдела — не связь, рекомендации нет.
Весь отдел — только если отдел назван своим именем, а не должность одного человека.

На первом шаге только план: для каждой должности участника вызови position. На втором запиши `{workspace / "recommendations.json"}`:
{{"files":[{{"file_id":"...","document_kind":"инструкция","suggestions":[{{"kind":"user","fio":"Фамилия Имя Отчество","position":"должность из документа","permission":"read","quote":"фраза из файла","why":"Почему именно этот человек: какая у него роль в процессе документа, одна-две фразы"}}]}}]}}
У каждого человека своё why. Не копируй одну фразу на всех. Напиши, что он делает с этим файлом: разработал, проверил, согласовал, утвердил или по должности вносит изменения.
"""


def _run_prompt(workspace: Path, plan: str) -> str:
    return (
        "Выполни план. Человека нет, ничего не спрашивай и ничего, кроме recommendations.json, не меняй. "
        "Доступ, 1С и почту не трогай. Должность участника процесса в тексте — уже связь: найди сотрудника "
        "и включи его в рекомендации, даже если в документе только инициалы.\n"
        f"Запиши итог в `{workspace / 'recommendations.json'}`.\n\n"
        f"{plan}"
    )


def _write_launcher(workspace: Path) -> str:
    python = sys.executable
    if sys.platform == "win32":
        path = workspace / "lookup.cmd"
        path.write_text(
            f'@echo off\r\nset "PYTHONPATH={BACKEND_DIR}"\r\n"{python}" -m app.services.server_agents %*\r\n',
            encoding="utf-8",
        )
        return str(path)
    path = workspace / "lookup.sh"
    path.write_text(
        f'#!/bin/sh\nPYTHONPATH="{BACKEND_DIR}" exec "{python}" -m app.services.server_agents "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def _model() -> tuple[str, list[dict[str, str]]]:
    try:
        data = json.loads((CONFIG_DIR / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "grok-4.7", [{"id": "reasoning_effort", "value": "xhigh"}, {"id": "fast", "value": "true"}]
    params = data.get("model_params") if isinstance(data.get("model_params"), list) else []
    clean = [
        {"id": str(item.get("id") or ""), "value": str(item.get("value") or "")}
        for item in params
        if isinstance(item, dict) and item.get("id") and item.get("value")
    ]
    return str(data.get("model") or "grok-4.7"), clean


def _env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if isinstance(value, str)}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["TURBOTESTER_HEADLESS"] = "1"
    env.pop("TURBOTESTER_API_URL", None)
    env.pop("TURBOTESTER_SESSION_ID", None)
    if not env.get("CURSOR_API_KEY") and settings.cursor_api_key:
        env["CURSOR_API_KEY"] = settings.cursor_api_key
    return env


def _plan_text(events: list[dict[str, Any]]) -> str:
    for item in reversed(events):
        if item.get("type") == "plan" and str(item.get("markdown") or "").strip():
            return str(item["markdown"]).strip()
    return ""


def _agent_id(events: list[dict[str, Any]]) -> str:
    for item in reversed(events):
        if item.get("type") == "done" and item.get("agentId"):
            return str(item["agentId"])
    return ""


def _load_json(path: Path, fallback: str) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8") if path.is_file() else fallback
    parsed = _parse_object(raw)
    if parsed:
        return parsed
    return _parse_object(fallback)


def _parse_object(raw: str) -> dict[str, Any]:
    text_value = (raw or "").strip()
    if text_value.startswith("```"):
        text_value = re.sub(r"^```(?:json)?\s*", "", text_value)
        text_value = re.sub(r"\s*```$", "", text_value)
    try:
        data = json.loads(text_value)
    except json.JSONDecodeError:
        start, end = text_value.find("{"), text_value.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(text_value[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


HISTORY_ROWS_PER_TURN = 120
_IMAGE_DATA = re.compile(r'"imageData"\s*:\s*"[^"]*"?')


def _history_events(prompt: str, plan_events: list[dict[str, Any]], agent_events: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = [{"turn": "0", "type": "user", "body": prompt[:8000], "name": "", "status": "", "args": "", "result": ""}]
    for turn, events in (("0", plan_events), ("1", agent_events)):
        turn_limit = len(rows) + HISTORY_ROWS_PER_TURN
        assistant: list[str] = []
        thinking: list[str] = []

        def flush() -> None:
            if assistant:
                rows.append({"turn": turn, "type": "assistant", "body": "".join(assistant)[:8000], "name": "", "status": "", "args": "", "result": ""})
                assistant.clear()
            if thinking:
                rows.append({"turn": turn, "type": "thinking", "body": "".join(thinking)[:4000], "name": "", "status": "", "args": "", "result": ""})
                thinking.clear()

        for item in events:
            kind = item.get("type")
            if kind == "assistant" and item.get("text"):
                assistant.append(str(item["text"]))
            elif kind == "thinking" and item.get("text"):
                thinking.append(str(item["text"]))
            elif kind == "tool_call" and item.get("status") not in {None, "running"}:
                flush()
                rows.append(
                    {
                        "turn": turn,
                        "type": "tool",
                        "body": "",
                        "name": str(item.get("name") or ""),
                        "status": str(item.get("status") or ""),
                        "args": str(item.get("args") or "")[:2000],
                        "result": _IMAGE_DATA.sub('"imageData":"…"', str(item.get("result") or ""))[:2000],
                    }
                )
            if len(rows) >= turn_limit:
                break
        flush()
    return rows


def _remember_history(
    *,
    run_id: str,
    prompt: str,
    plan: str,
    status: str,
    error: str,
    sdk_agent_id: str,
    events: list[dict[str, str]],
    agent_id: str = "server-explorer-access",
    agent_title: str = AGENT_TITLE,
) -> None:
    try:
        _write_history(
            run_id=run_id,
            prompt=prompt[:100_000],
            plan=plan[:50_000],
            status=status,
            error=error[:2000],
            sdk_agent_id=sdk_agent_id,
            events=events,
            agent_id=agent_id,
            agent_title=agent_title,
        )
    except Exception:
        logger.exception("%s history was not saved", agent_id)


def _write_history(
    *,
    run_id: str,
    prompt: str,
    plan: str,
    status: str,
    error: str,
    sdk_agent_id: str,
    events: list[dict[str, str]],
    agent_id: str,
    agent_title: str,
) -> None:
    now = datetime.now(timezone.utc)
    manifest = {}
    config_path = CONFIG_DIR / "config.json"
    if config_path.is_file():
        try:
            manifest = json.loads(config_path.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}
    with engine.begin() as conn:
        for statement in _HISTORY_DDL:
            conn.execute(text(statement))
        conn.execute(
            text(
                """
                INSERT INTO turbotest.runs (
                    id, config_id, config_title, source, agent_id, agent_title, prompt,
                    status, error, sdk_agent_id, turns, model, entry, config_manifest,
                    author, author_host, plan_turn, plan, machine,
                    created_at, updated_at, finished_at
                ) VALUES (
                    CAST(:id AS uuid), :config_id, :config_title, 'custom', :agent_id, :agent_title, :prompt,
                    :status, :error, :sdk_agent_id, :turns, :model, :entry, :config_manifest,
                    :author, :author_host, 0, :plan, :machine,
                    :created_at, :updated_at, :finished_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    error = EXCLUDED.error,
                    sdk_agent_id = EXCLUDED.sdk_agent_id,
                    turns = EXCLUDED.turns,
                    plan = EXCLUDED.plan,
                    updated_at = EXCLUDED.updated_at,
                    finished_at = EXCLUDED.finished_at
                """
            ).bindparams(
                bindparam_entry(),
                bindparam_manifest(),
                bindparam_machine(),
            ),
            {
                "id": run_id,
                "config_id": CONFIG_ID,
                "config_title": "Конфигурация 2",
                "agent_id": agent_id,
                "agent_title": agent_title,
                "prompt": prompt,
                "status": status,
                "error": error,
                "sdk_agent_id": sdk_agent_id,
                "turns": 2,
                "model": _model()[0],
                "entry": ["node", "runner.mjs"],
                "config_manifest": manifest,
                "author": "сервер",
                "author_host": socket.gethostname(),
                "plan": plan,
                "machine": {"where": "server"},
                "created_at": now,
                "updated_at": now,
                "finished_at": now,
            },
        )
        for seq, item in enumerate(events, start=1):
            conn.execute(
                text(
                    """
                    INSERT INTO turbotest.run_events (
                        run_id, seq, rev, turn, type, body, name, status, call_id, args, result,
                        args_chars, result_chars, label, attachments, parent
                    ) VALUES (
                        CAST(:run_id AS uuid), :seq, :seq, :turn, :type, :body, :name, :status, '',
                        :args, :result, :args_chars, :result_chars, '', :attachments, ''
                    )
                    ON CONFLICT (run_id, seq) DO NOTHING
                    """
                ).bindparams(bindparam_attachments()),
                {
                    "run_id": run_id,
                    "seq": seq,
                    "turn": int(item.get("turn") or 0),
                    "type": item.get("type") or "status",
                    "body": item.get("body") or "",
                    "name": item.get("name") or "",
                    "status": item.get("status") or "",
                    "args": item.get("args") or "",
                    "result": item.get("result") or "",
                    "args_chars": len(item.get("args") or ""),
                    "result_chars": len(item.get("result") or ""),
                    "attachments": [],
                },
            )


def bindparam_entry():
    from sqlalchemy import bindparam

    return bindparam("entry", type_=JSONB())


def bindparam_manifest():
    from sqlalchemy import bindparam

    return bindparam("config_manifest", type_=JSONB())


def bindparam_machine():
    from sqlalchemy import bindparam

    return bindparam("machine", type_=JSONB())


def bindparam_attachments():
    from sqlalchemy import bindparam

    return bindparam("attachments", type_=JSONB())


_HISTORY_DDL = (
    "CREATE SCHEMA IF NOT EXISTS turbotest",
    """
    CREATE TABLE IF NOT EXISTS turbotest.runs (
        id uuid PRIMARY KEY,
        config_id text NOT NULL,
        config_title text NOT NULL,
        source text NOT NULL,
        agent_id text NOT NULL,
        agent_title text NOT NULL,
        prompt text NOT NULL,
        status text NOT NULL,
        error text NOT NULL DEFAULT '',
        sdk_agent_id text NOT NULL DEFAULT '',
        turns integer NOT NULL DEFAULT 0,
        model text NOT NULL DEFAULT '',
        entry jsonb NOT NULL DEFAULT '[]',
        config_manifest jsonb NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        finished_at timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS turbotest.run_events (
        run_id uuid NOT NULL REFERENCES turbotest.runs (id) ON DELETE CASCADE,
        seq integer NOT NULL,
        rev integer NOT NULL,
        turn integer NOT NULL,
        type text NOT NULL,
        body text NOT NULL DEFAULT '',
        name text NOT NULL DEFAULT '',
        status text NOT NULL DEFAULT '',
        call_id text NOT NULL DEFAULT '',
        args text NOT NULL DEFAULT '',
        result text NOT NULL DEFAULT '',
        args_chars integer NOT NULL DEFAULT 0,
        result_chars integer NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, seq)
    )
    """,
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS author text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS author_host text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS plan_turn integer NOT NULL DEFAULT 0",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS plan text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS machine jsonb NOT NULL DEFAULT '{}'",
    "ALTER TABLE turbotest.run_events ADD COLUMN IF NOT EXISTS label text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.run_events ADD COLUMN IF NOT EXISTS attachments jsonb NOT NULL DEFAULT '[]'",
    "ALTER TABLE turbotest.run_events ADD COLUMN IF NOT EXISTS parent text NOT NULL DEFAULT ''",
)


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


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
            timeout=20,
        )
    if proc.poll() is None:
        proc.kill()

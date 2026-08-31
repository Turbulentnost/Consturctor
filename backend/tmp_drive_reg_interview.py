from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
BACKEND = ROOT / "backend"
sys.path.insert(0, str(DESKTOP))

from dotenv import load_dotenv
import jwt
from datetime import UTC, datetime, timedelta
from uuid import uuid4

load_dotenv(DESKTOP / ".env")
load_dotenv(BACKEND / ".env")

from app.sdk_agent.bridge import CursorSdkBridge, CursorSdkError
from app.sdk_agent.prompt import build_regulation_sdk_prompt
from sqlalchemy import create_engine, text

import os

DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://constructor:constructor@127.0.0.1:5435/constructor")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-constructor-secret-change-me")

API = "http://127.0.0.1:7812"
DRAFT_ID = "reg-create-6dd4b8cd6e82"
MAX_TURNS = 40


def log(msg: str) -> None:
    print(msg, flush=True)


def interview_json_answer(raw: str) -> str:
    decoder = json.JSONDecoder()
    text = raw or ""
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        status = str(obj.get("status") or "") if isinstance(obj, dict) else ""
        if status in {"need_more", "ready"}:
            return json.dumps(obj, ensure_ascii=False)
        index = end
    return ""


def token_for_draft() -> str:
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                select d.user_id, u.fio, u.department, u.position
                from regulation_creation_drafts d
                join users u on u.id = d.user_id
                where d.id = :id
                """
            ),
            {"id": DRAFT_ID},
        ).mappings().one()
    now = datetime.now(UTC)
    sid = ""
    try:
        import redis

        client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://127.0.0.1:6382/0"),
            decode_responses=True,
        )
        sid = str(client.get(f"constructor:session:{row['user_id']}") or "")
        if not sid:
            sid = str(uuid4())
            client.set(f"constructor:session:{row['user_id']}", sid)
    except Exception as exc:  # noqa: BLE001
        log("redis session set failed: " + str(exc))
        sid = sid or str(uuid4())
    return jwt.encode(
        {
            "sub": row["user_id"],
            "fio": row["fio"] or "",
            "department": row["department"] or "",
            "position": row["position"] or "",
            "sid": sid,
            "iat": now,
            "exp": now + timedelta(minutes=480),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def api_request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code} {detail}") from exc
    return json.loads(raw) if raw else {}


def prepare_workspace(run_cwd: Path, rules: str, interview: dict) -> None:
    run_cwd.mkdir(parents=True, exist_ok=True)
    (run_cwd / "AGENTS.md").write_text(rules or "Answer in JSON.", encoding="utf-8")
    (run_cwd / "interview.json").write_text(
        json.dumps(interview, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    materials = run_cwd / "materials"
    materials.mkdir(parents=True, exist_ok=True)
    for item in interview.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "file.txt")
        text_value = str(item.get("text") or "")
        if not text_value:
            continue
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in Path(name).stem)[:80]
        (materials / f"{safe}.txt").write_text(text_value, encoding="utf-8")


def choose_answer(question: str, quicks: list[str]) -> str:
    q = (question or "").lower()
    if any(key in q for key in ("относ", "принадлеж", "ваша должност", "к должност")):
        if any(key in q for key in ("делопроизвод", "архивариус", "специалист по смк")):
            return "Нет, это чужая роль. Моя должность - Помощник Председателя совета директоров."
        return (
            "Да, это относится к должности Помощник Председателя совета директоров "
            "по регламенту действий должности."
        )
    if any(key in q for key in ("инструмент", "систем", "где выполня", "в какой")):
        if any("1c" in a.lower() or "1с" in a.lower() for a in quicks) and any(
            key in q for key in ("поруч", "задач", "протокол", "erp", "учет")
        ):
            return next(a for a in quicks if "1c" in a.lower() or "1с" in a.lower())
        if any("outlook" in a.lower() for a in quicks) and any(
            key in q for key in ("совеща", "календар", "встреч", "письм")
        ):
            return next(a for a in quicks if "outlook" in a.lower())
        if quicks:
            return quicks[0]
        return "1C ERP для учета поручений и протоколов, Outlook для календаря совещаний."
    if any(key in q for key in ("периодич", "как часто", "когда", "с какой периодич")):
        if any(key in q for key in ("поруч", "исполнен", "контрол")):
            return "Ежедневно в 1C ERP: проверяю сроки, направляю напоминания исполнителям и докладываю ПСД о просрочках."
        if quicks:
            return quicks[0]
        return "По факту поступления поручения ПСД и по датам из утвержденного сводного плана."
    if any(key in q for key in ("триггер", "после чего", "событ", "запуска")):
        if quicks:
            return quicks[0]
        return "Поступило поручение ПСД либо наступила дата совещания из сводного плана."
    if any(key in q for key in ("что делает", "как выглядит", "действи")):
        if quicks:
            return quicks[0]
        return (
            "Фиксирую поручение в 1C ERP, контролирую срок, собираю материалы "
            "и докладываю ПСД о статусе."
        )
    if quicks:
        return quicks[0]
    return (
        "Да, выполняю это как Помощник ПСД. Учет в 1C ERP, календарь в Outlook. "
        "Триггер - поручение ПСД или дата из сводного плана."
    )


def last_assistant(session: dict) -> dict:
    for item in reversed(session.get("messages") or []):
        if item.get("role") == "assistant":
            return item
    return {}


def run_sdk(turn: dict) -> str:
    bridge = CursorSdkBridge()
    workspace_id = f"reg-create-{DRAFT_ID}"
    run_cwd = Path(bridge.workspace_cwd(workspace_id))
    prepare_workspace(
        run_cwd,
        str(turn.get("sdkRules") or ""),
        turn.get("interview") if isinstance(turn.get("interview"), dict) else {},
    )
    try:
        result = bridge.run(
            prompt=build_regulation_sdk_prompt(str(turn.get("sdkPrompt") or "")),
            workflow_id=workspace_id,
            cwd=str(run_cwd),
            mode="interview",
            tools=[],
            resume_agent_id=str(turn.get("sdkAgentId") or "").strip(),
            confirm_writes=False,
        )
        answer = str(result.get("answer") or "").strip()
    except CursorSdkError as exc:
        answer = interview_json_answer(str(exc))
        if not answer:
            raise
    recovered = interview_json_answer(answer)
    if recovered:
        answer = recovered
    if not answer:
        raise RuntimeError("empty SDK interview answer")
    return answer


def main() -> None:
    token = token_for_draft()
    session = api_request("GET", f"/api/v1/regulation-creation/sessions/{DRAFT_ID}", token)
    log(f"session status={session.get('status')} messages={len(session.get('messages') or [])}")

    for step in range(1, MAX_TURNS + 1):
        session = api_request("GET", f"/api/v1/regulation-creation/sessions/{DRAFT_ID}", token)
        if session.get("status") == "finalized" or session.get("resultDocumentPath"):
            log(f"done status={session.get('status')} path={session.get('resultDocumentPath')}")
            return
        msgs = session.get("messages") or []
        last_msg = msgs[-1] if msgs else {}
        if last_msg.get("role") == "assistant":
            last = last_assistant(session)
            question = str(last.get("content") or "")
            structured = last.get("structured") or {}
            quicks = []
            if isinstance(structured, dict) and isinstance(structured.get("quickAnswers"), list):
                quicks = [str(x) for x in structured["quickAnswers"] if str(x).strip()]
            answer_text = choose_answer(question, quicks)
            log(f"Q{step}: {question[:220]}")
            log(f"A{step}: {answer_text}")
            api_request(
                "POST",
                f"/api/v1/regulation-creation/sessions/{DRAFT_ID}/turns",
                token,
                {"message": answer_text},
            )
        turn = api_request("GET", f"/api/v1/regulation-creation/sessions/{DRAFT_ID}/turn", token)
        log(f"SDK turn {step} prompt_len={len(str(turn.get('sdkPrompt') or ''))}")
        started = time.time()
        raw = run_sdk(turn)
        parsed = json.loads(raw)
        log(f"SDK {int(time.time() - started)}s status={parsed.get('status')} msg={(parsed.get('message') or '')[:180]}")
        session = api_request(
            "POST",
            f"/api/v1/regulation-creation/sessions/{DRAFT_ID}/apply",
            token,
            {
                "answer": raw,
                "sdkAgentId": str(turn.get("sdkAgentId") or ""),
                "forceCreate": bool(turn.get("forceCreate")),
            },
        )
        log(f"applied status={session.get('status')} messages={len(session.get('messages') or [])}")
        if parsed.get("status") == "ready" or session.get("status") == "finalized":
            log(f"ready path={session.get('resultDocumentPath')}")
            return
    raise RuntimeError("interview did not finish in time")


if __name__ == "__main__":
    main()

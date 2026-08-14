"""
Seed a ready agent draft for a user from STO-34-238 testdata processes.

Creates:
  regulations + role_match_runs + agent_drafts (status=ready, agentSuggestions)

Usage (from backend/):
  python scripts/seed_sto_agent_draft.py
  python scripts/seed_sto_agent_draft.py --fio "Комарькова Анастасия Эдуардовна"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal, init_db
from app.models.regulation import AgentDraft, RegulationDocument, RoleMatchRun
from app.models.user import AppUser
from app.schemas.regulation import (
    FunctionActor,
    MatchEvidence,
    RegulationFragment,
    RegulationParseResult,
    RoleFunction,
    RoleMatchResult,
    RoleProfile,
)

TESTDATA = BACKEND_ROOT / "storage" / "testdata"
PROCESSES_PATH = TESTDATA / "STO-34-238_processes.txt"
PASSPORT_INPUTS_PATH = TESTDATA / "STO-34-238_passport_inputs.json"
PDF_PATH = TESTDATA / "STO-34-238.pdf"

DEFAULT_FIO = "Комарькова Анастасия Эдуардовна"


def _parse_processes(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    cards: list[dict] = []
    current: dict | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current, body
        if not current:
            return
        explanation = "\n".join(body).strip()
        current["explanation"] = explanation
        cards.append(current)
        current = None
        body = []

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("ИИ-агент:"):
            flush()
            title = line.strip()
            bp = title.removeprefix("ИИ-агент:").strip()
            current = {
                "title": title,
                "bp_name": bp,
                "role": "",
                "conditions": "",
                "recipient": "",
                "explanation": "",
            }
            body = []
            continue
        if current is None:
            continue
        if line.startswith("Роль:"):
            current["role"] = line.removeprefix("Роль:").strip()
        elif line.startswith("Условия:"):
            current["conditions"] = line.removeprefix("Условия:").strip()
        elif line.startswith("Получатель/участник:"):
            current["recipient"] = line.removeprefix("Получатель/участник:").strip()
        else:
            body.append(line.strip())
    flush()
    return cards


def _load_excerpts(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for case in payload.get("cases") or []:
        bp = str(case.get("bp_name") or "").strip().casefold()
        excerpt = str(case.get("excerpt") or "").strip()
        if bp and excerpt:
            out[bp] = excerpt
    return out


def _split_action_object(bp_name: str) -> tuple[str, str]:
    words = bp_name.split()
    if len(words) >= 2:
        return words[0], " ".join(words[1:])
    return bp_name, ""


def _description(card: dict) -> str:
    parts = []
    if card.get("role"):
        parts.append(f"Роль: {card['role']}")
    if card.get("conditions"):
        parts.append(f"Условия: {card['conditions']}")
    if card.get("recipient"):
        parts.append(f"Получатель/участник: {card['recipient']}")
    if card.get("explanation"):
        parts.append(card["explanation"])
    return "\n".join(parts)


def seed(*, fio: str, replace_existing: bool) -> None:
    init_db()
    cards = _parse_processes(PROCESSES_PATH)
    if not cards:
        raise SystemExit(f"No processes parsed from {PROCESSES_PATH}")
    excerpts = _load_excerpts(PASSPORT_INPUTS_PATH)

    db = SessionLocal()
    try:
        user = db.query(AppUser).filter(AppUser.fio == fio).first()
        if user is None:
            user = (
                db.query(AppUser)
                .filter(AppUser.fio.ilike(f"%{fio.split()[0]}%"))
                .first()
            )
        if user is None:
            raise SystemExit(f"User not found: {fio}")

        marker = "STO-34-238-seed"
        if replace_existing:
            old_drafts = (
                db.query(AgentDraft)
                .filter(
                    AgentDraft.user_id == user.id,
                    AgentDraft.title.ilike("%СТО-34-238%"),
                )
                .all()
            )
            for draft in old_drafts:
                db.delete(draft)
            db.commit()

        regulation_id = f"reg-{uuid4().hex[:12]}"
        role_run_id = f"role-match-{uuid4().hex[:12]}"
        draft_id = f"agent-draft-{uuid4().hex[:12]}"

        from app.config import settings

        storage_dir = settings.regulation_storage_dir / regulation_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        file_name = "СТО-34-238 Организация работ в отделе управление делами.pdf"
        if PDF_PATH.is_file():
            storage_path = storage_dir / PDF_PATH.name
            shutil.copy2(PDF_PATH, storage_path)
        else:
            storage_path = storage_dir / "STO-34-238.txt"
            storage_path.write_text(PROCESSES_PATH.read_text(encoding="utf-8"), encoding="utf-8")

        fragments: list[RegulationFragment] = []
        functions: list[RoleFunction] = []
        suggestions: list[dict] = []

        for index, card in enumerate(cards, start=1):
            frag_id = f"frag-sto-{index:03d}"
            fn_id = f"fn-sto-{index:03d}"
            excerpt = excerpts.get(card["bp_name"].casefold()) or "\n".join(
                part
                for part in [
                    card["title"],
                    f"Роль: {card['role']}" if card["role"] else "",
                    f"Условия: {card['conditions']}" if card["conditions"] else "",
                    f"Получатель/участник: {card['recipient']}" if card["recipient"] else "",
                    card["explanation"],
                ]
                if part
            )
            fragments.append(
                RegulationFragment(
                    fragmentId=frag_id,
                    page=1,
                    section="СТО-34-238",
                    sectionPath=["СТО-34-238"],
                    kind="text",
                    blockType="paragraph",
                    text=excerpt[:3500],
                    contentHash=f"sto-{index:03d}",
                )
            )
            action, obj = _split_action_object(card["bp_name"])
            conditions = [
                part.strip()
                for part in re.split(r"[;]", card.get("conditions") or "")
                if part.strip()
            ]
            functions.append(
                RoleFunction(
                    functionId=fn_id,
                    targetBlockId=frag_id,
                    isFunction=True,
                    actor=FunctionActor(
                        text=card.get("role") or "",
                        canonicalPosition=card.get("role") or "",
                        sourceBlockId=frag_id,
                    ),
                    action=action,
                    object=obj,
                    recipient=card.get("recipient") or "",
                    conditions=conditions,
                    evidence=[
                        MatchEvidence(fragmentId=frag_id, quote=excerpt[:400]),
                    ],
                    explanation=card.get("explanation") or card["bp_name"],
                    confidence=0.95,
                    requiresUserConfirmation=False,
                )
            )
            suggestions.append(
                {
                    "agentId": f"agent-suggestion-{index:03d}",
                    "title": card["title"],
                    "description": _description(card),
                    "regulationId": regulation_id,
                    "roleMatchRunId": role_run_id,
                    "functionId": fn_id,
                    "sourceBlockId": frag_id,
                }
            )

        now = datetime.now(timezone.utc)
        parse_result = RegulationParseResult(
            regulationId=regulation_id,
            fileName=file_name,
            pageCount=1,
            tableCount=0,
            sectionCount=1,
            recognitionQuality=1.0,
            isScan=False,
            sections=["СТО-34-238"],
            fragments=fragments,
            createdAt=now,
        )

        doc = RegulationDocument(
            id=regulation_id,
            user_id=user.id,
            file_name=file_name,
            content_type="application/pdf" if PDF_PATH.is_file() else "text/plain",
            storage_path=str(storage_path),
            is_scan=False,
            result_json={
                **parse_result.model_dump(mode="json"),
                "seedMarker": marker,
            },
        )
        db.add(doc)
        db.flush()

        role_result = RoleMatchResult(
            runId=role_run_id,
            regulationId=regulation_id,
            profile=RoleProfile(
                canonicalTitle=user.position or "офис-менеджер УД",
                department=user.department or "Управление делами",
            ),
            functions=functions,
            matches=[],
            audit={"seedMarker": marker, "source": "STO-34-238_processes.txt"},
            createdAt=now,
        )
        role_run = RoleMatchRun(
            id=role_run_id,
            regulation_id=regulation_id,
            user_id=user.id,
            position=role_result.profile.canonicalTitle,
            department=role_result.profile.department,
            result_json=role_result.model_dump(mode="json"),
        )
        db.add(role_run)
        db.flush()

        draft = AgentDraft(
            id=draft_id,
            user_id=user.id,
            regulation_id=regulation_id,
            role_match_run_id=role_run_id,
            readiness_run_id="",
            title=f"{role_result.profile.canonicalTitle}: {file_name}",
            position=role_result.profile.canonicalTitle,
            department=role_result.profile.department,
            status="ready",
            progress=100,
            result_json={
                "roleMatchRunId": role_run_id,
                "regulationFileName": file_name,
                "seedMarker": marker,
                "agentSuggestions": suggestions,
                "suggestionRegulationId": regulation_id,
                "suggestionRoleMatchRunId": role_run_id,
            },
        )
        db.add(draft)
        db.commit()

        print("OK")
        print(f"  user:       {user.fio} ({user.id})")
        print(f"  regulation: {regulation_id}")
        print(f"  role_match: {role_run_id}")
        print(f"  draft:      {draft_id}")
        print(f"  status:     ready")
        print(f"  processes:  {len(suggestions)}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed STO-34-238 ready agent draft")
    parser.add_argument("--fio", default=DEFAULT_FIO)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Delete previous СТО-34-238 drafts for this user before insert",
    )
    args = parser.parse_args()
    seed(fio=args.fio, replace_existing=args.replace_existing)


if __name__ == "__main__":
    main()

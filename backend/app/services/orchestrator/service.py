from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orchestrator import UserOrchestrator
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.schemas.orchestrator import (
    OrchestratorAgentBrief,
    OrchestratorOut,
    OrchestratorUserBrief,
)
from app.schemas.workflow import KpiTileSchema
from app.services import agent_kpi
from app.services.orchestrator.ilchenko import ilchenko_tiles, is_ilchenko, ILCHENKO_SUMMARY
from app.services.orchestrator.prompts import build_calc_prompt, build_form_prompt
from app.services.triggers.service import is_workflow_paused, workflow_is_deleted

logger = logging.getLogger(__name__)

STATUSES = frozenset({"empty", "forming", "ready", "reforming", "calculating"})
FORM_MODES = frozenset({"form", "calc"})


class OrchestratorError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def list_active_agent_briefs(db: Session, user_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id)
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    briefs: list[dict[str, Any]] = []
    for row in rows:
        if (row.phase or "") != "done":
            continue
        if workflow_is_deleted(row) or is_workflow_paused(row.local_run):
            continue
        plan = row.plan_json if isinstance(row.plan_json, dict) else {}
        steps: list[dict[str, Any]] = []
        for step in plan.get("steps") or []:
            if not isinstance(step, dict):
                continue
            steps.append(
                {
                    "id": str(step.get("id") or ""),
                    "title": str(step.get("title") or ""),
                    "action": str(step.get("action") or ""),
                }
            )
        briefs.append(
            {
                "id": row.id,
                "title": row.title or "ИИ-агент",
                "goal": str(plan.get("goal") or ""),
                "steps": steps,
            }
        )
    briefs.sort(key=lambda item: str(item.get("id") or ""))
    return briefs


def agent_fingerprint(briefs: list[dict[str, Any]]) -> str:
    payload = [{"id": item.get("id") or "", "title": item.get("title") or ""} for item in briefs]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_row(db: Session, user_id: str) -> UserOrchestrator | None:
    return db.execute(
        select(UserOrchestrator).where(UserOrchestrator.user_id == user_id)
    ).scalar_one_or_none()


def _user_fio_position(db: Session, auth_user_id: str, fio: str, position: str) -> tuple[str, str]:
    row = db.get(AppUser, auth_user_id)
    resolved_fio = (fio or "").strip() or (row.fio if row is not None else "")
    resolved_position = (position or "").strip() or (row.position if row is not None else "")
    return resolved_fio, resolved_position


def _new_row(user_id: str, *, locked: bool = False) -> UserOrchestrator:
    return UserOrchestrator(
        id=uuid4().hex,
        user_id=user_id,
        status="empty",
        locked=locked,
        source_fingerprint="",
        source_agent_ids=[],
        tiles=[],
        summary="",
        sdk_agent_id="",
    )


def _seed_ilchenko(row: UserOrchestrator, briefs: list[dict[str, Any]], now: datetime) -> None:
    row.locked = True
    row.status = "ready"
    row.tiles = ilchenko_tiles(now=now)
    row.summary = ILCHENKO_SUMMARY
    row.source_fingerprint = agent_fingerprint(briefs)
    row.source_agent_ids = [str(item.get("id") or "") for item in briefs if item.get("id")]
    row.formed_at = now
    row.forming_at = None


def normalize_formed_tiles(raw_tiles: list[Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or _now()
    tiles: list[dict[str, Any]] = []
    for raw in raw_tiles:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not tid or not name:
            continue
        measure = raw.get("measure") if isinstance(raw.get("measure"), dict) else {}
        kind = str(measure.get("kind") or tid)
        method = agent_kpi.normalize_method(raw.get("method") if isinstance(raw.get("method"), dict) else {}, kind=kind)
        plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
        fact = raw.get("fact") if isinstance(raw.get("fact"), dict) else {}
        params = measure.get("params") if isinstance(measure.get("params"), dict) else {}
        tiles.append(
            {
                "id": tid,
                "name": name,
                "plan": {
                    "label": str(plan.get("label") or "План"),
                    "value": agent_kpi._as_float(plan.get("value")),
                    "unit": str(plan.get("unit") or "%"),
                    "description": str(plan.get("description") or ""),
                },
                "fact": {
                    "label": str(fact.get("label") or "Факт"),
                    "value": None,
                    "unit": str(fact.get("unit") or plan.get("unit") or "%"),
                    "description": str(fact.get("description") or ""),
                },
                "measure": {
                    "kind": kind,
                    "params": params,
                    "formula": str(measure.get("formula") or ""),
                },
                "score_percent": None,
                "color": "none",
                "updated_at": "",
                "next_run_at": now.isoformat(),
                "evidence": "",
                "method": method,
            }
        )
        if len(tiles) >= 5:
            break
    if len(tiles) < 3:
        raise OrchestratorError("Нужно 3-5 плиток KPI должности", 400)
    return tiles


def _due_ids(tiles: list[Any], now: datetime) -> list[str]:
    return agent_kpi.due_tile_ids({"tiles": tiles}, now)


def _needs_form(*, locked: bool, tiles: list[Any], stored_fp: str, current_fp: str, has_agents: bool) -> bool:
    if locked:
        return False
    if not has_agents:
        return False
    if not tiles:
        return True
    return bool(current_fp) and current_fp != (stored_fp or "")


def _needs_calc(*, tiles: list[Any], calculating_at: Any, now: datetime) -> bool:
    if not tiles:
        return False
    if agent_kpi.is_calc_lock_active(calculating_at, now):
        return False
    return bool(_due_ids(tiles, now))


def to_out(
    row: UserOrchestrator | None,
    *,
    user_id: str,
    fio: str,
    position: str,
    briefs: list[dict[str, Any]],
    now: datetime | None = None,
) -> OrchestratorOut:
    now = now or _now()
    current_fp = agent_fingerprint(briefs)
    tiles = list((row.tiles if row is not None else None) or [])
    tiles = [item for item in tiles if isinstance(item, dict)]
    locked = bool(row.locked) if row is not None else is_ilchenko(user_id=user_id, fio=fio)
    stored_fp = (row.source_fingerprint if row is not None else "") or ""
    has_agents = bool(briefs)
    needs_form = _needs_form(
        locked=locked,
        tiles=tiles,
        stored_fp=stored_fp,
        current_fp=current_fp,
        has_agents=has_agents,
    )
    calculating_at = row.calculating_at if row is not None else None
    due_ids = _due_ids(tiles, now)
    needs_calc = _needs_calc(tiles=tiles, calculating_at=calculating_at, now=now)
    status = (row.status if row is not None else "empty") or "empty"
    if not tiles and not locked and status not in {"forming", "reforming", "calculating"}:
        status = "empty"
    form_prompt = ""
    calc_prompt = ""
    if needs_form:
        form_prompt = build_form_prompt(fio=fio, position=position, agents=briefs)
    if tiles:
        calc_prompt = build_calc_prompt(
            fio=fio,
            position=position,
            tiles=tiles,
            due_tile_ids=due_ids or [str(item.get("id") or "") for item in tiles],
            locked=locked,
        )
    parsed_tiles: list[KpiTileSchema] = []
    for item in tiles:
        try:
            parsed_tiles.append(KpiTileSchema.model_validate(item))
        except Exception:
            continue
    return OrchestratorOut(
        status=status,
        locked=locked,
        summary=(row.summary if row is not None else "") or "",
        tiles=parsed_tiles,
        source_fingerprint=stored_fp,
        current_fingerprint=current_fp,
        source_agent_ids=list((row.source_agent_ids if row is not None else None) or []),
        needs_form=needs_form,
        needs_calc=needs_calc,
        due_tile_ids=due_ids,
        sdk_agent_id=(row.sdk_agent_id if row is not None else "") or "",
        formed_at=_iso(row.formed_at if row is not None else None),
        form_prompt=form_prompt,
        calc_prompt=calc_prompt,
        agents=[OrchestratorAgentBrief.model_validate(item) for item in briefs],
        user=OrchestratorUserBrief(id=user_id, fio=fio, position=position),
    )


def get_orchestrator(
    db: Session,
    *,
    user_id: str,
    fio: str = "",
    position: str = "",
    now: datetime | None = None,
) -> OrchestratorOut:
    now = now or _now()
    try:
        fio, position = _user_fio_position(db, user_id, fio, position)
        briefs = list_active_agent_briefs(db, user_id)
        row = _get_row(db, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Orchestrator read failed user=%s: %s", user_id, exc)
        if is_ilchenko(user_id=user_id, fio=fio):
            ephemeral = _new_row(user_id, locked=True)
            _seed_ilchenko(ephemeral, [], now)
            return to_out(ephemeral, user_id=user_id, fio=fio, position=position, briefs=[], now=now)
        return to_out(None, user_id=user_id, fio=fio, position=position, briefs=[], now=now)
    if is_ilchenko(user_id=user_id, fio=fio) and (row is None or not (row.tiles or [])):
        try:
            if row is None:
                row = _new_row(user_id, locked=True)
                db.add(row)
            _seed_ilchenko(row, briefs, now)
            db.commit()
            db.refresh(row)
            logger.info("Orchestrator seeded locked tiles user=%s", user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Orchestrator seed failed user=%s: %s", user_id, exc)
            try:
                db.rollback()
            except Exception:
                pass
            ephemeral = _new_row(user_id, locked=True)
            _seed_ilchenko(ephemeral, briefs, now)
            return to_out(ephemeral, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)
    return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)


def ensure_orchestrator(
    db: Session,
    *,
    user_id: str,
    mode: str = "form",
    fio: str = "",
    position: str = "",
    now: datetime | None = None,
) -> OrchestratorOut:
    now = now or _now()
    kind = (mode or "form").strip().casefold()
    if kind not in FORM_MODES:
        raise OrchestratorError("mode must be form or calc", 400)
    fio, position = _user_fio_position(db, user_id, fio, position)
    briefs = list_active_agent_briefs(db, user_id)
    row = _get_row(db, user_id)
    locked_user = is_ilchenko(user_id=user_id, fio=fio)
    if row is None:
        row = _new_row(user_id, locked=locked_user)
        db.add(row)
    if locked_user:
        row.locked = True
        if not (row.tiles or []):
            _seed_ilchenko(row, briefs, now)
        if kind == "calc" and (row.tiles or []):
            row.status = "calculating"
            row.calculating_at = now
        db.commit()
        db.refresh(row)
        return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)

    snapshot = to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)
    if kind == "form":
        if not briefs:
            row.status = "empty"
            row.tiles = []
            row.forming_at = None
            db.commit()
            db.refresh(row)
            return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)
        if snapshot.needs_form:
            row.status = "reforming" if (row.tiles or []) else "forming"
            row.forming_at = now
        db.commit()
        db.refresh(row)
        return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)

    if row.tiles:
        row.status = "calculating"
        row.calculating_at = now
        db.commit()
        db.refresh(row)
    return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)


def save_formed(
    db: Session,
    *,
    user_id: str,
    tiles: list[Any],
    summary: str = "",
    sdk_agent_id: str = "",
    fio: str = "",
    position: str = "",
    now: datetime | None = None,
) -> OrchestratorOut:
    now = now or _now()
    fio, position = _user_fio_position(db, user_id, fio, position)
    if is_ilchenko(user_id=user_id, fio=fio):
        raise OrchestratorError("Для этого пользователя набор KPI фиксирован", 409)
    briefs = list_active_agent_briefs(db, user_id)
    if not briefs:
        raise OrchestratorError("Нет активных агентов для формирования KPI", 400)
    normalized = normalize_formed_tiles(tiles, now=now)
    row = _get_row(db, user_id)
    if row is None:
        row = _new_row(user_id, locked=False)
        db.add(row)
    if row.locked:
        raise OrchestratorError("Для этого пользователя набор KPI фиксирован", 409)
    row.status = "ready"
    row.locked = False
    row.tiles = normalized
    row.summary = (summary or "").strip()
    row.sdk_agent_id = (sdk_agent_id or "").strip() or row.sdk_agent_id
    row.source_fingerprint = agent_fingerprint(briefs)
    row.source_agent_ids = [str(item.get("id") or "") for item in briefs if item.get("id")]
    row.formed_at = now
    row.forming_at = None
    row.calculating_at = None
    db.commit()
    db.refresh(row)
    logger.info("Orchestrator formed user=%s tiles=%s", user_id, [item.get("id") for item in normalized])
    return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)


def apply_tile_updates(
    db: Session,
    *,
    user_id: str,
    updates: list[Any],
    sdk_agent_id: str = "",
    fio: str = "",
    position: str = "",
    now: datetime | None = None,
) -> OrchestratorOut:
    now = now or _now()
    fio, position = _user_fio_position(db, user_id, fio, position)
    briefs = list_active_agent_briefs(db, user_id)
    row = _get_row(db, user_id)
    if row is None or not (row.tiles or []):
        raise OrchestratorError("Оркестратор ещё не сформирован", 404)
    due_ids = set(_due_ids(list(row.tiles or []), now))
    if not due_ids:
        due_ids = {str(item.get("id") or "") for item in (row.tiles or []) if isinstance(item, dict)}
    kpi = {"tiles": [dict(item) for item in (row.tiles or []) if isinstance(item, dict)]}
    updated = agent_kpi.apply_calc_updates(kpi, updates if isinstance(updates, list) else [], due_ids=due_ids, now=now)
    row.tiles = updated.get("tiles") or row.tiles
    if sdk_agent_id.strip():
        row.sdk_agent_id = sdk_agent_id.strip()
    row.calculating_at = None
    if row.status == "calculating":
        row.status = "ready"
    db.commit()
    db.refresh(row)
    logger.info("Orchestrator calc user=%s tiles=%s", user_id, [item.get("id") for item in updates if isinstance(item, dict)])
    return to_out(row, user_id=user_id, fio=fio, position=position, briefs=briefs, now=now)


def list_due_orchestrators(
    db: Session, *, now: datetime | None = None
) -> list[tuple[UserOrchestrator, list[str]]]:
    now = now or _now()
    rows = list(db.execute(select(UserOrchestrator)).scalars().all())
    due: list[tuple[UserOrchestrator, list[str]]] = []
    for row in rows:
        tiles = [item for item in (row.tiles or []) if isinstance(item, dict)]
        if not tiles:
            continue
        if agent_kpi.is_calc_lock_active(row.calculating_at, now):
            continue
        tile_ids = _due_ids(tiles, now)
        if tile_ids:
            due.append((row, tile_ids))
    return due


def claim_due_orchestrator(db: Session, row: UserOrchestrator, *, now: datetime | None = None) -> bool:
    now = now or _now()
    if agent_kpi.is_calc_lock_active(row.calculating_at, now):
        return False
    row.calculating_at = now
    row.status = "calculating"
    db.commit()
    return True


def orch_calc_task_id(user_id: str, tile_ids: list[str], *, now: datetime | None = None) -> str:
    now = now or _now()
    tiles = ",".join(sorted(str(item) for item in tile_ids))
    slot = int(now.timestamp() // 60)
    return f"orch-kpi:{user_id}:{slot}:{tiles}"


def dispatch_due_orchestrator(db: Session, row: UserOrchestrator, tile_ids: list[str]) -> bool:
    from app.services.desktop_commands import push_desktop_command

    if not claim_due_orchestrator(db, row):
        return False
    payload = {
        "type": "calc_orchestrator",
        "user_id": row.user_id,
        "tile_ids": tile_ids,
    }
    ok = push_desktop_command(row.user_id, payload)
    logger.info(
        "Orchestrator calc dispatched user=%s tiles=%s delivered=%s",
        row.user_id,
        tile_ids,
        ok,
    )
    return ok

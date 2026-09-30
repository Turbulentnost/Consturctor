from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.models.position_kpi import (
    PositionKpiBuild,
    PositionKpiBuildMessage,
    PositionKpiMetric,
    PositionKpiModule,
    PositionKpiProfile,
    PositionKpiSource,
)
from app.services.position_kpi.connect import (
    builtin_metric_codes,
    connect_modules_to_profile,
    list_module_descriptors,
    module_source,
    stash_module_payloads,
    validate_generated_module_payloads,
)
from app.services.position_kpi.daily import resolve_profile
from app.services.position_kpi.extract import extract_position_kpis
from app.services.position_kpi.sources import catalog as data_source_catalog
from app.services.position_kpi.sources import describe_for_prompt
from app.services.workflows.document import DocumentError, load_attachment_bytes

logger = logging.getLogger(__name__)

STATUSES = {
    "awaiting_file",
    "extracting",
    "clarifying",
    "coding",
    "testing",
    "connected",
    "error",
}


class PositionKpiBuildError(Exception):
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


def _add_message(
    db: Session,
    *,
    build: PositionKpiBuild,
    role: str,
    content: str,
    structured: dict[str, Any] | None = None,
) -> PositionKpiBuildMessage:
    row = PositionKpiBuildMessage(
        id=str(uuid.uuid4()),
        build_id=build.id,
        user_id=build.user_id,
        role=role,
        content=content,
        structured_json=structured or {},
    )
    db.add(row)
    return row


_SCAN_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}


def _usable_text(value: str) -> str:
    text = (value or "").strip()
    if not text or "текст не извлечён" in text.casefold():
        return ""
    if text.startswith("[изображение:"):
        return ""
    return text


def _load_document(name: str, raw: bytes) -> tuple[str, str]:
    """Return (text, mode). Scans stay empty — Cursor SDK reads them via office.read_file."""
    suffix = Path(name or "").suffix.lower()
    try:
        item = load_attachment_bytes(name, raw, ocr=False)
    except DocumentError as exc:
        if suffix in _SCAN_SUFFIXES:
            return "", "scan"
        raise PositionKpiBuildError(str(exc)) from exc
    text = _usable_text(str(item.get("text") or ""))
    if text:
        return text, "text"
    if suffix in _SCAN_SUFFIXES:
        return "", "scan"
    return "", "empty"


def position_kpis_missing(answer: str) -> bool:
    blob = (answer or "").casefold().replace("ё", "е")
    return any(
        token in blob
        for token in (
            "должности нет",
            "должности не найден",
            "нет показателей",
            "показателей нет",
            "kpi этой должности нет",
            "в положении нет",
            "не нашла kpi",
            "не нашел kpi",
            "не относится к должности",
        )
    )


def build_sdk_prompt(build: PositionKpiBuild) -> str:
    extracted = build.extracted_json if isinstance(build.extracted_json, dict) else {}
    metrics = extracted.get("metrics") if isinstance(extracted.get("metrics"), list) else []
    lines = [
        "Ты одноразовый конструктор KPI, не публикуемый агент.",
        f"Должность пользователя: {build.position_name}. Официальная методика уже загружена Finance.",
        *(
            [
                f"Сотрудник: {_subject_fio(build)}. По нему проверяй источники на живых данных, "
                "но в код ФИО не зашивай."
            ]
            if _subject_fio(build)
            else []
        ),
        "Порядок строго такой:",
        "1) Не запрашивай и не загружай файл методики: список KPI ниже утверждён Finance.",
        "2) Не меняй названия, коды, веса и формулы каталога. Уточняй только источники плана, "
        "факта и правила сопоставления, если их не хватает.",
        "3) Напиши по одному slug: generated/<slug>.py и tests/test_<slug>.py. "
        "filename именно такой: это корень workspace, не папка code/. "
        "План и факт только из документа. Нет в документе — score_pct=None. "
        "Готовые модули уйдут в backend/kpi/generated.",
        "4) Модуль общий для должности. Никогда не зашивай ФИО сотрудника в код или SOURCE. "
        "Для персональных отборов используй ctx.subject_fio, а должность — ctx.subject_position.",
        "Не спрашивай расписание, Outlook и «когда запускать агента».",
        "Не пиши план «сейчас прочитаю».",
        "В модуле связка: SOURCE из реестра ниже, load_<code>_rows(ctx) = ctx.load_for(SOURCE), "
        "score_<code>_kpi(rows, ...) считает KPI, "
        "compute_<code>_kpi(ctx) вызывает load и сразу score. "
        "Тесты: FakeCtx для compute/load, словари для score. "
        "Модуль без SOURCE из реестра не подключится.",
        "Контракт отчёта: fact_pct, score_pct, contrib_pct, rows.",
        "Неавтоматизируемое оставь formula_kind=needs_clarify.",
        "Живые записи в 1С не создавай.",
        "",
        "Извлечённые показатели:",
    ]
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        lines.append(
            f"- {metric.get('code')}: {metric.get('name')} "
            f"(вес {metric.get('weight')}%, kind={metric.get('formula_kind')}, "
            f"clarify={metric.get('needs_clarify')})"
        )
        lines.append(f"  {str(metric.get('formula_human') or '')[:300]}")
    lines.append("")
    lines.append(describe_for_prompt())
    text = (build.source_text or "").strip()
    if text:
        lines.append("")
        lines.append("Текст методики (сокращённо):")
        lines.append(text[:12000])
    return "\n".join(lines)


def serialize_build(db: Session, build: PositionKpiBuild) -> dict[str, Any]:
    messages = (
        db.execute(
            select(PositionKpiBuildMessage)
            .where(PositionKpiBuildMessage.build_id == build.id)
            .order_by(PositionKpiBuildMessage.created_at, PositionKpiBuildMessage.id)
        )
        .scalars()
        .all()
    )
    return {
        "build_id": build.id,
        "position": build.position_name,
        "subject_fio": _subject_fio(build),
        "status": build.status,
        "cursor_agent_id": build.cursor_agent_id,
        "extracted": build.extracted_json or {},
        "catalog_draft": build.catalog_draft_json or {},
        "modules": build.modules_json or [],
        "profile_id": build.profile_id,
        "sdk_prompt": build_sdk_prompt(build) if build.source_text or build.extracted_json else "",
        "data_sources": data_source_catalog(),
        "messages": [
            {
                "message_id": row.id,
                "role": row.role,
                "content": row.content,
                "structured": row.structured_json or {},
                "created_at": _iso(row.created_at),
            }
            for row in messages
        ],
        "created_at": _iso(build.created_at),
        "updated_at": _iso(build.updated_at),
    }


def _get(db: Session, user_id: str, build_id: str) -> PositionKpiBuild:
    row = db.get(PositionKpiBuild, build_id)
    if row is None or row.user_id != user_id:
        raise PositionKpiBuildError("Сессия не найдена", status_code=404)
    return row


def _build_has_progress(build: PositionKpiBuild) -> bool:
    if (build.status or "") not in ("", "awaiting_file", "connected"):
        return True
    extracted = build.extracted_json if isinstance(build.extracted_json, dict) else {}
    if extracted.get("metrics") or extracted.get("attachments") or extracted.get("needs_vision"):
        return True
    if build.modules_json or (build.source_text or "").strip():
        return True
    return False


def _catalog_for_profile(db: Session, profile: PositionKpiProfile) -> dict[str, Any]:
    metrics = list(
        db.scalars(
            select(PositionKpiMetric)
            .where(PositionKpiMetric.profile_id == profile.id)
            .order_by(PositionKpiMetric.sort_order, PositionKpiMetric.id)
        ).all()
    )
    sources = list(
        db.scalars(
            select(PositionKpiSource).where(
                PositionKpiSource.metric_id.in_([item.id for item in metrics])
            )
        ).all()
    ) if metrics else []
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        by_metric.setdefault(source.metric_id, []).append(
            {
                "role": source.role,
                "kind": source.kind,
                "title": source.title,
                "detail": source.detail,
                "update_rule": source.update_rule,
                "extra_json": dict(source.extra_json or {}),
            }
        )
    return {
        "id": profile.id,
        "position_name": profile.position_name,
        "department": profile.department,
        "source_code": profile.source_code,
        "source_version": profile.source_version,
        "source_title": profile.source_title,
        "source_import_id": profile.source_import_id,
        "effective_from": profile.effective_from.isoformat() if profile.effective_from else None,
        "summary": profile.summary,
        "metrics": [
            {
                "id": metric.id,
                "code": metric.code,
                "name": metric.name,
                "sort_order": metric.sort_order,
                "weight": metric.weight,
                "unit": metric.unit,
                "plan_value": metric.plan_value,
                "direction": metric.direction,
                "formula_kind": metric.formula_kind,
                "formula_json": dict(metric.formula_json or {}),
                "formula_human": metric.formula_human,
                "sources": by_metric.get(metric.id, []),
            }
            for metric in metrics
        ],
    }


def _subject_fio(build: PositionKpiBuild) -> str:
    extracted = build.extracted_json if isinstance(build.extracted_json, dict) else {}
    return str(extracted.get("subject_fio") or "").strip()


def _kickoff_text(
    fio: str, profile: PositionKpiProfile, metrics: list[dict[str, Any]], *, ready: int = 0
) -> str:
    who = f"{fio}, {profile.position_name}" if fio else profile.position_name
    lines = [
        f"Сотрудник: {who}"
        + (f", {profile.department}" if profile.department else "")
        + ".",
        f"KPI утверждены Finance по «{profile.source_title or 'методике'}».",
        *([f"Уже считаются автоматически: {ready}."] if ready else []),
        "Нужны модули расчёта:",
        *[f"• {item['name']} ({item['weight']}%)" for item in metrics],
        "Пишу модули автоматического расчёта — по одному на показатель, с тестами.",
    ]
    return "\n".join(lines)


def _lock_build_start(db: Session, *, user_id: str, profile_id: str) -> None:
    """Serialize concurrent starts: the UI opens the chat twice and both requests would create a session."""
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        sql_text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"position_kpi_build:{user_id}:{profile_id}"},
    )


def start_build(
    db: Session,
    *,
    user_id: str,
    position: str,
    department: str = "",
    subject_fio: str = "",
) -> dict[str, Any]:
    name = (position or "").strip()
    if not name:
        raise PositionKpiBuildError("Укажите должность")
    profile = resolve_profile(db, name, department=(department or "").strip())
    if profile is None or not (profile.source_import_id or "").strip():
        raise PositionKpiBuildError(
            "Не загружена методика расчета KPI. Обратитесь к администратору",
            status_code=404,
        )
    catalog = _catalog_for_profile(db, profile)
    if not catalog["metrics"]:
        raise PositionKpiBuildError("В методике Finance нет показателей KPI.", status_code=409)
    ready_codes = builtin_metric_codes(db, profile.id) | set(
        db.scalars(
            select(PositionKpiModule.metric_code).where(PositionKpiModule.profile_id == profile.id)
        ).all()
    )
    pending = [item for item in catalog["metrics"] if item["code"] not in ready_codes]
    if not pending:
        raise PositionKpiBuildError("Все KPI должности уже считаются автоматически.", status_code=409)
    _lock_build_start(db, user_id=user_id, profile_id=profile.id)
    open_rows = (
        db.execute(
            select(PositionKpiBuild)
            .where(
                PositionKpiBuild.user_id == user_id,
                PositionKpiBuild.position_name == name,
                PositionKpiBuild.status.notin_(("connected",)),
            )
            .order_by(PositionKpiBuild.updated_at.desc())
        )
        .scalars()
        .all()
    )
    fio = (subject_fio or "").strip()
    current = [row for row in open_rows if row.profile_id == profile.id]
    if current:
        row = current[0]
        if fio and _subject_fio(row) != fio:
            row.extracted_json = {**(row.extracted_json or {}), "subject_fio": fio}
            db.commit()
            db.refresh(row)
        return serialize_build(db, row)
    row = PositionKpiBuild(
        id=str(uuid.uuid4()),
        user_id=user_id,
        position_name=name,
        status="clarifying",
        extracted_json={
            "position": profile.position_name,
            "subject_fio": fio,
            "metrics": pending,
            "source_import_id": profile.source_import_id,
        },
        catalog_draft_json=catalog,
        modules_json=[],
        profile_id=profile.id,
        source_text="\n".join(
            [
                profile.source_title or "Методика расчёта KPI",
                profile.summary or "",
                *[
                    f"{item['name']} — вес {item['weight']}%. {item['formula_human']}"
                    for item in pending
                ],
            ]
        ).strip(),
    )
    db.add(row)
    _add_message(
        db,
        build=row,
        role="assistant",
        content=_kickoff_text(fio, profile, pending, ready=len(catalog["metrics"]) - len(pending)),
        structured={"stage": "kickoff", "profile_id": profile.id},
    )
    db.commit()
    db.refresh(row)
    return serialize_build(db, row)


def get_build(db: Session, *, user_id: str, build_id: str) -> dict[str, Any]:
    return serialize_build(db, _get(db, user_id, build_id))


def _apply_extract(build: PositionKpiBuild, extracted: dict[str, Any]) -> None:
    build.extracted_json = extracted
    metrics = extracted.get("metrics") if isinstance(extracted.get("metrics"), list) else []
    build.catalog_draft_json = {
        "position_name": extracted.get("position") or build.position_name,
        "summary": extracted.get("summary") or "",
        "metrics": metrics,
    }
    if extracted.get("needs_position_choice"):
        build.status = "clarifying"
    elif metrics:
        build.status = "clarifying"
    else:
        build.status = "clarifying"


def attach_files(
    db: Session,
    *,
    user_id: str,
    build_id: str,
    files: list[tuple[str, bytes]],
) -> dict[str, Any]:
    del db, user_id, build_id, files
    raise PositionKpiBuildError(
        "Загружать методику может только Finance. Используйте назначенную методику.",
        status_code=403,
    )


def persist_turn(
    db: Session,
    *,
    user_id: str,
    build_id: str,
    message: str,
    files: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    if files:
        raise PositionKpiBuildError(
            "Файлы методики принимает только Finance.",
            status_code=403,
        )
    build = _get(db, user_id, build_id)
    text = (message or "").strip()
    if not text:
        raise PositionKpiBuildError("Пустое сообщение")
    _add_message(db, build=build, role="user", content=text)
    extracted = build.extracted_json if isinstance(build.extracted_json, dict) else {}
    if extracted.get("needs_position_choice") and build.source_text:
        extracted = extract_position_kpis(build.source_text, text)
        if not extracted.get("needs_position_choice"):
            build.position_name = str(extracted.get("position") or text).strip() or build.position_name
        _apply_extract(build, extracted)
        if extracted.get("metrics"):
            listing = "\n".join(
                f"• {item.get('name')} — вес {item.get('weight')}%"
                for item in extracted["metrics"]
                if isinstance(item, dict)
            )
            _add_message(
                db,
                build=build,
                role="assistant",
                content=f"Беру раздел «{build.position_name}»:\n{listing}",
                structured={"metrics": extracted["metrics"]},
            )
    elif build.status in {"clarifying", "awaiting_file"}:
        build.status = "coding"
    db.commit()
    db.refresh(build)
    return serialize_build(db, build)


def finish_sdk(
    db: Session,
    *,
    user_id: str,
    build_id: str,
    answer: str,
    events: list[dict[str, Any]] | None = None,
    modules: list[dict[str, Any]] | None = None,
    catalog_draft: dict[str, Any] | None = None,
    cursor_agent_id: str = "",
    connect: bool = False,
) -> dict[str, Any]:
    build = _get(db, user_id, build_id)
    if cursor_agent_id:
        build.cursor_agent_id = cursor_agent_id
    if catalog_draft:
        logger.info("Ignoring SDK catalog draft for Finance-owned KPI profile %s", build.profile_id)
    if modules:
        build.modules_json = stash_module_payloads(modules)
        build.status = "testing"
    parsed = extract_position_kpis(answer, build.position_name) if answer.strip() else {}
    found = [item for item in (parsed.get("metrics") or []) if isinstance(item, dict)]
    existing_metrics = (
        (build.catalog_draft_json or {}).get("metrics")
        if isinstance(build.catalog_draft_json, dict)
        else []
    )
    if found and len(found) >= 2 and not existing_metrics:
        _apply_extract(build, parsed)
    missing = (not modules) and position_kpis_missing(answer)
    if answer.strip():
        _add_message(
            db,
            build=build,
            role="assistant",
            content=answer.strip()[:4000],
            structured={
                "events": events or [],
                "metrics": found,
                "stage": "not_found" if missing else "sdk_finish",
                "needs_continue": not missing and not found,
            },
        )
    if not modules and not connect:
        build.status = "clarifying"
        if missing:
            if not answer.strip():
                _add_message(
                    db,
                    build=build,
                    role="assistant",
                    content=(
                        f"В этом положении нет KPI должности «{build.position_name}». "
                        "Приложите методику именно этой должности."
                    ),
                    structured={"stage": "not_found", "needs_continue": False},
                )
        elif not found:
            _add_message(
                db,
                build=build,
                role="assistant",
                content=(
                    "Нужно выделить KPI этой должности и уточнить, откуда план и факт. "
                    "Нажмите «Продолжить», если вопросы не начались."
                ),
                structured={"stage": "incomplete", "needs_continue": True},
            )
    if connect:
        return connect_build(
            db,
            user_id=user_id,
            build_id=build_id,
            modules=modules if modules else None,
        )
    db.commit()
    db.refresh(build)
    return serialize_build(db, build)


def connect_build(
    db: Session,
    *,
    user_id: str,
    build_id: str,
    catalog_draft: dict[str, Any] | None = None,
    modules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    build = _get(db, user_id, build_id)
    if catalog_draft:
        logger.info("Ignoring user catalog draft for Finance-owned KPI profile %s", build.profile_id)
    incoming = [item for item in (modules or []) if isinstance(item, dict) and module_source(item)]
    if not incoming:
        incoming = [
            item
            for item in (build.modules_json or [])
            if isinstance(item, dict) and module_source(item)
        ]
    catalog = dict(build.catalog_draft_json or {})
    if incoming:
        try:
            validate_generated_module_payloads(catalog, incoming)
        except ValueError as exc:
            build.status = "clarifying"
            _add_message(
                db,
                build=build,
                role="assistant",
                content=f"Методику не подключила. {exc}",
                structured={"stage": "module_invalid", "needs_continue": True},
            )
            db.commit()
            raise PositionKpiBuildError(str(exc)) from exc
    elif not build.profile_id:
        raise PositionKpiBuildError("Нет готовых модулей KPI для подключения")
    else:
        described = list_module_descriptors(db, build.profile_id)
        if not described:
            raise PositionKpiBuildError("Нет готовых модулей KPI для подключения")
        build.modules_json = described
        build.status = "connected"
        db.commit()
        db.refresh(build)
        return serialize_build(db, build)
    # Черновик сессии сохраняем до публикации, чтобы откат ошибки источника его не стёр.
    db.commit()
    try:
        profile_id = connect_modules_to_profile(
            db,
            profile_id=build.profile_id,
            catalog=catalog,
            modules=incoming,
        )
    except ValueError as exc:
        db.rollback()
        build = _get(db, user_id, build_id)
        build.status = "clarifying"
        _add_message(
            db,
            build=build,
            role="assistant",
            content=f"Методику не подключила. {exc}",
            structured={"stage": "source_invalid", "needs_continue": True},
        )
        db.commit()
        raise PositionKpiBuildError(str(exc)) from exc
    described = list_module_descriptors(db, profile_id)
    if described:
        build.modules_json = described
    build.profile_id = profile_id
    build.status = "connected"
    _add_message(
        db,
        build=build,
        role="assistant",
        content=(
            "Методика подключена: калькуляторы сохранены для этой должности "
            "и доступны всем, кто на ней работает."
        ),
        structured={"profile_id": profile_id, "stage": "connected"},
    )
    db.commit()
    db.refresh(build)
    return serialize_build(db, build)

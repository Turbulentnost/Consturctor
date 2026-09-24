from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.position_kpi import PositionKpiBuild, PositionKpiBuildMessage
from app.services.position_kpi.connect import (
    list_module_descriptors,
    module_source,
    stash_module_payloads,
    upsert_generated_catalog,
)
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
        f"Должность пользователя: {build.position_name}. Ищи только её таблицу.",
        "Порядок строго такой:",
        "1) Если страницы положения уже в этом сообщении — не вызывай office.read_file. "
        "Иначе один вызов office.read_file на конкретный файл .pdf "
        "(путь вида materials/attachments/001_имя.pdf, не папка attachments). "
        "start_page=2 — обложку пропусти. "
        "Как только инструмент вернул vision_pages — документ уже прочитан, "
        "второй вызов не делай. Не читай extracted.json, methodology.txt, AGENTS.md.",
        "2) По страницам найди KPI именно этой должности. Остальные строки таблицы выкинь.",
        "3) Если должности в документе нет — напиши это в чат и остановись. "
        "Больше никаких инструментов, askQuestion и файлов.",
        "4) Если KPI есть — выпиши ВСЕ показатели этой должности со всех страниц, "
        "не только первые два. Каждый с новой строки: 1. Название — вес N%. "
        "Последняя строка ровно СПИСОК_ГОТОВ. Не вызывай askQuestion.",
        "5) Модули на этом шаге не пиши. Следующий шаг спрашивает, откуда план и факт, "
        "затем отдельный агент пишет по одному slug: generated/<slug>.py и tests/test_<slug>.py. "
        "filename именно такой: это корень workspace, не папка code/. "
        "План и факт только из документа. Нет в документе — score_pct=None. "
        "Готовые модули уйдут в backend/kpi/generated.",
        "Не спрашивай расписание, Outlook и «когда запускать агента».",
        "Скан office.read_file отдаёт в зрение Cursor SDK. Не ищи OCR и LM Studio.",
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
    if extracted.get("needs_vision") and not metrics:
        lines.append(
            "Текста нет — это скан. extracted.json не содержит KPI. "
            "Читай PDF через office.read_file (без обложки) и ищи раздел этой должности."
        )
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


def start_build(db: Session, *, user_id: str, position: str) -> dict[str, Any]:
    name = (position or "").strip()
    if not name:
        raise PositionKpiBuildError("Укажите должность")
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
    empty = [row for row in open_rows if not _build_has_progress(row)]
    if empty:
        return serialize_build(db, empty[0])
    row = PositionKpiBuild(
        id=str(uuid.uuid4()),
        user_id=user_id,
        position_name=name,
        status="awaiting_file",
        extracted_json={},
        catalog_draft_json={},
        modules_json=[],
    )
    db.add(row)
    _add_message(
        db,
        build=row,
        role="assistant",
        content=(
            f"Загрузите положение о мотивации для должности «{name}». "
            "Подойдёт PDF, в том числе скан — страницы прочитает модель Cursor."
        ),
        structured={"stage": "awaiting_file"},
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
    build = _get(db, user_id, build_id)
    if not files:
        raise PositionKpiBuildError("Приложите файл методики")
    build.status = "extracting"
    texts: list[str] = []
    names: list[str] = []
    need_vision = False
    for name, raw in files:
        names.append(Path(name).name)
        text, mode = _load_document(name, raw)
        if text:
            texts.append(text)
        if mode == "scan":
            need_vision = True
    source = "\n\n".join(part for part in texts if part).strip()
    build.source_text = source
    extracted: dict[str, Any] = {}
    if source:
        extracted = extract_position_kpis(source, build.position_name)
        _apply_extract(build, extracted)
    else:
        build.status = "clarifying"
        build.extracted_json = {}
    merged = dict(build.extracted_json or {})
    merged["attachments"] = names
    if need_vision:
        merged["needs_vision"] = True
    build.extracted_json = merged
    extracted = merged
    _add_message(
        db,
        build=build,
        role="user",
        content="Загружена методика",
        structured={"attachments": names, "needs_vision": need_vision},
    )
    if extracted.get("needs_position_choice"):
        positions = extracted.get("positions") or []
        _add_message(
            db,
            build=build,
            role="assistant",
            content=(
                "В файле несколько должностей. Напишите, какой раздел разбирать: "
                + ", ".join(str(item) for item in positions)
            ),
            structured={"needs_position_choice": True, "positions": positions, "quickAnswers": positions},
        )
    elif extracted.get("metrics"):
        metrics = extracted["metrics"]
        listing = "\n".join(
            f"• {item.get('name')} — вес {item.get('weight')}%" for item in metrics if isinstance(item, dict)
        )
        _add_message(
            db,
            build=build,
            role="assistant",
            content=f"Нашла показатели должности «{build.position_name}»:\n{listing}\n\nДальше уточню, откуда брать план и факт по каждому.",
            structured={"metrics": metrics, "stage": "clarifying"},
        )
    elif need_vision:
        _add_message(
            db,
            build=build,
            role="assistant",
            content=(
                f"Файл получен. Прочитаю положение без обложки и найду KPI должности "
                f"«{build.position_name}». Если её в документе нет — сразу скажу, "
                "без лишних инструментов. Если есть — выпишу показатели и напишу модули в kpi."
            ),
            structured={"stage": "clarifying", "needs_vision": True, "attachments": names},
        )
    else:
        _add_message(
            db,
            build=build,
            role="assistant",
            content="В тексте не удалось однозначно выделить KPI. Опишите показатели или приложите другой файл.",
            structured={"metrics": []},
        )
    db.commit()
    db.refresh(build)
    return serialize_build(db, build)


def persist_turn(
    db: Session,
    *,
    user_id: str,
    build_id: str,
    message: str,
    files: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    if files:
        session = attach_files(db, user_id=user_id, build_id=build_id, files=files)
        build = _get(db, user_id, build_id)
        if message.strip():
            _add_message(db, build=build, role="user", content=message.strip())
            db.commit()
            db.refresh(build)
            session = serialize_build(db, build)
        return session
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
        merged = dict(build.catalog_draft_json or {})
        merged.update(catalog_draft)
        build.catalog_draft_json = merged
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
        merged = dict(build.catalog_draft_json or {})
        merged.update(catalog_draft)
        build.catalog_draft_json = merged
    incoming = [item for item in (modules or []) if isinstance(item, dict) and module_source(item)]
    if not incoming:
        incoming = [
            item
            for item in (build.modules_json or [])
            if isinstance(item, dict) and module_source(item)
        ]
    catalog = dict(build.catalog_draft_json or {})
    catalog.setdefault("position_name", build.position_name)
    # Черновик сессии сохраняем до публикации, чтобы откат ошибки источника его не стёр.
    db.commit()
    try:
        profile_id = upsert_generated_catalog(
            db,
            position=build.position_name,
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

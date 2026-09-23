from __future__ import annotations

import hashlib
import importlib
import logging
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models.position_kpi import (
    PositionCompRule,
    PositionKpiDailyFact,
    PositionKpiMetric,
    PositionKpiModule,
    PositionKpiProfile,
    PositionKpiSource,
)
from app.services.position_kpi.daily import normalize_position_name, resolve_profile
from app.services.position_kpi.extract import slug_code
from kpi.kinds import FORMULA_KINDS, SOURCE_KINDS, SOURCE_ROLES

logger = logging.getLogger(__name__)

GENERATED_PREFIX = "kpi.generated."
GENERATED_DIR = BACKEND_ROOT / "kpi" / "generated"


def generated_profile_id(position: str) -> str:
    digest = hashlib.sha1(normalize_position_name(position).encode("utf-8")).hexdigest()[:10]
    return f"generated-{digest}"


def module_name_for(profile_id: str, code: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", f"{profile_id}_{code}".lower()).strip("_")
    return f"{GENERATED_PREFIX}{slug}"


def declared_source(module_name: str) -> dict[str, Any]:
    if not module_name:
        return {}
    try:
        _drop_loaded_module(module_name)
        importlib.invalidate_caches()
        mod = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001
        return {}
    data = getattr(mod, "SOURCE", None)
    return dict(data) if isinstance(data, dict) else {}


def module_row_id(profile_id: str, code: str) -> str:
    digest = hashlib.sha1(f"{profile_id}\n{code}".encode("utf-8")).hexdigest()[:20]
    return f"mod-{digest}"


def metric_row_id(profile_id: str, code: str) -> str:
    digest = hashlib.sha1(f"{profile_id}\n{code}".encode("utf-8")).hexdigest()[:20]
    return f"met-{digest}"


def source_row_id(metric_id: str, role: str, kind: str, index: int) -> str:
    digest = hashlib.sha1(f"{metric_id}\n{role}\n{kind}\n{index}".encode("utf-8")).hexdigest()[:20]
    return f"src-{digest}"


def module_source(item: dict[str, Any]) -> str:
    return str(item.get("code_text") or item.get("source") or item.get("content") or "").strip()


def module_code(item: dict[str, Any]) -> str:
    return str(item.get("code") or item.get("metric_code") or "").strip()


def _drop_loaded_module(module_name: str) -> None:
    sys.modules.pop(module_name, None)
    package = sys.modules.get("kpi.generated")
    stem = module_name.removeprefix(GENERATED_PREFIX)
    if package is not None and hasattr(package, stem):
        delattr(package, stem)


def _safe_filename(module: str) -> str:
    name = module[len(GENERATED_PREFIX) :] if module.startswith(GENERATED_PREFIX) else module
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "metric"
    return f"{slug}.py"


def _upsert(db: Session, model, item_id: str, **values: Any) -> None:
    row = db.get(model, item_id)
    if row is None:
        db.add(model(id=item_id, **values))
        return
    for key, value in values.items():
        setattr(row, key, value)


def _drop_profile(db: Session, profile_id: str) -> None:
    """Убрать карточку должности вместе с показателями, чтобы имя освободилось."""
    metric_ids = list(
        db.execute(
            select(PositionKpiMetric.id).where(PositionKpiMetric.profile_id == profile_id)
        ).scalars()
    )
    if metric_ids:
        db.execute(delete(PositionKpiSource).where(PositionKpiSource.metric_id.in_(metric_ids)))
    db.execute(delete(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile_id))
    db.execute(delete(PositionKpiModule).where(PositionKpiModule.profile_id == profile_id))
    db.execute(delete(PositionCompRule).where(PositionCompRule.profile_id == profile_id))
    db.execute(delete(PositionKpiDailyFact).where(PositionKpiDailyFact.profile_id == profile_id))
    row = db.get(PositionKpiProfile, profile_id)
    if row is not None:
        db.delete(row)
    db.flush()


def write_generated_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init_path = GENERATED_DIR / "__init__.py"
    if not init_path.exists():
        init_path.write_text('"""Сгенерированные калькуляторы KPI должности."""\n', encoding="utf-8")
    stored: list[dict[str, Any]] = []
    for item in modules:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("metric_code") or "").strip()
        module = str(item.get("module") or "").strip()
        source = module_source(item)
        if not source:
            continue
        if not code:
            code = module_code(item)
        if not module.startswith(GENERATED_PREFIX):
            if not code:
                continue
            module = f"{GENERATED_PREFIX}{slug_code(code, 1)}"
        filename = _safe_filename(module)
        path = GENERATED_DIR / filename
        path.write_text(source, encoding="utf-8")
        _drop_loaded_module(module)
        tests = str(item.get("tests") or item.get("test_text") or "").strip()
        test_name = ""
        if tests:
            test_name = f"test_{Path(filename).stem}.py"
            (GENERATED_DIR / test_name).write_text(tests, encoding="utf-8")
        stored.append(
            {
                "module": module,
                "filename": filename,
                "metric_code": code,
                "tests": test_name,
                "path": str(path),
            }
        )
    importlib.invalidate_caches()
    return stored


def stash_module_payloads(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Черновик сессии: исходник остаётся в JSON, пока публикация не запишет его в каталог."""
    stashed: list[dict[str, Any]] = []
    for item in modules or []:
        if not isinstance(item, dict):
            continue
        source = module_source(item)
        code = module_code(item)
        if not source or not code:
            continue
        stashed.append(
            {
                "metric_code": code,
                "module": str(item.get("module") or "").strip(),
                "code_text": source,
                "tests": str(item.get("tests") or item.get("test_text") or "").strip(),
            }
        )
    return stashed


def persist_generated_modules(
    db: Session,
    profile_id: str,
    modules: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Пишет исходник в каталог должности и материализует файл на этом процессе."""
    prepared: list[dict[str, Any]] = []
    for item in modules or []:
        if not isinstance(item, dict):
            continue
        code = module_code(item)
        source = module_source(item)
        if not code or not source:
            continue
        module = module_name_for(profile_id, code)
        tests = str(item.get("tests") or item.get("test_text") or "").strip()
        _upsert(
            db,
            PositionKpiModule,
            module_row_id(profile_id, code),
            profile_id=profile_id,
            metric_code=code,
            module_name=module,
            source=source,
            tests=tests,
            content_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        )
        prepared.append(
            {
                "code": code,
                "metric_code": code,
                "module": module,
                "code_text": source,
                "tests": tests,
            }
        )
    if prepared:
        db.flush()
    return write_generated_modules(prepared)


def list_module_descriptors(db: Session, profile_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(PositionKpiModule)
        .where(PositionKpiModule.profile_id == profile_id)
        .order_by(PositionKpiModule.metric_code)
    ).scalars()
    described: list[dict[str, Any]] = []
    for row in rows:
        filename = _safe_filename(row.module_name)
        described.append(
            {
                "module": row.module_name,
                "filename": filename,
                "metric_code": row.metric_code,
                "tests": f"test_{Path(filename).stem}.py" if (row.tests or "").strip() else "",
                "path": str(GENERATED_DIR / filename),
            }
        )
    return described


def ensure_generated_modules(db: Session, profile_id: str) -> list[str]:
    """Восстанавливает файлы калькуляторов из базы, если на этом процессе их нет или они устарели."""
    if not profile_id:
        return []
    rows = (
        db.execute(select(PositionKpiModule).where(PositionKpiModule.profile_id == profile_id))
        .scalars()
        .all()
    )
    if not rows:
        return []
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init_path = GENERATED_DIR / "__init__.py"
    if not init_path.exists():
        init_path.write_text('"""Сгенерированные калькуляторы KPI должности."""\n', encoding="utf-8")
    refreshed: list[str] = []
    for row in rows:
        filename = _safe_filename(row.module_name)
        path = GENERATED_DIR / filename
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != (row.source or ""):
            path.write_text(row.source or "", encoding="utf-8")
            refreshed.append(row.module_name)
        tests = (row.tests or "").strip()
        if tests:
            test_path = GENERATED_DIR / f"test_{Path(filename).stem}.py"
            existing_tests = test_path.read_text(encoding="utf-8") if test_path.exists() else ""
            if existing_tests != tests:
                test_path.write_text(tests, encoding="utf-8")
    if not refreshed:
        return []
    importlib.invalidate_caches()
    for name in refreshed:
        _drop_loaded_module(name)
    return refreshed


def invalidate_profile_cache(db: Session, profile_id: str) -> None:
    if not profile_id:
        return
    db.execute(delete(PositionKpiDailyFact).where(PositionKpiDailyFact.profile_id == profile_id))


def upsert_generated_catalog(
    db: Session,
    *,
    position: str,
    catalog: dict[str, Any],
    modules: list[dict[str, Any]] | None = None,
) -> str:
    name = str(position or catalog.get("position_name") or catalog.get("position") or "").strip()
    if not name:
        raise ValueError("Не указана должность")
    profile_id = str(catalog.get("id") or "").strip()
    if not profile_id or profile_id.startswith("plnpo010-"):
        profile_id = generated_profile_id(name)
    existing = resolve_profile(db, name)
    if existing is not None and existing.id != profile_id:
        _drop_profile(db, existing.id)
    metrics = catalog.get("metrics") if isinstance(catalog.get("metrics"), list) else []
    _upsert(
        db,
        PositionKpiProfile,
        profile_id,
        position_name=name,
        department=str(catalog.get("department") or ""),
        status="active",
        source_code=str(catalog.get("source_code") or "methodology"),
        source_version=str(catalog.get("source_version") or "1"),
        source_title=str(catalog.get("source_title") or "Методика расчёта KPI"),
        effective_from=None,
        summary=str(catalog.get("summary") or ""),
    )
    db.flush()
    stored = persist_generated_modules(db, profile_id, modules or [])
    by_code = {
        str(item.get("metric_code") or "").strip(): item
        for item in stored
        if str(item.get("metric_code") or "").strip()
    }
    for row in db.execute(
        select(PositionKpiModule).where(PositionKpiModule.profile_id == profile_id)
    ).scalars():
        by_code.setdefault(row.metric_code, {"module": row.module_name, "metric_code": row.metric_code})
    _upsert(
        db,
        PositionCompRule,
        f"{profile_id}-comp",
        profile_id=profile_id,
        salary_min=None,
        salary_max=None,
        currency="RUB",
        bonus_kind=str(catalog.get("bonus_kind") or "none"),
        bonus_base_pct=100,
        bonus_human=str(catalog.get("bonus_human") or ""),
        payout_json=[],
        notes=str(catalog.get("notes") or ""),
    )
    keep_metric_ids: set[str] = set()
    keep_metric_codes: set[str] = set()
    keep_source_ids: set[str] = set()
    for index, metric in enumerate(metrics, start=1):
        if not isinstance(metric, dict):
            continue
        code = str(metric.get("code") or slug_code(str(metric.get("name") or ""), index))[:64]
        provided_id = str(metric.get("id") or "").strip()
        metric_id = provided_id if provided_id and len(provided_id) <= 64 else metric_row_id(profile_id, code)
        keep_metric_ids.add(metric_id)
        keep_metric_codes.add(code)
        formula_kind = str(metric.get("formula_kind") or "needs_clarify")
        if formula_kind not in FORMULA_KINDS:
            formula_kind = "needs_clarify"
        formula_json = metric.get("formula_json") if isinstance(metric.get("formula_json"), dict) else {}
        _upsert(
            db,
            PositionKpiMetric,
            metric_id,
            profile_id=profile_id,
            code=code,
            name=str(metric.get("name") or code),
            sort_order=int(metric.get("sort_order") or index),
            weight=int(metric.get("weight") or 0),
            unit=str(metric.get("unit") or "%"),
            plan_value=metric.get("plan_value"),
            direction=str(metric.get("direction") or "higher"),
            formula_kind=formula_kind,
            formula_json=formula_json or {"kind": formula_kind},
            formula_human=str(metric.get("formula_human") or ""),
        )
        db.flush()
        sources = metric.get("sources") if isinstance(metric.get("sources"), list) else []
        module = by_code.get(code, {}).get("module") or ""
        if not sources:
            sources = [
                {
                    "role": "plan",
                    "kind": "regulation",
                    "title": "Методика",
                    "detail": "",
                    "update_rule": "",
                    "extra_json": {},
                },
                {
                    "role": "fact",
                    "kind": "unknown",
                    "title": "Факт",
                    "detail": "",
                    "update_rule": "",
                    "extra_json": {"module": module} if module else {},
                },
            ]
        for source_index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            role = str(source.get("role") or "fact")
            kind = str(source.get("kind") or "unknown")
            if role not in SOURCE_ROLES:
                role = "fact"
            if kind not in SOURCE_KINDS:
                kind = "unknown"
            extra = dict(source.get("extra_json") or {}) if isinstance(source.get("extra_json"), dict) else {}
            if role == "fact" and module:
                extra["module"] = module
                declared = declared_source(module)
                for key, value in declared.items():
                    if key == "module" or extra.get(key):
                        continue
                    extra[key] = value
            source_id = source_row_id(metric_id, role, kind, source_index)
            keep_source_ids.add(source_id)
            _upsert(
                db,
                PositionKpiSource,
                source_id,
                metric_id=metric_id,
                role=role,
                kind=kind,
                title=str(source.get("title") or ""),
                detail=str(source.get("detail") or ""),
                update_rule=str(source.get("update_rule") or ""),
                extra_json=extra,
            )
    existing_metrics = db.execute(
        select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile_id)
    ).scalars()
    for metric in existing_metrics:
        if metric.id not in keep_metric_ids:
            db.delete(metric)
    if keep_metric_ids:
        existing_sources = db.execute(
            select(PositionKpiSource).where(PositionKpiSource.metric_id.in_(list(keep_metric_ids)))
        ).scalars()
        for source in existing_sources:
            if source.id not in keep_source_ids:
                db.delete(source)
    if keep_metric_codes:
        for row in db.execute(
            select(PositionKpiModule).where(PositionKpiModule.profile_id == profile_id)
        ).scalars():
            if row.metric_code not in keep_metric_codes:
                db.delete(row)
    invalidate_profile_cache(db, profile_id)
    return profile_id

from __future__ import annotations

import ast
import hashlib
import importlib
import logging
import re
import sys
from datetime import date
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
    PositionKpiSubjectFact,
)
from app.services.position_kpi.daily import (
    department_key,
    normalize_position_name,
    resolve_profile,
)
from app.services.position_kpi.sources import SOURCES, validate_spec
from app.services.position_kpi.extract import slug_code
from kpi.kinds import FORMULA_KINDS, SOURCE_KINDS, SOURCE_ROLES

logger = logging.getLogger(__name__)

GENERATED_PREFIX = "kpi.generated."
GENERATED_DIR = BACKEND_ROOT / "kpi" / "generated"


def generated_profile_id(
    position: str, effective_from: date | None = None, department: str = ""
) -> str:
    identity = f"{normalize_position_name(position)}\n{effective_from.isoformat() if effective_from else ''}"
    dept = department_key(department)
    if dept:
        identity = f"{identity}\n{dept}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]
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


def validate_generated_module_payloads(
    catalog: dict[str, Any],
    modules: list[dict[str, Any]],
) -> None:
    """Не допускает публикацию частичного или несовместимого набора калькуляторов."""
    metrics = [item for item in (catalog.get("metrics") or []) if isinstance(item, dict)]
    required = [
        str(metric.get("code") or "").strip()
        for metric in metrics
        if str(metric.get("code") or "").strip()
        and not _builtin_module(metric.get("sources") if isinstance(metric.get("sources"), list) else [])
    ]
    by_code = {
        module_code(item): item
        for item in modules
        if isinstance(item, dict) and module_code(item)
    }
    missing = [code for code in required if code not in by_code]
    if missing:
        raise ValueError("Не созданы калькуляторы KPI: " + ", ".join(missing))
    if not required:
        raise ValueError("В методике нет показателей KPI для подключения")

    errors: list[str] = []
    for code in required:
        item = by_code[code]
        source_text = module_source(item)
        tests = str(item.get("tests") or item.get("test_text") or "").strip()
        if not source_text:
            errors.append(f"{code}: пустой исходник")
            continue
        if not tests:
            errors.append(f"{code}: нет теста")
        try:
            tree = ast.parse(source_text, filename=f"{code}.py")
        except SyntaxError as exc:
            errors.append(f"{code}: синтаксическая ошибка, строка {exc.lineno}: {exc.msg}")
            continue
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        expected = {
            f"load_{code}_rows",
            f"score_{code}_kpi",
            f"compute_{code}_kpi",
        }
        absent = sorted(expected - functions)
        if absent:
            errors.append(f"{code}: нет функций {', '.join(absent)}")
        declared: dict[str, Any] | None = None
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(target, ast.Name) and target.id == "SOURCE" for target in targets):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                value = None
            if isinstance(value, dict):
                declared = value
            break
        if declared is None:
            errors.append(f"{code}: SOURCE должен быть статическим словарём")
            continue
        source_check = validate_spec(declared)
        errors.extend(f"{code}: {message}" for message in source_check["errors"])
    if errors:
        raise ValueError("Модули KPI не готовы: " + " ".join(errors))


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
    db.execute(delete(PositionKpiSubjectFact).where(PositionKpiSubjectFact.profile_id == profile_id))
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


def connect_modules_to_profile(
    db: Session,
    *,
    profile_id: str,
    catalog: dict[str, Any],
    modules: list[dict[str, Any]],
) -> str:
    """Attach calculators to a Finance-owned profile without changing its methodology."""
    profile = db.get(PositionKpiProfile, profile_id)
    if profile is None or not (profile.source_import_id or "").strip():
        raise ValueError("Модули можно подключить только к методике, подтверждённой Finance")
    validate_generated_module_payloads(catalog, modules)
    metrics = list(
        db.scalars(
            select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile_id)
        ).all()
    )
    by_code = {metric.code: metric for metric in metrics}
    unknown = sorted(
        code for code in (module_code(item) for item in modules) if code and code not in by_code
    )
    if unknown:
        raise ValueError("В официальной методике нет KPI: " + ", ".join(unknown))

    stored = persist_generated_modules(db, profile_id, modules)
    source_errors: list[str] = []
    for item in stored:
        code = str(item.get("metric_code") or "").strip()
        module = str(item.get("module") or "").strip()
        metric = by_code.get(code)
        if metric is None or not module:
            continue
        facts = list(
            db.scalars(
                select(PositionKpiSource).where(
                    PositionKpiSource.metric_id == metric.id,
                    PositionKpiSource.role == "fact",
                )
            ).all()
        )
        if not facts:
            fact = PositionKpiSource(
                id=source_row_id(metric.id, "fact", "unknown", 1),
                metric_id=metric.id,
                role="fact",
                kind="unknown",
                title="Факт",
                detail="",
                update_rule="",
                extra_json={},
            )
            db.add(fact)
            facts = [fact]
        declared = declared_source(module)
        spec = {key: value for key, value in declared.items() if key != "module"}
        check = validate_spec(spec)
        source_errors.extend(f"«{metric.name}»: {error}" for error in check["errors"])
        registry = SOURCES.get(str(spec.get("source") or "").strip())
        target = facts[0]
        extra = dict(target.extra_json or {})
        extra.update({key: value for key, value in declared.items() if key != "module"})
        extra["module"] = module
        extra["validation"] = {
            "ok": not check["errors"],
            "errors": check["errors"],
            "warnings": check["warnings"],
        }
        target.extra_json = extra
        if registry is not None:
            target.kind = registry.kind
    if source_errors:
        raise ValueError("Модули не знают, откуда брать данные: " + " ".join(source_errors))
    invalidate_profile_cache(db, profile_id)
    db.flush()
    return profile_id


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
    db.execute(delete(PositionKpiSubjectFact).where(PositionKpiSubjectFact.profile_id == profile_id))


BUILTIN_PREFIX = "kpi.sources."


def _metric_name_key(value: str) -> str:
    folded = str(value or "").casefold().replace("ё", "е")
    return " ".join(re.sub(r"[^\w]+", " ", folded).split())


def _builtin_module(sources: list[dict[str, Any]]) -> str:
    from app.services.position_kpi.registry import scorer_for

    for source in sources:
        if str(source.get("role") or "") != "fact":
            continue
        extra = source.get("extra_json") if isinstance(source.get("extra_json"), dict) else {}
        module = str(extra.get("module") or "").strip()
        if module.startswith(BUILTIN_PREFIX) and scorer_for(module) is not None:
            return module
    return ""


def _source_dict(row: PositionKpiSource) -> dict[str, Any]:
    return {
        "role": row.role,
        "kind": row.kind,
        "title": row.title,
        "detail": row.detail,
        "update_rule": row.update_rule,
        "extra_json": dict(row.extra_json or {}),
    }


def _builtin_bindings(
    db: Session, profile_ids: list[str], *, position: str, department: str
) -> list[dict[str, Any]]:
    """Показатели с готовыми калькуляторами kpi.sources.* — их нельзя терять при замене профиля."""
    bindings: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        for metric in db.scalars(
            select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile_id)
        ).all():
            sources = [
                _source_dict(row)
                for row in db.scalars(
                    select(PositionKpiSource).where(PositionKpiSource.metric_id == metric.id)
                ).all()
            ]
            if _builtin_module(sources):
                bindings.append({"name": metric.name, "weight": metric.weight, "sources": sources})
    from kpi.seed_pl_npo_010 import CATALOG, DEPARTMENT

    if department_key(department) == department_key(DEPARTMENT):
        for item in CATALOG:
            if normalize_position_name(str(item["position_name"])) != normalize_position_name(position):
                continue
            for metric in item["metrics"]:
                sources = [dict(source) for source in metric["sources"]]
                if _builtin_module(sources):
                    bindings.append(
                        {"name": metric["name"], "weight": metric["weight"], "sources": sources}
                    )
    return bindings


def _match_binding(
    name: str, weight: int, bindings: list[dict[str, Any]], used: set[int]
) -> dict[str, Any] | None:
    from difflib import SequenceMatcher

    key = _metric_name_key(name)
    best: tuple[float, int] | None = None
    for index, binding in enumerate(bindings):
        if index in used:
            continue
        other = _metric_name_key(binding["name"])
        if other == key:
            used.add(index)
            return binding
        ratio = SequenceMatcher(None, key, other).ratio()
        same_weight = int(binding.get("weight") or 0) == int(weight or 0)
        if ratio >= 0.8 or (same_weight and ratio >= 0.55):
            if best is None or ratio > best[0]:
                best = (ratio, index)
    if best is None:
        return None
    used.add(best[1])
    return bindings[best[1]]


def builtin_metric_codes(db: Session, profile_id: str) -> set[str]:
    codes: set[str] = set()
    for metric in db.scalars(
        select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile_id)
    ).all():
        sources = [
            _source_dict(row)
            for row in db.scalars(
                select(PositionKpiSource).where(PositionKpiSource.metric_id == metric.id)
            ).all()
        ]
        if _builtin_module(sources):
            codes.add(metric.code)
    return codes


def inherit_builtin_sources(
    db: Session, profile_id: str, bindings: list[dict[str, Any]]
) -> list[str]:
    """Показатель без калькулятора получает источники готового kpi.sources.* с тем же смыслом."""
    if not bindings:
        return []
    used: set[int] = set()
    inherited: list[str] = []
    metrics = db.scalars(
        select(PositionKpiMetric)
        .where(PositionKpiMetric.profile_id == profile_id)
        .order_by(PositionKpiMetric.sort_order, PositionKpiMetric.id)
    ).all()
    pending: list[PositionKpiMetric] = []
    for metric in metrics:
        current = [
            _source_dict(row)
            for row in db.scalars(
                select(PositionKpiSource).where(PositionKpiSource.metric_id == metric.id)
            ).all()
        ]
        module = _builtin_module(current)
        if module:
            for index, binding in enumerate(bindings):
                if _builtin_module(binding["sources"]) == module:
                    used.add(index)
            continue
        pending.append(metric)
    for metric in pending:
        binding = _match_binding(metric.name, metric.weight, bindings, used)
        if binding is None:
            continue
        db.execute(delete(PositionKpiSource).where(PositionKpiSource.metric_id == metric.id))
        for index, source in enumerate(binding["sources"], start=1):
            role = str(source.get("role") or "fact")
            kind = str(source.get("kind") or "unknown")
            db.add(
                PositionKpiSource(
                    id=source_row_id(metric.id, role, kind, index),
                    metric_id=metric.id,
                    role=role,
                    kind=kind,
                    title=str(source.get("title") or ""),
                    detail=str(source.get("detail") or ""),
                    update_rule=str(source.get("update_rule") or ""),
                    extra_json=dict(source.get("extra_json") or {}),
                )
            )
        inherited.append(metric.code)
    db.flush()
    return inherited


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
    effective_raw = catalog.get("effective_from")
    if isinstance(effective_raw, date):
        effective_from = effective_raw
    elif str(effective_raw or "").strip():
        effective_from = date.fromisoformat(str(effective_raw).strip())
    else:
        effective_from = None
    department = str(catalog.get("department") or "").strip()
    profile_id = str(catalog.get("id") or "").strip()
    if not profile_id or profile_id.startswith("plnpo010-"):
        profile_id = generated_profile_id(name, effective_from, department)
    existing = resolve_profile(
        db,
        name,
        as_of=effective_from or date.today(),
        department=department or None,
        exact_department=bool(department),
    )
    same_key = db.scalars(
        select(PositionKpiProfile.id).where(
            PositionKpiProfile.position_name == name,
            PositionKpiProfile.department == department,
            PositionKpiProfile.effective_from == effective_from
            if effective_from is not None
            else PositionKpiProfile.effective_from.is_(None),
            PositionKpiProfile.id != profile_id,
        )
    ).all()
    replaced = list(same_key)
    if effective_from is None and existing is not None and existing.id != profile_id:
        replaced.append(existing.id)
    bindings = _builtin_bindings(
        db, [*replaced, profile_id], position=name, department=department
    )
    for stale_id in dict.fromkeys(replaced):
        _drop_profile(db, stale_id)
    metrics = catalog.get("metrics") if isinstance(catalog.get("metrics"), list) else []
    _upsert(
        db,
        PositionKpiProfile,
        profile_id,
        position_name=name,
        department=department,
        status="active",
        source_code=str(catalog.get("source_code") or "methodology"),
        source_version=str(catalog.get("source_version") or "1"),
        source_title=str(catalog.get("source_title") or "Методика расчёта KPI"),
        effective_from=effective_from,
        effective_to=None,
        source_import_id=str(catalog.get("source_import_id") or ""),
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
        bonus_base_pct=int(catalog.get("bonus_base_pct") or 100),
        bonus_human=str(catalog.get("bonus_human") or ""),
        payout_json=[],
        notes=str(catalog.get("notes") or ""),
    )
    keep_metric_ids: set[str] = set()
    keep_metric_codes: set[str] = set()
    keep_source_ids: set[str] = set()
    source_errors: list[str] = []
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
                spec = {key: value for key, value in extra.items() if key not in {"module", "validation"}}
                check = validate_spec(spec)
                if check["errors"]:
                    title = str(metric.get("name") or code)
                    source_errors.extend(f"«{title}»: {error}" for error in check["errors"])
                registry = SOURCES.get(str(spec.get("source") or "").strip())
                if registry is not None:
                    kind = registry.kind
                extra["validation"] = {
                    "ok": not check["errors"],
                    "errors": check["errors"],
                    "warnings": check["warnings"],
                }
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
    if source_errors:
        raise ValueError(
            "Модули не знают, откуда брать данные: " + " ".join(source_errors)
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
    db.flush()
    inherit_builtin_sources(db, profile_id, bindings)
    invalidate_profile_cache(db, profile_id)
    return profile_id

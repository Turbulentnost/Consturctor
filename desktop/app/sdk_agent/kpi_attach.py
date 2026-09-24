"""Attach methodology pages to the first KPI SDK message — like a chat drop."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.tools.ac.office_read import mark_vision_attached
from app.tools.ac.office_vision import VISION_MAX_PAGES, VisionRenderError, render_document_pages
from app.tools.ac.readable_files import IMAGE_SUFFIXES, PDF_SUFFIXES

_DOC_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES
_KPI_ROW = re.compile(
    r"^\s*(?:\d+[\).]|[-*•])\s*(.+?)(?:\s*[—\-–]\s*|\s+)(?:вес\s*)?(\d{1,3})\s*%",
    re.IGNORECASE,
)
_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

KPI_MODULE_SAMPLE = """from __future__ import annotations

from datetime import date
from typing import Any

# Источник ТОЛЬКО из реестра materials/data_sources.json: {"source": "<имя>", "params": {...}}.
# Один модуль считается для каждого сотрудника — вместо ФИО ставь {employee_fio}.
SOURCE = {
    "source": "onec.odata",
    "params": {
        "entity": "Document_ТД_Приказ",
        "filter": "Date ge datetime'{period_from_dt}' and Date le datetime'{period_to_dt}'",
    },
}


def load_orders_on_time_rows(ctx) -> list[dict[str, Any]]:
    raw = ctx.load_for(SOURCE) if hasattr(ctx, "load_for") else []
    rows: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        on_time = item.get("on_time")
        if on_time is None:
            plan = item.get("plan") or item.get("PlanDate")
            fact = item.get("fact") or item.get("FactDate")
            on_time = bool(plan) and bool(fact) and str(fact) <= str(plan)
        rows.append({**item, "on_time": bool(on_time)})
    return rows


def score_orders_on_time_kpi(rows, *, as_of: date, date_from=None, date_to=None) -> dict[str, Any]:
    items = [row for row in (rows or []) if isinstance(row, dict)]
    total = len(items)
    ok = sum(1 for row in items if row.get("on_time"))
    fact = round(100.0 * ok / total, 1) if total else None
    return {
        "fact_pct": fact,
        "score_pct": fact,
        "contrib_pct": round(fact * 50 / 100.0, 1) if fact is not None else None,
        "rows": items,
    }


def compute_orders_on_time_kpi(ctx, *, as_of: date, date_from=None, date_to=None) -> dict[str, Any]:
    rows = load_orders_on_time_rows(ctx)
    return score_orders_on_time_kpi(rows, as_of=as_of, date_from=date_from, date_to=date_to)
"""

KPI_MODULE_SAMPLE_TEST = """from datetime import date

from generated.orders_on_time import (
    compute_orders_on_time_kpi,
    load_orders_on_time_rows,
    score_orders_on_time_kpi,
)


class _FakeCtx:
    def extra_for(self, *_a, **_k):
        return {}

    def load_for(self, extra):
        assert extra.get("source") == "onec.odata"
        return [{"on_time": True}, {"on_time": False}]


def test_load_orders_on_time_rows() -> None:
    rows = load_orders_on_time_rows(_FakeCtx())
    report = score_orders_on_time_kpi(rows, as_of=date(2026, 9, 22))
    assert report["fact_pct"] == 50.0


def test_compute_orders_on_time_kpi_uses_loader() -> None:
    report = compute_orders_on_time_kpi(_FakeCtx(), as_of=date(2026, 9, 22))
    assert report["fact_pct"] == 50.0
    assert report["rows"]


def test_score_orders_on_time_kpi() -> None:
    report = score_orders_on_time_kpi(
        [{"on_time": True}, {"on_time": False}],
        as_of=date(2026, 9, 22),
    )
    assert report["fact_pct"] == 50.0
    assert report["score_pct"] == 50.0
    assert report["rows"]
"""


def unasked_kpi_rows(rows: list[dict[str, str]], asked_text: str) -> list[dict[str, str]]:
    """KPI names that are not already mentioned in a source question."""
    blob = (asked_text or "").casefold().replace("ё", "е")
    pending: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if len(name) < 3:
            continue
        key = name.casefold().replace("ё", "е")[:48]
        if key and key in blob:
            continue
        pending.append(row)
    return pending


def parse_kpi_rows(text: str) -> list[dict[str, str]]:
    """Pull name+weight lines from the agent's first table."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        match = _KPI_ROW.search(line)
        if not match:
            continue
        name = match.group(1).strip().strip("—-– ").strip()
        if len(name) < 3:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"name": name, "weight": match.group(2)})
    return rows


def collect_kpi_prompt_images(
    run_cwd: Path,
    *,
    start_page: int = 2,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Render the methodology PDF (skip cover) and return Agent.send image refs."""
    root = Path(run_cwd)
    source = _first_methodology_file(root)
    if source is None:
        return []
    dest = root / "materials" / "vision"
    try:
        rendered = render_document_pages(
            source,
            dest,
            max_pages=max(1, min(int(max_pages or VISION_MAX_PAGES), VISION_MAX_PAGES)),
            start_page=start_page,
        )
    except VisionRenderError:
        return []
    pages = rendered.get("pages") if isinstance(rendered, dict) else None
    if not isinstance(pages, list) or not pages:
        return []
    out: list[dict[str, Any]] = []
    for item in pages:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            continue
        out.append(
            {
                "path": _rel_to_workspace(root, path),
                "mimeType": str(item.get("mimeType") or "image/jpeg"),
                "page": int(item.get("page") or 0) or None,
                "filename": source.name,
            }
        )
    last = int(out[-1]["page"] or 0) if out else 0
    total = int(rendered.get("page_count") or 0)
    if out and total and last >= total:
        mark_vision_attached(root)
    return out


def _first_methodology_file(root: Path) -> Path | None:
    folder = root / "materials" / "attachments"
    if not folder.is_dir():
        return None
    found: list[Path] = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in _DOC_SUFFIXES:
            found.append(path)
    return found[0] if found else None


def _rel_to_workspace(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def kpi_slug(name: str, index: int) -> str:
    raw = "".join(_TRANSLIT.get(ch, ch) for ch in (name or "").casefold())
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")[:40]
    if slug and slug[0].isdigit():
        slug = f"kpi_{slug}"
    return slug or f"kpi_{index}"


KPI_SOURCE_OPTIONS = (
    "1С",
    "Outlook",
    "Excel или другой файл",
    "Уже написано в положении",
    "Форма / вручную",
    "Ходы агента",
    "Другая система — напишу какая",
    "Пока не знаю",
)


def source_kind_from_answer(text: str) -> str:
    blob = (text or "").casefold().replace("ё", "е")
    if any(token in blob for token in ("1с", "1c", "odata", "catalog_", "document_")):
        return "onec"
    if "план" in blob and "факт" in blob:
        return "onec"
    if "совещани" in blob and "отчет" in blob:
        return "onec"
    if "outlook" in blob:
        return "outlook"
    if "excel" in blob or "файл" in blob or ".xls" in blob:
        return "files"
    if "положен" in blob:
        return "regulation"
    if any(token in blob for token in ("вручн", "форма", "ручн")):
        return "manual"
    if "агент" in blob:
        return "agent_runs"
    return "unknown"


def source_loader_from_kind(kind: str) -> str:
    return {"onec": "odata", "outlook": "outlook", "files": "files"}.get(kind, "")


def registry_source_from_kind(kind: str) -> str:
    """Имя источника из реестра data_sources.json для выбранного канала."""
    return {
        "onec": "onec.odata",
        "outlook": "outlook.calendar",
        "files": "files.xlsx",
    }.get(kind, "")


def needs_source_detail(text: str) -> bool:
    blob = (text or "").casefold().replace("ё", "е")
    return "другая" in blob or "напишу" in blob


def source_spec_from_answer(text: str) -> dict[str, Any]:
    note = " ".join(str(text or "").split())
    kind = source_kind_from_answer(note)
    loader = source_loader_from_kind(kind)
    spec: dict[str, Any] = {"kind": kind, "note": note}
    if loader:
        spec["loader"] = loader
    return spec


def source_loader_hint(source: str) -> str:
    spec = source_spec_from_answer(source)
    kind = spec["kind"]
    registry = registry_source_from_kind(kind)
    if registry == "onec.odata":
        return (
            'SOURCE = {"source": "onec.odata", "params": {"entity": ..., "filter": ...}}  '
            "entity не угадывай: сначала onec.odata_catalog(search=слова пользователя), "
            "потом onec.odata_get(entity из ответа, top=5). "
            "В filter можно {period_from_dt}, {period_to_dt}, {employee_fio}. "
            "Если задачи именно этого сотрудника — лучше source docflow.tasks или onec.assignments."
        )
    if registry == "outlook.calendar":
        return 'SOURCE = {"source": "outlook.calendar", "params": {}}'
    if registry == "files.xlsx":
        return (
            'SOURCE = {"source": "files.xlsx", "params": {"file": "\\\\\\\\сервер\\\\папка\\\\файл.xlsx"}}  '
            "# путь общий (UNC), иначе на других ПК файла не будет"
        )
    if kind == "regulation":
        return 'SOURCE = {"source": "onec.protocols", "params": {}}  # или свой источник из реестра; иначе load_*_rows → []'
    if kind == "manual":
        return 'SOURCE = {"source": "manual"}  # форму не заполняй в тесте, load_*_rows → []'
    if kind == "agent_runs":
        return 'SOURCE = {"source": "agent_runs"}  # ходы не выдумывай, load_*_rows → []'
    note = spec.get("note") or source or "не назван"
    return (
        f'Выбери source из materials/data_sources.json (канал: {note!r}). '
        "Нет подходящего — load_*_rows → []. Свой формат {loader:...} не выдумывай."
    )


def _weight_int(value: str) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return 0
    return min(max(int(digits), 0), 100)


def catalog_from_jobs(jobs: list[dict[str, str]], *, position: str = "") -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    for index, job in enumerate(jobs or [], start=1):
        if not isinstance(job, dict):
            continue
        slug = str(job.get("slug") or "").strip()
        name = str(job.get("name") or slug).strip()
        if not slug and len(name) < 3:
            continue
        spec = source_spec_from_answer(str(job.get("source") or ""))
        kind = str(spec.get("kind") or "unknown")
        extra = {key: value for key, value in spec.items() if key != "kind" and value}
        weight = _weight_int(str(job.get("weight") or ""))
        metrics.append(
            {
                "code": slug or kpi_slug(name, index),
                "name": name,
                "sort_order": index,
                "weight": weight,
                "unit": "%",
                "plan_value": None,
                "direction": "higher",
                "formula_kind": "needs_clarify",
                "formula_json": {"kind": "needs_clarify"},
                "formula_human": f"{name} — вес {weight}%",
                "sources": [
                    {
                        "role": "plan",
                        "kind": "regulation",
                        "title": "Методика расчёта",
                        "detail": "Норма из загруженного положения.",
                        "update_rule": "Меняется новой версией положения.",
                        "extra_json": {},
                    },
                    {
                        "role": "fact",
                        "kind": kind,
                        "title": "Источник факта",
                        "detail": str(job.get("source") or "").strip(),
                        "update_rule": "Раз в расчётный период.",
                        "extra_json": extra,
                    },
                ],
            }
        )
    return {
        "position_name": position,
        "summary": f"Найдено показателей: {len(metrics)}." if metrics else "",
        "metrics": metrics,
    }


def source_for_kpi(name: str, notes: str) -> str:
    key = (name or "").casefold().replace("ё", "е")
    if not key:
        return ""
    for line in (notes or "").splitlines():
        folded = line.casefold().replace("ё", "е")
        if key not in folded:
            continue
        for sep in (" — ", " —", ": ", ":"):
            if sep not in line:
                continue
            tail = line.split(sep, 1)[-1].strip()
            if tail:
                return tail
        return line.strip()
    return ""


def unique_kpi_jobs(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    used: set[str] = set()
    jobs: list[dict[str, str]] = []
    for index, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if len(name) < 3:
            continue
        base = str(row.get("slug") or "").strip() or kpi_slug(name, index)
        slug = base
        suffix = 2
        while slug in used:
            slug = f"{base}_{suffix}"[:48]
            suffix += 1
        used.add(slug)
        jobs.append(
            {
                "name": name,
                "weight": str(row.get("weight") or "").strip(),
                "source": str(row.get("source") or "").strip(),
                "slug": slug,
            }
        )
    return jobs


def kpi_write_prompt(
    *,
    position: str,
    name: str,
    weight: str,
    source: str,
    slug: str,
) -> str:
    weight_label = f"{weight}%" if weight else "не указан"
    source_label = source or (
        "не назван — план и факт только из положения, иначе score_pct=None и fact_pct=None"
    )
    loader_hint = source_loader_hint(source)
    return (
        "KPI уже выписаны. Не читай PDF и не повторяй список. "
        "Пиши только один модуль. Не задавай вопросы.\n"
        f"Должность: {position or 'из задания'}.\n"
        f"Показатель: {name}\n"
        f"Вес: {weight_label}\n"
        f"Откуда брать план и факт: {source_label}\n"
        f"{loader_hint}\n"
        "Источник любой: 1С, Outlook, Excel, положение, форма, ходы агента "
        "или другая система. Не подставляй 1С/Outlook, если пользователь назвал иное.\n"
        f"slug: {slug}\n\n"
        f"Напиши ТОЛЬКО generated/{slug}.py и tests/test_{slug}.py. "
        "Другие slug не пиши. Готовый извлекатель в backend/ не ищи — "
        "источник найди инструментами Constructor.\n"
        "Порядок:\n"
        "1) Если источник 1С/отчёт — onec.odata_catalog(search=формулировка пользователя), "
        "затем onec.odata_get по entity из ответа. Outlook — outlook.*, "
        "файл — excel.* / office.read_file. Имена EntitySet не выдумывай.\n"
        "2) Read examples/orders_on_time.py — образец той же формы.\n"
        f"3) code.write_python filename=generated/{slug}.py — связка в одном файле:\n"
        f"   load_{slug}_rows(ctx) — достаёт сырые строки через ctx.load_for(SOURCE) "
        f"и отдаёт их калькулятору. Живой 1С/Outlook/файл в тесте не зови.\n"
        f"   score_{slug}_kpi(rows, *, as_of, date_from=None, date_to=None) — "
        "только считает, сам ничего не тянет. "
        "fact_pct, score_pct, contrib_pct, rows. "
        f"contrib_pct = score_pct * вес / 100, вес={weight or '0'}.\n"
        f"   compute_{slug}_kpi(ctx, *, as_of, date_from=None, date_to=None) — "
        f"rows = load_{slug}_rows(ctx); return score_{slug}_kpi(rows, ...). "
        "Дневной ход вызывает compute, не score напрямую.\n"
        "   SOURCE = {\"source\": <имя из materials/data_sources.json>, \"params\": {...}}. "
        "Свой формат {loader:...}/{kind:...} не выдумывай — иначе модуль не подключится. "
        "Для onec.odata entity бери из onec.odata_catalog. "
        "Если план и факт из разных источников — два ctx.load_for с двумя SOURCE.\n"
        f"4) code.write_python filename=tests/test_{slug}.py — "
        f"from generated.{slug} import compute_{slug}_kpi, load_{slug}_rows, score_{slug}_kpi; "
        "compute/load — FakeCtx; score — словарные фикстуры.\n"
        f"5) code.run_python filename=tests/test_{slug}.py — это pytest.\n"
        "6) Если упал, в ответе traceback: перепиши только упавший файл "
        "и запусти pytest снова.\n"
        "7) Как pytest прошёл (exit_code 0) — остановись. "
        "Следующий показатель будет отдельным ходом.\n\n"
        "Образец формы (скопируй сигнатуру, не имя функции):\n"
        f"{KPI_MODULE_SAMPLE}\n"
        "Образец теста:\n"
        f"{KPI_MODULE_SAMPLE_TEST}"
    )


def kpi_repair_prompt(slug: str, output: str) -> str:
    return (
        "Тесты не прошли. "
        f"Прочитай generated/{slug}.py и tests/test_{slug}.py, "
        "исправь только эти два файла через code.write_python "
        f"и снова запусти code.run_python filename=tests/test_{slug}.py.\n"
        "Не читай PDF. Не пиши другие slug. "
        "Если SOURCE без entity и источник 1С — сначала onec.odata_catalog / onec.odata_get.\n"
        f"Нужна связка: load_{slug}_rows(ctx) → "
        f"score_{slug}_kpi(rows, ...) → compute_{slug}_kpi(ctx) вызывает оба.\n\n"
        f"{(output or '')[-8000:]}"
    )


def kpi_write_jobs(
    rows: list[dict[str, str]],
    *,
    source_notes: str = "",
    existing_slugs: list[str] | None = None,
    position: str = "",
) -> list[dict[str, str]]:
    skip = {str(item).strip() for item in (existing_slugs or []) if str(item).strip()}
    jobs: list[dict[str, str]] = []
    for item in unique_kpi_jobs(rows):
        if item["slug"] in skip:
            continue
        source = item["source"] or source_for_kpi(item["name"], source_notes)
        jobs.append(
            {
                **item,
                "source": source,
                "position": position,
                "prompt": kpi_write_prompt(
                    position=position,
                    name=item["name"],
                    weight=item["weight"],
                    source=source,
                    slug=item["slug"],
                ),
            }
        )
    return jobs


def write_kpi_example_files(folder: Path) -> None:
    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "orders_on_time.py").write_text(KPI_MODULE_SAMPLE, encoding="utf-8")
    (dest / "test_orders_on_time.py").write_text(KPI_MODULE_SAMPLE_TEST, encoding="utf-8")

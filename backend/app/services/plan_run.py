"""Запуск агента по правилам из plan_json (не по захардкоженному сценарию).

Исполнение поиска/Excel — на desktop (SSE tool_request). Здесь только
резолв правил из plan и форматирование ответа.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from app.models.workflow import Workflow
from app.services.workflows.plan_models import PlanRuntime, WorkflowPlan

ProgressCallback = Callable[[str], None]

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class PlanRunError(RuntimeError):
    pass


@dataclass
class ResolvedRun:
    site_url: str
    keywords: list[str]
    columns: list[str]
    destination: str  # desktop | ...
    export_format: str  # xlsx
    source: str  # runtime | inferred


def plan_dict(workflow: Workflow) -> dict[str, Any]:
    return workflow.plan_json if isinstance(workflow.plan_json, dict) else {}


def resolve_run_spec(workflow: Workflow) -> ResolvedRun | None:
    """Build run rules from structured runtime, else infer from this plan's text only."""
    plan = WorkflowPlan.from_dict(plan_dict(workflow))
    ensure_runtime(plan)
    rt = plan.runtime
    if not rt.kind:
        return None
    if rt.kind != "site_search_excel":
        return None

    keywords = list(rt.keywords)
    if not keywords and rt.keyword_text:
        keywords = _expand_keyword_text(rt.keyword_text)
    if not keywords:
        return None

    columns = list(rt.columns) or ["название", "цена", "дата", "ссылка", "ключевые слова"]
    dest = (rt.export_destination or "desktop").casefold()
    fmt = (rt.export_format or "xlsx").casefold()
    if fmt in {"excel", "xls"}:
        fmt = "xlsx"
    url = (rt.site_url or "").strip()
    if not url:
        # Без URL в плане — не подставляем чужую площадку.
        return None

    return ResolvedRun(
        site_url=url,
        keywords=keywords,
        columns=columns,
        destination=dest,
        export_format=fmt,
        source="runtime" if plan_dict(workflow).get("runtime") else "inferred",
    )


def uses_plan_export(workflow: Workflow) -> bool:
    return resolve_run_spec(workflow) is not None


def build_plan_export_arguments(
    workflow: Workflow,
    *,
    max_queries: int = 80,
) -> dict[str, Any]:
    """Arguments for desktop tool `plan_export` (no local Playwright/Excel)."""
    spec = resolve_run_spec(workflow)
    if spec is None:
        raise PlanRunError("В плане агента нет правил поиска/Excel-выгрузки")
    if spec.export_format != "xlsx":
        raise PlanRunError(f"Формат выгрузки «{spec.export_format}» пока не поддержан")
    queries = list(spec.keywords[:max_queries])
    if not queries:
        raise PlanRunError("В плане нет ключевых слов для поиска")
    if not str(spec.site_url or "").strip():
        raise PlanRunError(
            "В плане агента не указан URL сайта (runtime.site_url). "
            "Укажите площадку в ответах при создании — без подстановки по умолчанию."
        )
    return {
        "site_url": spec.site_url,
        "keywords": queries,
        "columns": list(spec.columns),
        "destination": spec.destination,
        "export_format": spec.export_format,
        "workflow_title": workflow.title or "agent",
        "source": spec.source,
        "max_queries": max_queries,
    }


def ensure_runtime(plan: WorkflowPlan) -> WorkflowPlan:
    """Fill plan.runtime from answers/constraints when planner left it empty."""
    rt = plan.runtime
    if rt.kind and not rt.keywords and rt.keyword_text:
        rt.keywords = _expand_keyword_text(rt.keyword_text)
    if rt.kind and (rt.keywords or rt.keyword_text):
        if not rt.export_format:
            rt.export_format = "xlsx"
        if not rt.export_destination:
            rt.export_destination = "desktop"
        if not rt.columns:
            rt.columns = _extract_columns(_plan_blob(plan)) or [
                "название",
                "цена",
                "дата",
            ]
        return plan
    inferred = infer_runtime(plan)
    if inferred is not None:
        plan.runtime = inferred
    return plan


def infer_runtime(plan: WorkflowPlan) -> PlanRuntime | None:
    """Infer site_search_excel from free-text plan for this agent only."""
    blob = _plan_blob(plan)
    low = blob.casefold()

    wants_excel = "excel" in low or "xlsx" in low or "выгрузк" in low
    wants_desktop = "рабоч" in low and "стол" in low
    has_keywords = "ключев" in low
    if not (wants_excel and (wants_desktop or has_keywords)):
        # Still allow Excel+keywords without explicit desktop.
        if not (wants_excel and has_keywords):
            return None

    url = _extract_url(blob) or ""
    if not url:
        # Не выводим runtime без явного сайта — иначе позже подставлялась чужая площадка.
        return None
    keyword_text = _extract_keyword_block(plan)
    keywords = _expand_keyword_text(keyword_text) if keyword_text else []
    if not keywords:
        return None

    columns = _extract_columns(blob)
    destination = "desktop" if wants_desktop else "desktop"

    return PlanRuntime(
        kind="site_search_excel",
        site_url=url,
        keywords=keywords,
        keyword_text=keyword_text,
        export_format="xlsx",
        export_destination=destination,
        columns=columns,
    )


def _plan_blob(plan: WorkflowPlan) -> str:
    parts = [
        plan.title,
        plan.goal,
        "\n".join(plan.constraints),
        "\n".join(plan.test_criteria),
        "\n".join(plan.out_of_scope),
    ]
    for s in plan.steps:
        parts.append(f"{s.title}\n{s.action}\n{s.done_when}")
    for q in plan.open_questions:
        parts.append(f"{q.question}\n{q.answer}")
    return "\n".join(parts)


def _extract_url(text: str) -> str:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(").,;") if m else ""


def _extract_keyword_block(plan: WorkflowPlan) -> str:
    for line in plan.constraints:
        if "ключев" in line.casefold():
            m = re.search(
                r"(?:перечня|слов|фразы)\s*[:：]\s*(.+)$",
                line,
                flags=re.IGNORECASE,
            )
            if m:
                return m.group(1).strip()
            if ":" in line:
                tail = line.split(":", 1)[1].strip()
                if ";" in tail or "," in tail:
                    return tail
            return line.strip()

    chunks: list[str] = []
    for q in plan.open_questions:
        text = f"{q.question}\n{q.answer}"
        if "ключев" in text.casefold() or "словарь" in text.casefold():
            ans = (q.answer or "").strip()
            if ans:
                chunks.append(ans)
    return "\n".join(chunks)


def _extract_columns(blob: str) -> list[str]:
    low = blob.casefold()
    m = re.search(
        r"колонк[аи]\s*(?:excel[^:]*|выгрузки)?\s*[:—-]\s*([^\n.]+)",
        low,
        flags=re.IGNORECASE,
    )
    found: list[str] = []
    if m:
        raw = m.group(1)
        found = [p.strip(" «»\"'") for p in re.split(r"[,;/]| и ", raw) if p.strip(" «»\"'")]
    defaults = []
    for name in ("название", "цена", "дата", "ссылка", "ключевые слова"):
        if name in low:
            defaults.append(name)
    cols = found or defaults or ["название", "цена", "дата"]
    for extra in ("ссылка", "ключевые слова"):
        if extra in low and extra not in cols:
            cols.append(extra)
    nice = []
    for c in cols:
        c = c.strip().casefold()
        if not c:
            continue
        if c not in nice:
            nice.append(c)
    return nice


def _expand_keyword_text(block: str) -> list[str]:
    """Split keyword block into queries — no marketplace dictionaries."""
    block = (block or "").strip()
    if not block:
        return []
    if ";" in block:
        raw_parts = [p.strip() for p in block.split(";") if p.strip()]
    else:
        raw_parts = [p.strip() for p in re.split(r"[\n]+", block) if p.strip()]

    out: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        # Semicolon groups stay as phrases; otherwise allow comma-splitting.
        pieces = [part] if ";" in block else [c.strip() for c in re.split(r"[,/]", part) if c.strip()]
        if not pieces:
            pieces = [part]
        for q in pieces:
            q = q.strip()
            if not q:
                continue
            key = q.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
    return out


def run_site_search_excel(
    workflow: Workflow,
    *,
    on_progress: ProgressCallback | None = None,
    max_queries: int = 80,
) -> dict[str, Any]:
    """Deprecated: execution moved to desktop via tool_request `plan_export`."""
    _ = workflow, on_progress, max_queries
    raise PlanRunError(
        "Поиск и Excel выполняются на desktop (tool plan_export), не на backend."
    )


def format_plan_run_answer(result: dict[str, Any]) -> str:
    file_path = result.get("file") or ""
    count = int(result.get("count") or 0)
    cols = ", ".join(result.get("columns") or [])
    lines = [
        f"Готово. Найдено записей: {count}.",
        "Файл Excel сохранён по правилам из паспорта агента:",
        str(file_path),
        f"Колонки: {cols}.",
    ]
    if result.get("site_url"):
        lines.append(f"Источник: {result['site_url']}")
    rows = result.get("rows") or []
    if rows:
        lines.append("")
        lines.append("Примеры:")
        for row in rows[:8]:
            title = str(row.get("title") or "—")
            amount = str(row.get("amount") or "—")
            deadline = str(row.get("deadline") or "—")
            url = str(row.get("url") or "")
            kw = str(row.get("keywords") or "")
            lines.append(f"• {title}")
            lines.append(f"  цена: {amount}; дата: {deadline}")
            if kw:
                lines.append(f"  ключи: {kw}")
            if url:
                lines.append(f"  {url}")
    return "\n".join(lines)

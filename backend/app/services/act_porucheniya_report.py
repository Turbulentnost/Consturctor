"""Excel-отчёт по реестру поручений ACT/АСТ (как в журнале 1С «Поручения (ТД)»)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.workflow import Workflow
from app.services.fio_utils import fio_initials_slug
from app.services.act_porucheniya_odata import MODULE_TITLE, normalize_act_number
from app.services.assignments_report import _LABEL, _parse_dt

_ACT_HINTS = (
    "act00",
    "аст00",
    "act-",
    "аст-",
    "act_porucheniya",
    "act registry",
    "реестр поручений",
    "журнал поручений",
    "поручения (тд)",
    "document_тд_поручения",
    "акт00",
    "act porucheniya",
)

_HEADER_FILL = "FF37474F"
_HEADER_FONT = True
_COLUMN_WIDTHS = [16, 52, 28, 14, 14]
# Заметные пастельные заливки (ARGB) — хорошо видны на белом фоне с сеткой
_ACT_FILL = {
    "overdue": "FFFFCDD2",  # красный (просрочено)
    "critical": "FFFFAB91",  # коралловый (≤3 дн.)
    "high": "FFFFCC80",  # оранжевый (4–7 дн.)
    "medium": "FFFFF176",  # жёлтый (8–14 дн.)
    "low": "FFA5D6A7",  # зелёный (>14 дн.)
    "unknown": "FFE0E0E0",  # серый
}
_ACCEPTED_FILL = "FF81C784"  # «Принято» — насыщенный зелёный

_ACT_EXCEL_TABLE_STYLE = {
    "cell_borders": True,
    "wrap_text_columns": [2],
}

_STATUS_1C_MAP: dict[str, str] = {
    "вработе": "В работе",
    "принято": "Принято",
    "создано": "Создано",
    "отменено": "Отменено",
    "выполнено": "Выполнено",
    "done": "Выполнено",
}


def format_act_status_1c(status: str, *, source: str = "") -> str:
    """Подпись статуса как в журнале 1С «Поручения (ТД)»."""
    raw = (status or "").strip()
    if raw.casefold().startswith("из протокола"):
        return raw
    key = raw.casefold().replace(" ", "")
    if key in _STATUS_1C_MAP:
        return _STATUS_1C_MAP[key]
    if raw:
        return raw
    if (source or "").strip() == "protocol":
        return "Из протокола"
    return ""


def documents_from_excel_payload(excel_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Восстановить документы ACT из прочитанного Excel (лист «Задачи ACT»)."""
    rows = list(excel_payload.get("rows") or [])
    if len(rows) < 2:
        return []

    header = [str(cell or "").strip() for cell in rows[0]]
    col_index = {name.casefold(): idx for idx, name in enumerate(header)}

    def col(name: str, fallback: int) -> int:
        return col_index.get(name.casefold(), fallback)

    idx_act = col("номер act", 0)
    idx_task = col("задача", 1)
    idx_executor = col("исполнитель", 2)
    idx_deadline = col("срок", 3)
    idx_status = col("статус", 4)

    by_number: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        cells = list(row) + [""] * max(0, 5 - len(row))
        act = str(cells[idx_act] or "").strip()
        task = str(cells[idx_task] or "").strip()
        if not act or not task:
            continue
        deadline_raw = _parse_deadline_cell(cells[idx_deadline])
        status = str(cells[idx_status] or "").strip()
        if status.casefold().startswith("из протокола"):
            status = "В работе"
        line = {
            "line_number": 0,
            "task": task,
            "executor": str(cells[idx_executor] or "").strip(),
            "deadline": str(cells[idx_deadline] or "").strip(),
            "deadline_raw": deadline_raw,
            "priority": "",
            "source": "protocol" if "PROTO" in act.upper() else "excel",
        }
        doc = by_number.get(act)
        if doc is None:
            doc = {
                "number": act,
                "number_display": act,
                "about": "",
                "status": status or "В работе",
                "reporter": "",
                "secretary": "",
                "task_lines": [],
                "source": "excel",
            }
            by_number[act] = doc
        line["line_number"] = len(doc["task_lines"]) + 1
        doc["task_lines"].append(line)

    documents = list(by_number.values())
    for doc in documents:
        doc["task_line_count"] = len(doc.get("task_lines") or [])
    return documents


def flatten_documents_to_task_rows(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Одна строка Excel/отчёта = одна задача из табличной части «Поручения»."""
    flat: list[dict[str, Any]] = []
    for doc in documents:
        lines = list(doc.get("task_lines") or [])
        if not lines:
            continue
        for line in lines:
            flat.append(
                {
                    "number_display": doc.get("number_display")
                    or normalize_act_number(str(doc.get("number") or "")),
                    "date": doc.get("date") or "",
                    "about": doc.get("about") or "",
                    "status": doc.get("status") or "",
                    "reporter": doc.get("reporter") or "",
                    "secretary": doc.get("secretary") or "",
                    "line_number": line.get("line_number") or 0,
                    "task": line.get("task") or "",
                    "executor": line.get("executor") or "",
                    "task_deadline": line.get("deadline") or "",
                    "task_deadline_raw": line.get("deadline_raw") or "",
                    "priority": line.get("priority") or "",
                    "source": line.get("source") or doc.get("source") or "odata",
                }
            )
    return flat


def row_fill_for_task_row(row: dict[str, Any]) -> str:
    if _is_accepted_status(str(row.get("status") or "")):
        return _ACCEPTED_FILL
    raw = str(row.get("task_deadline_raw") or row.get("final_deadline_raw") or "")
    return criticality_for_deadline(raw)["fill"]


def _is_accepted_status(status: str) -> bool:
    text = (status or "").casefold().replace(" ", "")
    return text.startswith("принят") or text == "accepted"


def row_fill_for_document(doc: dict[str, Any]) -> str:
    if _is_accepted_status(str(doc.get("status") or "")):
        return _ACCEPTED_FILL
    return criticality_for_deadline(str(doc.get("final_deadline_raw") or ""))["fill"]


def workflow_runtime_kind(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    rt_plan = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    rt_local = local.get("runtime") if isinstance(local.get("runtime"), dict) else {}
    kind = str(rt_plan.get("kind") or rt_local.get("kind") or "").strip().casefold()
    if kind:
        return kind
    if str(local.get("seed") or "").casefold() in {"porucheniya", "action_tracker"}:
        return "action_tracker"
    return ""


def is_act_porucheniya_workflow(workflow: Workflow, *, task: str = "") -> bool:
    if workflow_runtime_kind(workflow) in {"act_porucheniya", "act_registry"}:
        return True
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    blob = " ".join(
        [
            str(workflow.title or ""),
            str(getattr(workflow, "notes", "") or ""),
            str(plan.get("title") or ""),
            str(plan.get("goal") or ""),
            str(task or ""),
            " ".join(str(x) for x in (plan.get("constraints") or [])),
        ]
    ).casefold()
    return any(h in blob for h in _ACT_HINTS)


def task_implies_act_registry(task: str) -> bool:
    blob = (task or "").casefold()
    return any(h in blob for h in _ACT_HINTS) or (
        "odata" in blob and ("act" in blob or "аст" in blob or "тд_поруч" in blob)
    )


def criticality_for_deadline(deadline_raw: str, *, now: datetime | None = None) -> dict[str, Any]:
    ref_now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    due = _parse_dt(deadline_raw.replace("T", " ")[:19] if deadline_raw else "")
    days_left: int | None = None
    level = "unknown"
    if due is not None:
        days_left = (due.date() - ref_now.date()).days
        if days_left < 0:
            level = "overdue"
        elif days_left <= 3:
            level = "critical"
        elif days_left <= 7:
            level = "high"
        elif days_left <= 14:
            level = "medium"
        else:
            level = "low"
    return {
        "level": level,
        "label": _LABEL[level],
        "fill": _ACT_FILL[level],
        "days_left": days_left,
    }


def build_act_excel_reformat_arguments(
    excel_payload: dict[str, Any],
    *,
    workflow_id: str,
    actor_fio: str = "",
) -> dict[str, Any] | None:
    """Пересохранить Excel с новыми row_fills, не меняя данные строк."""
    rows = list(excel_payload.get("rows") or [])
    if len(rows) < 2:
        return None

    header = [str(cell or "").strip() for cell in rows[0]]
    col_index = {name.casefold(): idx for idx, name in enumerate(header)}

    def col(name: str, fallback: int) -> int:
        return col_index.get(name.casefold(), fallback)

    idx_deadline = col("срок", 3)
    idx_status = col("статус", 4)

    data_rows: list[list[Any]] = []
    row_fills: list[str] = []
    for row in rows[1:]:
        cells = list(row) + [""] * max(0, len(header) - len(row))
        act = str(cells[col("номер act", 0)] or "").strip()
        task = str(cells[col("задача", 1)] or "").strip()
        if not act and not task:
            continue
        data_rows.append(cells[: len(header)])
        deadline_raw = _parse_deadline_cell(cells[idx_deadline])
        status = str(cells[idx_status] or "")
        row_fills.append(
            row_fill_for_task_row({"status": status, "task_deadline_raw": deadline_raw})
        )

    if not data_rows:
        return None

    slug = fio_initials_slug(actor_fio, fallback="act")
    filename = f"act_porucheniya_{slug}_{workflow_id[:8]}.xlsx"
    return {
        "filename": filename,
        "sheet": str(excel_payload.get("sheet") or "Задачи ACT")[:31],
        "headers": header,
        "rows": data_rows,
        "row_fills": row_fills,
        "header_fill": _HEADER_FILL,
        "header_bold": _HEADER_FONT,
        "column_widths": _COLUMN_WIDTHS,
        "freeze_header": True,
        "overwrite": True,
        "save_to_desktop": True,
        "runtime_context": {"workflow_id": workflow_id, "agent_id": workflow_id},
        **_ACT_EXCEL_TABLE_STYLE,
    }


def build_act_excel_arguments(
    *,
    workflow_id: str,
    documents: list[dict[str, Any]],
    actor_fio: str = "",
) -> dict[str, Any]:
    headers = [
        "Номер ACT",
        "Задача",
        "Исполнитель",
        "Срок",
        "Статус",
    ]
    rows: list[list[Any]] = []
    row_fills: list[str] = []
    for item in flatten_documents_to_task_rows(documents):
        status = str(item.get("status") or "")
        source = str(item.get("source") or "")
        status_label = format_act_status_1c(status, source=source)
        rows.append(
            [
                item.get("number_display") or "",
                item.get("task") or "",
                item.get("executor") or "",
                item.get("task_deadline") or "",
                status_label,
            ]
        )
        row_fills.append(row_fill_for_task_row(item))

    slug = fio_initials_slug(actor_fio, fallback="act")
    filename = f"act_porucheniya_{slug}_{workflow_id[:8]}.xlsx"
    return {
        "filename": filename,
        "sheet": "Задачи ACT",
        "headers": headers,
        "rows": rows,
        "row_fills": row_fills,
        "header_fill": _HEADER_FILL,
        "header_bold": _HEADER_FONT,
        "column_widths": _COLUMN_WIDTHS,
        "freeze_header": True,
        "overwrite": True,
        "save_to_desktop": True,
        "runtime_context": {"workflow_id": workflow_id, "agent_id": workflow_id},
        **_ACT_EXCEL_TABLE_STYLE,
    }


def format_task_lines_for_doc(doc: dict[str, Any], *, max_lines: int = 0) -> list[str]:
    """Текст задач документа в формате для чата."""
    lines = list(doc.get("task_lines") or [])
    if max_lines:
        lines = lines[:max_lines]
    out: list[str] = []
    for line in lines:
        ln = int(line.get("line_number") or 0) or len(out) + 1
        task = str(line.get("task") or "").strip()
        executor = str(line.get("executor") or "—").strip() or "—"
        deadline = str(line.get("deadline") or "—").strip() or "—"
        out.append(f"{ln}. {task}")
        out.append(f"   Исполнитель: {executor}")
        out.append(f"   Срок: {deadline}")
    return out


def compose_act_registry_answer(
    registry_payload: dict[str, Any],
    excel_payload: dict[str, Any] | None,
) -> str:
    documents = list(registry_payload.get("documents") or [])
    task_rows = flatten_documents_to_task_rows(documents)
    task_count = len(task_rows) or int(registry_payload.get("task_count") or 0)
    lines = [
        f"{MODULE_TITLE}: {len(documents)} документов ACT/АСТ, {task_count} задач (табличная часть «Поручения»).",
        f"Источник: OData ({registry_payload.get('entity') or 'Document_ТД_Поручения'}).",
    ]
    if not documents:
        source = str(registry_payload.get("source") or "")
        summary = str(registry_payload.get("summary") or "")
        if source == "odata-error":
            lines.append(f"OData: ошибка загрузки — {summary or 'неизвестная ошибка'}.")
            lines.append("Excel на рабочий стол не создан.")
        elif source == "odata-unconfigured":
            lines.append("OData не настроен (ODATA_BASE_URL / ERP_LOGIN в infra/.env).")
            lines.append("Excel на рабочий стол не создан.")
        else:
            lines.append("Документы ACT не найдены в OData (пустой ответ 1С).")
            lines.append("Excel на рабочий стол не создан.")
        return "\n".join(lines)

    merge = registry_payload.get("protocol_merge") or {}
    if merge.get("added_task_lines") or merge.get("added_documents"):
        lines.append("")
        lines.append("Дополнение из протокола:")
        if merge.get("added_documents"):
            lines.append(f"• Новых ACT-документов: {merge['added_documents']}")
        if merge.get("added_task_lines"):
            lines.append(f"• Новых строк задач: {merge['added_task_lines']}")
        lines.append(
            "• Строки из протокола помечены в колонке «Статус» "
            "(«Из протокола» или статус из текста); цвет строки — по сроку задачи, как у OData."
        )

    filt = str(registry_payload.get("filter") or "")
    if filt and filt != "без фильтров (полный реестр)":
        lines.append(f"Фильтр: {filt}.")

    counts: dict[str, int] = {}
    for row in task_rows:
        level = criticality_for_deadline(str(row.get("task_deadline_raw") or ""))["level"]
        counts[level] = counts.get(level, 0) + 1

    lines.append("")
    lines.append("Критичность по сроку задачи:")
    for key in ("overdue", "critical", "high", "medium", "low", "unknown"):
        if counts.get(key):
            lines.append(f"• {_LABEL[key]}: {counts[key]}")

    lines.append("")
    lines.append("Примеры (каждая задача отдельно):")
    shown_docs = 0
    for doc in documents:
        if shown_docs >= 3:
            break
        task_lines = list(doc.get("task_lines") or [])
        if not task_lines:
            continue
        num = doc.get("number_display") or doc.get("number") or "—"
        status = doc.get("status") or "—"
        lines.append(f"\n{num} ({status}) — {doc.get('about') or ''}"[:120])
        lines.extend(format_task_lines_for_doc(doc, max_lines=5))
        shown_docs += 1

    if excel_payload and excel_payload.get("path"):
        desktop = excel_payload.get("desktop_path") or excel_payload.get("path")
        lines.extend(
            [
                "",
                f"Excel (задачи ACT): {desktop}",
                "Одна строка = одна задача: номер ACT, текст, исполнитель, срок; "
                "статус — как в 1С; мягкая заливка строки по сроку задачи.",
            ]
        )
    return "\n".join(lines)


def _parse_deadline_cell(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:10], fmt)
            return dt.strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            continue
    parsed = _parse_dt(text)
    return parsed.strftime("%Y-%m-%dT00:00:00") if parsed else ""


def compose_excel_workbook_summary(
    excel_payload: dict[str, Any],
    *,
    source_path: str = "",
) -> str:
    """Сводка по прочитанному ACT-Excel (лист «Задачи ACT»)."""
    from pathlib import Path

    rows = list(excel_payload.get("rows") or [])
    sheet = str(excel_payload.get("sheet") or "")
    filename = str(excel_payload.get("filename") or (Path(source_path).name if source_path else ""))
    if not rows:
        return "Excel пуст или не удалось прочитать строки."

    header = [str(cell or "").strip() for cell in rows[0]]
    data_rows = rows[1:] if len(rows) > 1 else []
    col_index = {name.casefold(): idx for idx, name in enumerate(header)}

    def col(name: str, fallback: int) -> int:
        return col_index.get(name.casefold(), fallback)

    idx_act = col("номер act", 0)
    idx_task = col("задача", 1)
    idx_executor = col("исполнитель", 2)
    idx_deadline = col("срок", 3)
    idx_status = col("статус", 4)

    task_rows: list[dict[str, Any]] = []
    for row in data_rows:
        cells = list(row) + [""] * max(0, 5 - len(row))
        act = str(cells[idx_act] or "").strip()
        task = str(cells[idx_task] or "").strip()
        if not act and not task:
            continue
        deadline_raw = _parse_deadline_cell(cells[idx_deadline])
        task_rows.append(
            {
                "number_display": act,
                "task": task,
                "executor": str(cells[idx_executor] or "").strip(),
                "task_deadline": str(cells[idx_deadline] or "").strip(),
                "task_deadline_raw": deadline_raw,
                "status": str(cells[idx_status] or "").strip(),
                "source": "protocol" if "PROTO" in act.upper() else "excel",
            }
        )

    lines = [f"Сводка по Excel: {filename or source_path or 'файл'}"]
    if sheet:
        lines.append(f"Лист: {sheet}")
    lines.append(f"Строк задач: {len(task_rows)}")

    if not task_rows:
        lines.append("На листе нет данных (только заголовок).")
        return "\n".join(lines)

    act_numbers = sorted({str(r.get("number_display") or "") for r in task_rows if r.get("number_display")})
    lines.append(f"Уникальных ACT: {len(act_numbers)}")

    counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in task_rows:
        level = criticality_for_deadline(str(row.get("task_deadline_raw") or ""))["level"]
        counts[level] = counts.get(level, 0) + 1
        status = str(row.get("status") or "—").strip() or "—"
        status_counts[status] = status_counts.get(status, 0) + 1

    lines.append("")
    lines.append("Критичность по сроку:")
    for key in ("overdue", "critical", "high", "medium", "low", "unknown"):
        if counts.get(key):
            lines.append(f"• {_LABEL[key]}: {counts[key]}")

    lines.append("")
    lines.append("Статусы:")
    for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))[:8]:
        lines.append(f"• {status}: {count}")

    overdue_samples = [
        r
        for r in task_rows
        if criticality_for_deadline(str(r.get("task_deadline_raw") or ""))["level"] == "overdue"
    ][:5]
    if overdue_samples:
        lines.append("")
        lines.append("Примеры просроченных задач:")
        for row in overdue_samples:
            lines.append(
                f"• {row.get('number_display')} | {row.get('executor') or '—'} | "
                f"{row.get('task_deadline') or '—'} | {(row.get('task') or '')[:80]}"
            )

    protocol_count = sum(
        1 for r in task_rows if str(r.get("number_display") or "").upper().startswith("ACT00-PROTO")
    )
    if protocol_count:
        lines.append("")
        lines.append(f"Строк из протокола (ACT00-PROTO-*): {protocol_count}")

    if excel_payload.get("truncated"):
        lines.append("")
        lines.append("Примечание: прочитана только часть строк (лимит max_rows).")

    return "\n".join(lines)

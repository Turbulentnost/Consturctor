from __future__ import annotations

import re
from typing import Any

from app.services.position_kpi.daily import normalize_position_name
from kpi.kinds import FORMULA_KINDS

_POSITION_HEAD = re.compile(
    r"(?im)^(?:#{1,3}\s*)?(?:должность|position)\s*[:\-–]\s*(.+)$"
)
_NUMBERED = re.compile(r"(?m)^\s*(?:\d+[\).]|[-*•])\s+")
_WEIGHT = re.compile(r"(?i)(?:вес(?:ом)?|weight)\s*[:\-–]?\s*(\d{1,3})\s*%|(\d{1,3})\s*%")
_PLAN = re.compile(r"(?i)(?:цел[ьяи]|план|target|≥|>=)\s*(\d{1,3})\s*%")
_SOURCE = re.compile(
    r"(?i)источник\s*[:\-–]\s*(.+)$|Document_\S+|Catalog_\S+|outlook|1с|1c|excel",
)
_ENTITY = re.compile(r"(Document_[A-Za-zА-Яа-я0-9_]+|Catalog_[A-Za-zА-Яа-я0-9_]+)")

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

KPI_OCR_PROMPT = (
    "Распознай систему мотивации: должности, показатели KPI, вес в процентах, "
    "формулу расчёта, план/цель и источник данных (1С, Outlook, файл). "
    "Сохраняй таблицы построчно."
)


def slug_code(name: str, index: int) -> str:
    raw = "".join(_TRANSLIT.get(ch, ch) for ch in (name or "").casefold())
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")[:40]
    return slug or f"kpi_{index}"


def _guess_formula(text: str) -> tuple[str, dict[str, Any], bool]:
    blob = (text or "").casefold()
    if "индивидуальн" in blob or "02-58" in blob:
        return "individual", {"kind": "individual", "source": "form_02_58"}, False
    if "менее 5" in blob or "нарушен" in blob:
        return (
            "violation_bands",
            {
                "kind": "violation_bands",
                "input": "violations",
                "bands": [
                    {"lt": 5, "score": 100},
                    {"lte": 8, "score": 50},
                    {"gt": 8, "score": 0},
                ],
            },
            "источник" not in blob and "document_" not in blob,
        )
    if "без возврат" in blob or "возврат" in blob:
        return "complement_ratio", {"kind": "complement_ratio", "target_pct": 98}, False
    if "min(" in blob or "минимум" in blob:
        return "min_of", {"kind": "min_of"}, False
    if "≥" in text or ">=" in text or "цель" in blob:
        plan = _first_int(_PLAN.search(text))
        return (
            "gate_then_ratio",
            {"kind": "gate_then_ratio", "target_pct": plan or 95, "direction": "higher"},
            False,
        )
    if any(word in blob for word in ("формула не", "уточнить", "не указан", "склеен")):
        return "needs_clarify", {"kind": "needs_clarify", "note": text[:240]}, True
    return "needs_clarify", {"kind": "needs_clarify", "note": text[:240]}, True


def _first_int(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    for group in match.groups():
        if group and str(group).isdigit():
            return int(group)
    return None


def _split_items(block: str) -> list[str]:
    if _NUMBERED.search(block):
        parts = _NUMBERED.split(block)
        return [part.strip() for part in parts if part.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    for line in block.splitlines():
        text = line.strip()
        if not text:
            if buf:
                chunks.append("\n".join(buf).strip())
                buf = []
            continue
        if buf and _WEIGHT.search(text) and _WEIGHT.search(buf[0] or ""):
            chunks.append("\n".join(buf).strip())
            buf = [text]
            continue
        buf.append(text)
    if buf:
        chunks.append("\n".join(buf).strip())
    return [item for item in chunks if _WEIGHT.search(item) or len(item) > 20]


def _metric_from_item(item: str, index: int) -> dict[str, Any]:
    first = item.splitlines()[0].strip()
    name = re.split(r"\s[—\-–]\s|\s+вес|\s+\d{1,3}\s*%", first, maxsplit=1)[0].strip(" .;")
    if len(name) < 3:
        name = first[:120]
    weight = _first_int(_WEIGHT.search(item)) or 0
    plan = _first_int(_PLAN.search(item))
    formula_kind, formula_json, unclear = _guess_formula(item)
    if formula_kind not in FORMULA_KINDS:
        formula_kind = "needs_clarify"
        unclear = True
    entity_match = _ENTITY.search(item)
    source_match = _SOURCE.search(item)
    has_source = bool(entity_match or source_match)
    kind = "onec" if entity_match else "unknown"
    if source_match and "outlook" in (source_match.group(0) or "").casefold():
        kind = "outlook"
    if "excel" in item.casefold() or ".xlsx" in item.casefold():
        kind = "files"
    extra: dict[str, Any] = {}
    if entity_match:
        extra["entity"] = entity_match.group(1)
        extra["loader"] = "odata"
    elif kind == "outlook":
        extra["loader"] = "outlook"
    elif kind == "files":
        extra["loader"] = "files"
    needs_clarify = unclear or not has_source or formula_kind == "needs_clarify"
    return {
        "code": slug_code(name, index),
        "name": name[:512],
        "sort_order": index,
        "weight": min(max(weight, 0), 100),
        "unit": "%",
        "plan_value": plan,
        "direction": "higher",
        "formula_kind": "needs_clarify" if needs_clarify and formula_kind == "needs_clarify" else formula_kind,
        "formula_json": formula_json,
        "formula_human": item[:800],
        "needs_clarify": needs_clarify,
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
                "kind": kind if has_source else "unknown",
                "title": "Источник факта",
                "detail": item[:400],
                "update_rule": "Раз в расчётный период.",
                "extra_json": extra,
            },
        ],
    }


def split_position_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(_POSITION_HEAD.finditer(text or ""))
    if not matches:
        return [("", text or "")]
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        name = (match.group(1) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((name, text[start:end].strip()))
    return blocks


def extract_position_kpis(text: str, position: str) -> dict[str, Any]:
    """Достаёт KPI текущей должности из текста методики. Без VLM."""
    raw = (text or "").strip()
    wanted = normalize_position_name(position)
    blocks = split_position_blocks(raw)
    named = [(name, body) for name, body in blocks if name]
    positions = [name for name, _ in named]
    chosen_name = (position or "").strip()
    chosen_body = raw
    needs_choice = False
    if named:
        exact = next(
            ((name, body) for name, body in named if normalize_position_name(name) == wanted),
            None,
        )
        if exact is not None:
            chosen_name, chosen_body = exact
        elif wanted and len(named) == 1:
            chosen_name, chosen_body = named[0]
        elif not wanted and len(named) == 1:
            chosen_name, chosen_body = named[0]
        else:
            needs_choice = True
            chosen_body = ""
    metrics = []
    if chosen_body:
        items = _split_items(chosen_body)
        metrics = [_metric_from_item(item, index) for index, item in enumerate(items, start=1)]
        if not metrics and chosen_body.strip():
            metrics = [_metric_from_item(chosen_body.strip(), 1)]
    return {
        "position": chosen_name,
        "positions": positions,
        "needs_position_choice": needs_choice,
        "metrics": [] if needs_choice else metrics,
        "summary": (
            f"Найдено показателей: {len(metrics)}."
            if metrics
            else "Показатели должности в тексте не найдены."
        ),
    }

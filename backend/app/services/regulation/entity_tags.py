from __future__ import annotations

import re
from collections import OrderedDict

from app.schemas.regulation import (
    FragmentEntityTag,
    RegulationEntityLegendItem,
    RegulationFragment,
)

_TOC_LINE_RE = re.compile(r"\.{4,}\s*\d+\s*$")
# Жёсткие границы: старый вариант с {2,} и * на заглавной строке уходил в backtracking.
_ABBR_MAX_LEN = 160
_ABBR_RE = re.compile(
    r"^[-\u2022\u2013]?\s*"
    r"(?P<abbr>[A-ZА-ЯЁ]{2,16}(?:[ \t]+[A-ZА-ЯЁ0-9/]{1,16}){0,8})"
    r"[ \t]*[-—–][ \t]*"
    r"(?P<title>.{1,200})$"
)
_NUMBERED_TITLE_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+(?P<title>.+)$")
_ROLE_MARKERS = (
    "руководитель",
    "инженер",
    "заказчик",
    "владелец",
    "пользователь",
    "администратор",
    "специалист",
    "менеджер",
    "директор",
    "помощник",
    "секретарь",
    "исполнитель",
    "координатор",
    "оператор",
    "аналитик",
)
_ROLE_WORD_RE = re.compile(
    r"(?<![а-яёa-z])(?:" + "|".join(re.escape(marker) for marker in _ROLE_MARKERS) + r")(?![а-яёa-z])",
    re.IGNORECASE,
)
_PROCESS_MARKERS = (
    "этап",
    "процесс",
    "порядок",
    "жизненный цикл",
    "согласование",
    "регистрация",
    "внедрение",
)
_MAJOR_SECTION_RE = re.compile(r"^\d+\s+\S")
_VERSION_RE = re.compile(r"версия\s+\d+", re.I)
_SHEET_RE = re.compile(r"лист\s+\d+", re.I)
_DOC_CODE_RE = re.compile(r"рг-\d+", re.I)


def is_toc_line(text: str) -> bool:
    compact = " ".join((text or "").split())
    return bool(_TOC_LINE_RE.search(compact))


def strip_toc_leaders(text: str) -> str:
    compact = " ".join((text or "").split())
    return _TOC_LINE_RE.sub("", compact).strip()


def filter_display_noise(fragments: list[RegulationFragment]) -> list[RegulationFragment]:
    cleaned: list[RegulationFragment] = []
    for index, fragment in enumerate(fragments):
        if fragment.blockType == "table_row":
            cleaned.append(fragment)
            continue
        if _is_running_header_table(fragment):
            continue
        leftover = _strip_running_header_text(fragment.text, fragment.page)
        if leftover != fragment.text:
            if leftover:
                fragment = fragment.model_copy(
                    update={"text": leftover, "styleRuns": _filter_runs(fragment.styleRuns, leftover)}
                )
            elif _is_title_block(fragment):
                cleaned.append(fragment)
                continue
            else:
                continue
        if _is_flattened_title_duplicate(fragment, fragments[index + 1] if index + 1 < len(fragments) else None):
            continue
        cleaned.append(fragment)
    return cleaned


def annotate_entities(
    fragments: list[RegulationFragment],
) -> tuple[list[RegulationFragment], list[RegulationEntityLegendItem]]:
    abbreviations = _collect_abbreviations(fragments)
    tagged: list[RegulationFragment] = []
    current_role: FragmentEntityTag | None = None
    current_process: FragmentEntityTag | None = None

    for fragment in fragments:
        heading_title = _heading_title(fragment)
        if heading_title:
            if _is_role_title(heading_title):
                current_role = _make_tag("role", heading_title, abbreviations)
                current_process = None
            elif _is_process_title(heading_title):
                current_process = _make_tag("process", heading_title, abbreviations)
                current_role = None
            elif _NUMBERED_TITLE_RE.match(heading_title) or _is_major_section(heading_title):
                current_role = None
                current_process = None

        entities: list[FragmentEntityTag] = []
        if current_role is not None:
            entities.append(current_role)
        elif current_process is not None:
            entities.append(current_process)
        tagged.append(fragment.model_copy(update={"entities": entities}))

    legend = legend_from_fragments(tagged)
    return tagged, legend


def _collect_abbreviations(fragments: list[RegulationFragment]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fragment in fragments:
        text = (fragment.text or "").strip()
        if not text or len(text) > _ABBR_MAX_LEN or "\n" in text:
            continue
        match = _ABBR_RE.match(text)
        if not match:
            continue
        abbr = _clean_spaces(match.group("abbr"))
        title = match.group("title").strip(" ;.")
        if abbr and title:
            mapping[abbr.casefold()] = title
            mapping[_normalize_key(title)] = abbr
    return mapping


def _heading_title(fragment: RegulationFragment) -> str:
    if fragment.blockType != "heading":
        first_line = (fragment.text or "").splitlines()[0].strip() if fragment.text else ""
        if _NUMBERED_TITLE_RE.match(first_line) and len(first_line) <= 90:
            return strip_toc_leaders(first_line)
        return ""
    first_line = (fragment.text or "").splitlines()[0].strip()
    return strip_toc_leaders(first_line or fragment.section)


def _is_role_title(title: str) -> bool:
    numbered = _NUMBERED_TITLE_RE.match(title.strip())
    body = numbered.group("title") if numbered else title
    return bool(_ROLE_WORD_RE.search(body))


def _is_process_title(title: str) -> bool:
    lower = title.casefold()
    return any(marker in lower for marker in _PROCESS_MARKERS)


def _is_major_section(title: str) -> bool:
    return bool(_MAJOR_SECTION_RE.match(title.strip())) and "." not in title.split()[0]


def _make_tag(kind: str, title: str, abbreviations: dict[str, str]) -> FragmentEntityTag:
    clean_title = strip_toc_leaders(title)
    short = _short_title(clean_title, abbreviations)
    return FragmentEntityTag(
        entityId=f"{kind}:{_normalize_key(clean_title)}",
        kind=kind,  # type: ignore[arg-type]
        title=clean_title,
        shortTitle=short,
    )


def _short_title(title: str, abbreviations: dict[str, str]) -> str:
    numbered = _NUMBERED_TITLE_RE.match(title.strip())
    body = numbered.group("title") if numbered else title
    abbr = abbreviations.get(_normalize_key(body))
    if abbr and len(abbr) <= 24:
        return abbr
    return body


def legend_from_fragments(fragments: list[RegulationFragment]) -> list[RegulationEntityLegendItem]:
    items: OrderedDict[str, RegulationEntityLegendItem] = OrderedDict()
    for fragment in fragments:
        for entity in fragment.entities:
            current = items.get(entity.entityId)
            if current is None:
                items[entity.entityId] = RegulationEntityLegendItem(
                    entityId=entity.entityId,
                    kind=entity.kind,
                    title=entity.title,
                    shortTitle=entity.shortTitle,
                    fragmentIds=[fragment.fragmentId],
                )
            elif fragment.fragmentId not in current.fragmentIds:
                current.fragmentIds.append(fragment.fragmentId)
    return list(items.values())


def _is_running_header_table(fragment: RegulationFragment) -> bool:
    if fragment.kind != "table" and fragment.blockType != "table":
        return False
    blob = _table_blob(fragment)
    if fragment.page <= 1 and ("система менеджмента" in blob.casefold() or "всего листов" in blob.casefold()):
        return False
    return _looks_like_running_header(blob)


def _is_title_block(fragment: RegulationFragment) -> bool:
    blob = ((fragment.text or "") + " " + _table_blob(fragment)).casefold()
    return "система менеджмента" in blob or "всего листов" in blob


def _is_flattened_title_duplicate(
    fragment: RegulationFragment,
    nxt: RegulationFragment | None,
) -> bool:
    if nxt is None or fragment.table is not None or nxt.table is None:
        return False
    current = _normalize_key(fragment.text)
    following = _normalize_key(_table_blob(nxt))
    return bool(current) and current in following and _looks_like_running_header(fragment.text)


def _strip_running_header_text(text: str, page: int) -> str:
    raw = text or ""
    if page <= 1 and ("Система менеджмента" in raw or "Всего листов" in raw):
        return raw.strip()
    is_header_block = bool(_DOC_CODE_RE.search(raw) and _VERSION_RE.search(raw))
    kept: list[str] = []
    for line in raw.splitlines():
        compact = " ".join(line.split())
        if compact.casefold() == "содержание":
            kept.append(compact)
            continue
        if _is_headerish_line(compact, page):
            continue
        if is_header_block and len(compact) < 60 and not compact.startswith(("-", "•")) and not re.search(
            r"[.!?]", compact
        ):
            continue
        kept.append(compact)
    return "\n".join(item for item in kept if item).strip()


def _is_headerish_line(line: str, page: int) -> bool:
    compact = " ".join((line or "").split())
    if not compact:
        return True
    if page <= 1 and ("Система менеджмента" in compact or "Всего листов" in compact):
        return False
    if _looks_like_running_header(compact):
        return True
    if _DOC_CODE_RE.search(compact):
        return True
    if _VERSION_RE.search(compact) or _SHEET_RE.search(compact):
        return True
    lower = compact.casefold()
    return lower.startswith("регламент ") and len(compact) < 90


def _looks_like_running_header(text: str) -> bool:
    compact = " ".join((text or "").split())
    if not compact:
        return False
    has_version = bool(_VERSION_RE.search(compact))
    has_sheet = bool(_SHEET_RE.search(compact))
    has_code = bool(_DOC_CODE_RE.search(compact))
    if has_version and has_sheet:
        leftover = _VERSION_RE.sub("", compact)
        leftover = _SHEET_RE.sub("", leftover)
        leftover = _DOC_CODE_RE.sub("", leftover)
        leftover = leftover.replace("РЕГЛАМЕНТ внедрения решений на базе искусственного интеллекта", "")
        leftover = leftover.replace("на базе искусственного интеллекта", "")
        leftover = re.sub(r"\s+", " ", leftover).strip(" |;,-")
        return len(leftover) < 18
    return has_code and has_version and len(compact) < 160


def _table_blob(fragment: RegulationFragment) -> str:
    if fragment.table is None:
        return ""
    cells = list(fragment.table.headers)
    for row in fragment.table.rows:
        cells.extend(row)
    return " ".join(cells)


def _filter_runs(runs: list[dict], leftover: str) -> list[dict]:
    if not leftover:
        return []
    return [run for run in runs if str(run.get("text") or "") in leftover]


def normalize_entity_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip(" .;:-")


def _normalize_key(value: str) -> str:
    return normalize_entity_key(value)


def _clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

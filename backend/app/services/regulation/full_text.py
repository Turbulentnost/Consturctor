from __future__ import annotations

from app.schemas.regulation import RegulationFragment, RegulationParseResult

DEFAULT_MAX_CHARS = 120_000


def compose_regulation_text(result: RegulationParseResult, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Build a prompt-friendly full document with stable fragment references."""
    parts: list[str] = [
        f"Документ: {result.fileName}",
        f"regulationId: {result.regulationId}",
        "",
    ]
    total = sum(len(part) + 2 for part in parts)
    truncated = False

    for fragment in result.fragments:
        block = _fragment_block(fragment)
        if not block:
            continue
        block_len = len(block) + 2
        if total + block_len > max_chars:
            remain = max(0, max_chars - total)
            if remain > 200:
                parts.append(block[:remain].rstrip())
            truncated = True
            break
        parts.append(block)
        total += block_len

    if truncated:
        parts.append("\n[Документ обрезан из-за лимита контекста. Сохраняй ссылки на уже переданные fragmentId.]")
    return "\n\n".join(part for part in parts if part is not None).strip()


def _fragment_block(fragment: RegulationFragment) -> str:
    text = _fragment_text(fragment).strip()
    if not text:
        return ""
    section_path = " > ".join(fragment.sectionPath or ([fragment.section] if fragment.section else []))
    meta = [
        f"fragmentId={fragment.fragmentId}",
        f"page={fragment.page}",
        f"kind={fragment.kind}",
        f"blockType={fragment.blockType}",
    ]
    if section_path:
        meta.append(f"sectionPath={section_path}")
    if fragment.numbering:
        meta.append(f"numbering={fragment.numbering}")
    return f"[{' | '.join(meta)}]\n{text}"


def _fragment_text(fragment: RegulationFragment) -> str:
    if fragment.table is not None:
        rows: list[str] = []
        if fragment.table.headers:
            rows.append(" | ".join(fragment.table.headers))
        rows.extend(" | ".join(str(cell) for cell in row) for row in fragment.table.rows)
        table_text = "\n".join(row for row in rows if row.strip())
        if table_text:
            return table_text
    if fragment.cells:
        return " | ".join(f"{key}: {value}" for key, value in fragment.cells.items() if str(value).strip())
    return fragment.text or ""

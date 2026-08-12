from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas.regulation import AgentReadinessResult, RegulationParseResult, RevisionDiffBlock
from app.services.role_matching.claudehub_client import _load_json, _post_json


def create_llm_revision_files(
    *,
    source_path: Path,
    output_dir: Path,
    result: RegulationParseResult,
    readiness: AgentReadinessResult,
) -> tuple[
    Path,
    Path,
    Path | None,
    str,
    str,
    str,
    list[RevisionDiffBlock],
    list[dict],
    list[dict],
]:
    output_dir.mkdir(parents=True, exist_ok=True)
    applicable = [
        change
        for change in readiness.changes
        if change.status in {"pending", "accepted", "edited", "unchanged"}
    ]
    revised_blocks, message = _compose_revised_blocks(result, readiness, applicable)
    document_path = output_dir / f"{source_path.stem}.ai-ready.docx"
    protocol_path = output_dir / "change_protocol.txt"
    source_html = _preview_html(result.fragments, changed_ids={change.targetBlockId for change in applicable})
    revised_html = _preview_html(
        [
            fragment.model_copy(update={"text": revised_blocks.get(fragment.fragmentId, fragment.text)})
            for fragment in result.fragments
        ],
        changed_ids={change.targetBlockId for change in applicable},
    )
    diff_blocks = _diff_blocks(result, revised_blocks, applicable)
    _write_docx(document_path, result, revised_blocks, changed_ids={item.blockId for item in diff_blocks})
    pdf_path, source_preview_pages, revised_preview_pages = _write_pdf_revision_assets(
        source_path=source_path,
        output_dir=output_dir,
        result=result,
        revised_blocks=revised_blocks,
        diff_blocks=diff_blocks,
    )
    protocol_path.write_text(_protocol(readiness, diff_blocks, message), encoding="utf-8")
    return (
        document_path,
        protocol_path,
        pdf_path,
        message,
        source_html,
        revised_html,
        diff_blocks,
        source_preview_pages,
        revised_preview_pages,
    )


def _compose_revised_blocks(result: RegulationParseResult, readiness: AgentReadinessResult, changes: list) -> tuple[dict[str, str], str]:
    baseline = {fragment.fragmentId: fragment.text for fragment in result.fragments}
    fallback = _fallback_revised_blocks(baseline, changes)
    if not changes:
        return baseline, "Нет применяемых изменений; создана DOCX-копия исходного текста"
    payload = _revision_prompt(result, readiness, changes)
    try:
        raw = _post_json(payload, timeout=240.0)
        return _revised_blocks_from_raw(raw, baseline), "ClaudeHub Sonnet сформировал новую редакцию регламента"
    except Exception as sonnet_exc:  # noqa: BLE001 - retry with cheaper/faster fallback model.
        try:
            raw = _post_json(payload, timeout=240.0, model=settings.claudehub_fallback_model)
            return (
                _revised_blocks_from_raw(raw, baseline),
                f"ClaudeHub Haiku 4.5 ({settings.claudehub_fallback_model}) сформировал новую редакцию регламента",
            )
        except Exception as haiku_exc:  # noqa: BLE001 - keep document generation available offline.
            return _fallback_revision(baseline, fallback), (
                "ClaudeHub недоступен, применена редакция из ответов пользователя. "
                f"Sonnet error: {sonnet_exc}; Haiku error: {haiku_exc}"
            )


def _revised_blocks_from_raw(raw: str, baseline: dict[str, str]) -> dict[str, str]:
    data = _load_json(raw)
    revised = data.get("revisedBlocks") if isinstance(data, dict) else None
    if not isinstance(revised, list):
        raise ValueError("ClaudeHub did not return revisedBlocks")
    out = dict(baseline)
    for item in revised:
        if not isinstance(item, dict):
            continue
        block_id = str(item.get("blockId") or "")
        text = str(item.get("text") or "").strip()
        if block_id in baseline and text:
            out[block_id] = text
    return out


def _fallback_revision(baseline: dict[str, str], fallback: dict[str, str]) -> dict[str, str]:
    out = dict(baseline)
    out.update(fallback)
    return out


def _revision_prompt(result: RegulationParseResult, readiness: AgentReadinessResult, changes_for_revision: list) -> dict[str, Any]:
    changed_ids = {change.targetBlockId for change in changes_for_revision}
    source_blocks = [
        {
            "blockId": fragment.fragmentId,
            "section": fragment.section,
            "text": fragment.text,
        }
        for fragment in result.fragments
        if fragment.fragmentId in changed_ids
    ]
    changes = [
        {
            "changeId": change.changeId,
            "targetBlockId": change.targetBlockId,
            "before": change.before,
            "after": change.after,
            "reason": change.reason,
            "answer": change.source.get("answer", ""),
        }
        for change in changes_for_revision
    ]
    return {
        "instruction": (
            "Сформируй новую редакцию только указанных блоков регламента. "
            "Используй исключительно подтверждённые ответы пользователя и текст исходного блока. "
            "Не добавляй новые правила от себя, не меняй смысл незатронутых блоков. "
            "Верни только JSON с массивом revisedBlocks: [{blockId, section, text, explanation}]."
        ),
        "sourceDocument": {"fileName": result.fileName, "changedBlocks": source_blocks},
        "acceptedChanges": changes,
        "answers": [answer.model_dump(mode="json") for answer in readiness.answers],
        "responseSchema": {
            "revisedBlocks": [
                {
                    "blockId": "B-001",
                    "section": "5.2 Руководитель сектора",
                    "text": "Новая редакция пункта",
                    "explanation": "как использован ответ пользователя",
                }
            ]
        },
    }


def _write_docx(document_path: Path, result: RegulationParseResult, revised_blocks: dict[str, str], *, changed_ids: set[str]) -> None:
    try:
        from docx import Document
        from docx.enum.text import WD_COLOR_INDEX
    except ImportError as exc:
        raise RuntimeError("Для формирования DOCX требуется python-docx") from exc
    doc = Document()
    doc.add_heading(result.fileName, level=1)
    current_section = ""
    for fragment in result.fragments:
        if fragment.section and fragment.section != current_section:
            current_section = fragment.section
            doc.add_heading(current_section, level=2)
        paragraph = doc.add_paragraph()
        run = paragraph.add_run(revised_blocks.get(fragment.fragmentId, fragment.text))
        if fragment.fragmentId in changed_ids:
            run.font.highlight_color = WD_COLOR_INDEX.TURQUOISE
    doc.save(str(document_path))


def _write_pdf_revision_assets(
    *,
    source_path: Path,
    output_dir: Path,
    result: RegulationParseResult,
    revised_blocks: dict[str, str],
    diff_blocks: list[RevisionDiffBlock],
) -> tuple[Path | None, list[dict], list[dict]]:
    if source_path.suffix.casefold() != ".pdf" or not source_path.exists():
        return None, [], []
    try:
        import fitz
    except ImportError:
        return None, [], []

    changed_ids = {item.blockId for item in diff_blocks}
    fragments_by_id = {fragment.fragmentId: fragment for fragment in result.fragments}
    changed_fragments = [
        fragment for block_id in changed_ids if (fragment := fragments_by_id.get(block_id)) is not None
    ]
    pdf_path = output_dir / f"{source_path.stem}.ai-ready.pdf"
    try:
        with fitz.open(str(source_path)) as source:
            out = fitz.open()
            replace_pages = _pages_requiring_text_replacement(source, changed_fragments, result.isScan)
            for index in range(source.page_count):
                page_no = index + 1
                if page_no in replace_pages:
                    page = source[index]
                    new_page = out.new_page(width=page.rect.width, height=page.rect.height)
                    _write_text_page(new_page, _page_text(result, revised_blocks, page_no))
                else:
                    out.insert_pdf(source, from_page=index, to_page=index)
            for fragment in changed_fragments:
                if fragment.page in replace_pages:
                    continue
                _replace_fragment_text(out, fragment, revised_blocks.get(fragment.fragmentId, fragment.text))
            out.save(str(pdf_path), garbage=4, deflate=True)
            out.close()
    except Exception:
        return None, [], []

    source_pages = _render_pdf_preview_pages(source_path, output_dir / "preview" / "source")
    revised_pages = _render_pdf_preview_pages(pdf_path, output_dir / "preview" / "revised")
    return pdf_path, source_pages, revised_pages


def _pages_requiring_text_replacement(source, fragments, is_scan: bool) -> set[int]:
    pages: set[int] = set()
    for fragment in fragments:
        if is_scan:
            pages.add(fragment.page)
            continue
        if fragment.page < 1 or fragment.page > source.page_count:
            pages.add(fragment.page)
            continue
        page = source[fragment.page - 1]
        if not _usable_bbox(fragment.bbox, page.rect):
            pages.add(fragment.page)
    return pages


def _usable_bbox(bbox: list[float] | None, page_rect) -> bool:
    if not bbox or len(bbox) < 4:
        return False
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    if x1 <= x0 or y1 <= y0:
        return False
    if (x1 - x0) > page_rect.width * 0.85 and (y1 - y0) > page_rect.height * 0.85:
        return False
    return True


def _replace_fragment_text(doc, fragment, text: str) -> None:
    if fragment.page < 1 or fragment.page > doc.page_count or not _usable_bbox(fragment.bbox, doc[fragment.page - 1].rect):
        return
    import fitz

    page = doc[fragment.page - 1]
    rect = fitz.Rect(*[float(value) for value in fragment.bbox[:4]])
    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()
    fontsize = max(7.0, min(float(fragment.fontSize or 10.0), 12.0))
    page.insert_textbox(rect, text, fontsize=fontsize, color=(0, 0, 0), align=0, **_pdf_font_kwargs())


def _write_text_page(page, text: str) -> None:
    import fitz

    margin = 42
    rect = fitz.Rect(margin, margin, page.rect.width - margin, page.rect.height - margin)
    page.insert_textbox(
        rect,
        text or "Текст страницы недоступен.",
        fontsize=10,
        color=(0, 0, 0),
        align=0,
        **_pdf_font_kwargs(),
    )


def _pdf_font_kwargs() -> dict[str, str]:
    for font_path in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if font_path.is_file():
            return {"fontname": "revision-font", "fontfile": str(font_path)}
    return {"fontname": "helv"}


def _page_text(result: RegulationParseResult, revised_blocks: dict[str, str], page_no: int) -> str:
    lines = [
        revised_blocks.get(fragment.fragmentId, fragment.text)
        for fragment in result.fragments
        if fragment.page == page_no and (fragment.text or "").strip()
    ]
    return "\n\n".join(lines)


def _render_pdf_preview_pages(path: Path, target_dir: Path) -> list[dict]:
    try:
        import fitz
    except ImportError:
        return []
    target_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    with fitz.open(str(path)) as doc:
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            image_path = target_dir / f"page-{index:03d}.png"
            pix.save(str(image_path))
            pages.append({"page": index, "path": str(image_path)})
    return pages


def _preview_html(fragments, *, changed_ids: set[str]) -> str:
    items = []
    current_section = ""
    for fragment in fragments:
        if fragment.section and fragment.section != current_section:
            current_section = fragment.section
            items.append(f"<h3>{html.escape(current_section)}</h3>")
        cls = "changed" if fragment.fragmentId in changed_ids else "plain"
        items.append(f'<div class="block {cls}">{html.escape(fragment.text)}</div>')
    return "\n".join(
        [
            "<style>",
            "body{font-family:Segoe UI,Arial,sans-serif;color:#101817;background:#fff;}",
            ".block{padding:10px 12px;margin:8px 0;border-radius:12px;border:1px solid rgba(16,24,23,.08);}",
            ".changed{background:rgba(8,116,95,.08);border-color:rgba(8,116,95,.28);}",
            "h3{font-size:14px;margin:18px 0 8px;color:#06483D;}",
            "</style>",
            *items,
        ]
    )


def _diff_blocks(result: RegulationParseResult, revised_blocks: dict[str, str], accepted: list) -> list[RevisionDiffBlock]:
    by_id = {fragment.fragmentId: fragment for fragment in result.fragments}
    changed_ids = {change.targetBlockId for change in accepted}
    diff = []
    for block_id in changed_ids:
        fragment = by_id.get(block_id)
        before = fragment.text if fragment is not None else ""
        after = revised_blocks.get(block_id, before)
        if before.strip() == after.strip():
            continue
        diff.append(
            RevisionDiffBlock(
                blockId=block_id,
                section=fragment.section if fragment is not None else "",
                before=before,
                after=after,
                status="changed",
            )
        )
    return diff


def _fallback_revised_blocks(baseline: dict[str, str], changes: list) -> dict[str, str]:
    out = dict(baseline)
    for change in changes:
        block_id = change.targetBlockId
        if not block_id or not change.after.strip():
            continue
        before = (change.before or baseline.get(block_id, "")).strip()
        after = change.after.strip()
        addition = _addition_from_after(before, after)
        if not addition:
            out[block_id] = after
            continue
        current = out.get(block_id, before).strip()
        if addition not in current:
            out[block_id] = f"{current.rstrip()} {addition}".strip()
    return out


def _addition_from_after(before: str, after: str) -> str:
    if before and after.startswith(before):
        return after[len(before) :].strip()
    return after.strip()


def _protocol(readiness: AgentReadinessResult, diff_blocks: list[RevisionDiffBlock], message: str) -> str:
    payload = {
        "message": message,
        "readinessRunId": readiness.readinessRunId,
        "answers": [answer.model_dump(mode="json") for answer in readiness.answers],
        "diffBlocks": [item.model_dump(mode="json") for item in diff_blocks],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

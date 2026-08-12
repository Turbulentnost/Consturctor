from __future__ import annotations

import json

import pytest

from app.schemas.regulation import (
    AgentReadinessResult,
    ReadinessAnswer,
    RegulationChangeDraft,
    RegulationFragment,
    RegulationParseResult,
)
from app.services.regulation.pdf_text import extract_pdf_text
from app.services.readiness import revision_composer


def test_revision_composer_uses_claudehub_revised_blocks(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4")
    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="source.pdf",
        pageCount=1,
        recognitionQuality=1,
        fragments=[
            RegulationFragment(
                fragmentId="B-001",
                page=1,
                section="5.2 Руководитель сектора",
                text="Руководитель утверждает правила работы сектора.",
                bbox=[10, 20, 100, 40],
            )
        ],
    )
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        answers=[ReadinessAnswer(answerId="A-001", questionId="Q-001", answer="по поручению руководителя")],
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                source={"questionId": "Q-001", "answer": "по поручению руководителя"},
                targetBlockId="B-001",
                before="Руководитель утверждает правила работы сектора.",
                after="Руководитель утверждает правила работы сектора по поручению руководителя.",
                status="pending",
            )
        ],
    )

    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (
            json.dumps(
                {
                    "revisedBlocks": [
                        {
                            "blockId": "B-001",
                            "section": "5.2 Руководитель сектора",
                            "text": "Руководитель утверждает правила работы сектора по поручению руководителя.",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            "claude-sonnet-4.6",
        ),
    )

    document_path, protocol_path, _pdf_path, message, source_html, revised_html, diff_blocks, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert document_path.suffix == ".docx"
    assert document_path.is_file()
    assert protocol_path.is_file()
    assert "ClaudeHub" in message
    assert "changed" in revised_html
    assert source_html
    assert diff_blocks[0].blockId == "B-001"
    assert diff_blocks[0].page == 1
    assert diff_blocks[0].bbox == [10, 20, 100, 40]


def test_revision_composer_merges_pending_changes_for_same_block(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4")
    before = "Руководитель утверждает правила работы сектора."
    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="source.pdf",
        pageCount=1,
        recognitionQuality=1,
        fragments=[RegulationFragment(fragmentId="B-001", page=1, section="5.2", text=before)],
    )
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before=before,
                after=f"{before} Выполнение начинается: по поручению руководителя.",
                status="pending",
            ),
            RegulationChangeDraft(
                changeId="CH-002",
                targetBlockId="B-001",
                before=before,
                after=f"{before} Контроль выполнения: индивидуально по каждой задаче.",
                status="pending",
            ),
        ],
    )

    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    _document_path, _protocol_path, _pdf_path, _message, _source_html, _revised_html, diff_blocks, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert len(diff_blocks) == 1
    assert "Выполнение начинается" in diff_blocks[0].after
    assert "Контроль выполнения" in diff_blocks[0].after


def test_revision_composer_rejects_partial_llm_block(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4")
    before = "\n".join(
        [
            "- plans work;",
            "- assigns executors;",
            "- controls deadlines;",
            "- prepares reports;",
        ]
    )
    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="source.pdf",
        pageCount=1,
        recognitionQuality=1,
        fragments=[RegulationFragment(fragmentId="B-001", page=1, section="5.2", text=before)],
    )
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before=before,
                after=f"{before}\n- escalates missed milestones.",
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (
            json.dumps(
                {"revisedBlocks": [{"blockId": "B-001", "section": "5.2", "text": "- escalates missed milestones."}]}
            ),
            "claude-sonnet-4.6",
        ),
    )

    _document_path, _protocol_path, _pdf_path, _message, _source_html, _revised_html, diff_blocks, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert "- plans work;" in diff_blocks[0].after
    assert "- controls deadlines;" in diff_blocks[0].after
    assert "- escalates missed milestones." in diff_blocks[0].after


def test_revision_composer_creates_pdf_preview_and_preserves_unchanged_page(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")
    fitz = pytest.importorskip("fitz")

    source = tmp_path / "source.pdf"
    _write_sample_pdf(fitz, source, ["Original changed text", "Unchanged second page"])
    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="source.pdf",
        pageCount=2,
        recognitionQuality=1,
        fragments=[
            RegulationFragment(
                fragmentId="B-001",
                page=1,
                section="1",
                text="Original changed text",
                bbox=[48, 45, 260, 70],
                fontSize=11,
            ),
            RegulationFragment(fragmentId="B-002", page=2, section="2", text="Unchanged second page"),
        ],
    )
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before="Original changed text",
                after="Revised changed text",
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    _docx, _protocol, pdf_path, _message, _source_html, _revised_html, _diff, source_pages, revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert pdf_path is not None and pdf_path.is_file()
    assert len(source_pages) == 2
    assert len(revised_pages) == 2
    assert all((item["path"] and item["page"]) for item in revised_pages)
    with fitz.open(str(pdf_path)) as doc:
        assert doc.page_count == 2
        assert "Unchanged second page" in doc[1].get_text()


def test_revision_composer_uses_page_fallback_when_text_does_not_fit_bbox(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")
    fitz = pytest.importorskip("fitz")

    source = tmp_path / "source.pdf"
    _write_sample_pdf(fitz, source, ["Short source", "Second page intact"])
    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="source.pdf",
        pageCount=2,
        recognitionQuality=1,
        fragments=[
            RegulationFragment(
                fragmentId="B-001",
                page=1,
                section="1",
                text="Short source",
                bbox=[48, 45, 120, 58],
                fontSize=11,
            ),
            RegulationFragment(fragmentId="B-002", page=2, section="2", text="Second page intact"),
        ],
    )
    long_after = "Short source. " + "Additional regulation sentence. " * 12
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before="Short source",
                after=long_after,
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    _docx, _protocol, pdf_path, _message, _source_html, _revised_html, _diff, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert pdf_path is not None and pdf_path.is_file()
    with fitz.open(str(pdf_path)) as doc:
        assert "Additional regulation sentence" in doc[0].get_text().replace("\xa0", " ")
        assert "Second page intact" in doc[1].get_text()


def test_pdf_extraction_keeps_style_runs(tmp_path) -> None:
    fitz = pytest.importorskip("fitz")

    source = tmp_path / "styled.pdf"
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    page.insert_text((50, 60), "Styled heading", fontsize=16, fontname="hebo")
    page.insert_text((72, 90), "- regular item", fontsize=10, fontname="helv")
    doc.save(str(source))
    doc.close()

    extracted = extract_pdf_text(source)
    heading = next(block for block in extracted.blocks if "Styled heading" in block.text)

    assert heading.style_runs
    assert heading.font_size and heading.font_size >= 15
    assert heading.is_bold
    assert heading.style_runs[0]["fontSize"] >= 15


def test_revision_composer_reconstructs_styled_page(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")
    fitz = pytest.importorskip("fitz")

    source = tmp_path / "styled-source.pdf"
    _write_sample_pdf(fitz, source, ["Styled heading\n- original item", "Second page intact"])
    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="styled-source.pdf",
        pageCount=2,
        recognitionQuality=1,
        fragments=[
            RegulationFragment(
                fragmentId="B-H",
                page=1,
                section="1",
                text="Styled heading",
                bbox=[50, 45, 220, 65],
                fontSize=16,
                isBold=True,
                styleRuns=[
                    {
                        "text": "Styled heading",
                        "bbox": [50, 45, 220, 65],
                        "origin": [50, 60],
                        "fontName": "Helvetica-Bold",
                        "fontSize": 16,
                        "isBold": True,
                        "isItalic": False,
                        "color": 0,
                    }
                ],
            ),
            RegulationFragment(
                fragmentId="B-001",
                page=1,
                section="1",
                text="- original item",
                bbox=[72, 75, 150, 88],
                fontSize=10,
                styleRuns=[
                    {
                        "text": "- original item",
                        "bbox": [72, 75, 150, 88],
                        "origin": [72, 90],
                        "fontName": "Helvetica",
                        "fontSize": 10,
                        "isBold": False,
                        "isItalic": False,
                        "color": 0,
                    }
                ],
            ),
            RegulationFragment(fragmentId="B-002", page=2, section="2", text="Second page intact"),
        ],
    )
    after = "- original item\n- added item with preserved style"
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before="- original item",
                after=after,
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    _docx, _protocol, pdf_path, _message, _source_html, _revised_html, _diff, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert pdf_path is not None and pdf_path.is_file()
    with fitz.open(str(pdf_path)) as doc:
        first_page_text = " ".join(doc[0].get_text().replace("\xa0", " ").split())
        assert "Styled heading" in first_page_text
        assert "added item with preserved style" in first_page_text
        assert "Second page intact" in doc[-1].get_text()
        sizes = [
            round(float(span.get("size") or 0))
            for block in doc[0].get_text("dict").get("blocks") or []
            for line in block.get("lines") or []
            for span in line.get("spans") or []
        ]
        assert 16 in sizes
        assert 10 in sizes


def test_revision_composer_enriches_old_fragments_from_source_pdf(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")
    fitz = pytest.importorskip("fitz")

    source = tmp_path / "old-fragments.pdf"
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    page.insert_text((50, 60), "Styled heading", fontsize=16, fontname="hebo")
    page.insert_text((72, 90), "- original item", fontsize=10, fontname="helv")
    doc.save(str(source))
    doc.close()

    result = RegulationParseResult(
        regulationId="reg-revision",
        fileName="old-fragments.pdf",
        pageCount=1,
        recognitionQuality=1,
        fragments=[
            RegulationFragment(
                fragmentId="B-H",
                page=1,
                section="1",
                text="Styled heading",
                bbox=[50, 45, 220, 65],
                fontSize=12,
            ),
            RegulationFragment(
                fragmentId="B-001",
                page=1,
                section="1",
                text="- original item",
                bbox=[72, 75, 150, 88],
                fontSize=10,
            ),
        ],
    )
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-revision",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before="- original item",
                after="- original item\n- added item",
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    _docx, _protocol, pdf_path, _message, _source_html, _revised_html, _diff, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert pdf_path is not None and pdf_path.is_file()
    with fitz.open(str(pdf_path)) as revised:
        text = " ".join(revised[0].get_text().split())
        assert "Styled heading" in text
        assert "added item" in text
        sizes = [
            round(float(span.get("size") or 0))
            for block in revised[0].get_text("dict").get("blocks") or []
            for line in block.get("lines") or []
            for span in line.get("spans") or []
        ]
        assert 16 in sizes


def test_revision_composer_scan_fallback_replaces_only_changed_page(monkeypatch, tmp_path) -> None:
    pytest.importorskip("docx")
    fitz = pytest.importorskip("fitz")

    source = tmp_path / "scan.pdf"
    _write_sample_pdf(fitz, source, ["Scan page text", "Original page kept"])
    result = RegulationParseResult(
        regulationId="reg-scan",
        fileName="scan.pdf",
        pageCount=2,
        recognitionQuality=0.5,
        isScan=True,
        fragments=[
            RegulationFragment(fragmentId="B-001", page=1, section="1", text="Scan page text"),
            RegulationFragment(fragmentId="B-002", page=2, section="2", text="Original page kept"),
        ],
    )
    readiness = AgentReadinessResult(
        readinessRunId="ready-run",
        regulationId="reg-scan",
        roleMatchRunId="role-run",
        changes=[
            RegulationChangeDraft(
                changeId="CH-001",
                targetBlockId="B-001",
                before="Scan page text",
                after="Scan page revised text",
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        revision_composer,
        "_post_json_with_model",
        lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    _docx, _protocol, pdf_path, _message, _source_html, _revised_html, _diff, _source_pages, _revised_pages = (
        revision_composer.create_llm_revision_files(
            source_path=source,
            output_dir=tmp_path / "revision",
            result=result,
            readiness=readiness,
        )
    )

    assert pdf_path is not None and pdf_path.is_file()
    with fitz.open(str(pdf_path)) as doc:
        assert doc.page_count == 2
        assert "Original page kept" in doc[1].get_text()


def _write_sample_pdf(fitz, path, page_texts: list[str]) -> None:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=360, height=240)
        page.insert_text((50, 60), text, fontsize=11)
    doc.save(str(path))
    doc.close()

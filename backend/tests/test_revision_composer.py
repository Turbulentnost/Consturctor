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
        "_post_json",
        lambda _payload, timeout: json.dumps(
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
    )

    document_path, protocol_path, message, source_html, revised_html, diff_blocks = (
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

    monkeypatch.setattr(revision_composer, "_post_json", lambda _payload, timeout: (_ for _ in ()).throw(RuntimeError("offline")))

    _document_path, _protocol_path, _message, _source_html, _revised_html, diff_blocks = (
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

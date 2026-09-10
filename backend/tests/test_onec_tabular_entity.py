"""OData tabular document entities must not use Date orderby."""

from __future__ import annotations

from app.services.onec_tools import _is_tabular_document_entity


def test_tabular_protocol_sections_detected() -> None:
    assert _is_tabular_document_entity("Document_ТД_Протокол_Решения")
    assert _is_tabular_document_entity("Document_ТД_Протокол_ПовесткаСовещания")
    assert not _is_tabular_document_entity("Document_ТД_Протокол")

from __future__ import annotations

from app.tools.ac.workers.onec_com_actions import (
    _is_selectable_field_name,
    _local_document_metadata_names,
    _local_odata_snapshot_path,
    _odata_metadata_name,
    _score_local_metadata_name,
)


def test_meeting_fields_are_selectable() -> None:
    assert _is_selectable_field_name("Инициатор")
    assert _is_selectable_field_name("Участники")
    assert _is_selectable_field_name("Длительность")
    assert _is_selectable_field_name("ФорматСовещания")
    assert _is_selectable_field_name("ВремяПроведения")
    assert _is_selectable_field_name("ТемаСлужебнойЗаписки")


def test_local_snapshot_scores_document_types() -> None:
    assert _odata_metadata_name("Document_ТД_СлужебнаяЗаписка") == "ТД_СлужебнаяЗаписка"
    assert _score_local_metadata_name("служебная записка", "ТД_СлужебнаяЗаписка") >= 50
    assert _score_local_metadata_name("000013243", "ТД_СлужебнаяЗаписка") == 0


def test_local_snapshot_lists_erp_documents() -> None:
    path = _local_odata_snapshot_path()
    if path is None:
        return
    names = _local_document_metadata_names()
    assert "ТД_СлужебнаяЗаписка" in names
    assert "ТД_Поручения" in names
    assert "ТД_Протокол" in names

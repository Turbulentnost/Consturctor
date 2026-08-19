from __future__ import annotations

from app.tools.ac.workers.onec_com_actions import _is_selectable_field_name


def test_meeting_fields_are_selectable() -> None:
    assert _is_selectable_field_name("Инициатор")
    assert _is_selectable_field_name("Участники")
    assert _is_selectable_field_name("Длительность")
    assert _is_selectable_field_name("ФорматСовещания")
    assert _is_selectable_field_name("ВремяПроведения")
    assert _is_selectable_field_name("ТемаСлужебнойЗаписки")

from app.services.calendar_overlay import normalize_meetings


def test_normalize_meetings_keeps_people_and_substitutes() -> None:
    items = normalize_meetings(
        [
            {
                "title": "Предложение комиссии по займам",
                "start": "2026-09-09T10:00:00+03:00",
                "end": "2026-09-09T10:30:00+03:00",
                "mark": "keep",
                "organizer": "Комарькова",
                "attendees": ["Иванов И.И.", {"fio": "Петров П.П."}],
                "optional_attendees": ["Сидоров"],
                "substitutes": [{"who": "Кузнецов", "instead_of": "Орлов"}],
                "reason": "оставить",
            }
        ]
    )
    assert len(items) == 1
    row = items[0]
    assert row["title"] == "Предложение комиссии по займам"
    assert row["organizer"] == "Комарькова"
    assert row["attendees"] == ["Иванов И.И.", "Петров П.П.", "Сидоров"]
    assert row["substitutes"] == ["Кузнецов замещает Орлов"]
    assert row["reason"] == "оставить"

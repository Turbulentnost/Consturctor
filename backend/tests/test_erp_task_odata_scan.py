from __future__ import annotations

from app.services.erp_task_odata_scan import (
    ROLE_AUTHOR,
    ROLE_EXECUTOR,
    classify_my_task_row,
    row_matches_user_ref,
    scan_task_zadacha_ispolnitelya,
)


def test_row_matches_user_ref_on_ispolnitel_guid() -> None:
    ref = "41290a43-5990-11f1-980e-6cb31113810e"
    row = {"Исполнитель": ref.upper(), "Автор": "00000000-0000-0000-0000-000000000002"}
    assert row_matches_user_ref(row, "Исполнитель", ref)
    assert classify_my_task_row(row, user_ref=ref, fio="Жалыбин М. Д.") == ROLE_EXECUTOR


def test_classify_author_as_from_me() -> None:
    ref = "41290a43-5990-11f1-980e-6cb31113810e"
    row = {"Исполнитель": "00000000-0000-0000-0000-000000000003", "Автор": ref}
    assert classify_my_task_row(row, user_ref=ref, fio="Жалыбин") == ROLE_AUTHOR


def test_scan_paginates_and_maps_roles() -> None:
    ref = "41290a43-5990-11f1-980e-6cb31113810e"
    pages = [
        {
            "value": [
                {
                    "Ref_Key": "a1",
                    "Number": "1",
                    "Description": "мне",
                    "Executed": False,
                    "Исполнитель": ref,
                    "Date": "2026-01-01T00:00:00",
                },
                {
                    "Ref_Key": "a2",
                    "Number": "2",
                    "Description": "от меня",
                    "Executed": False,
                    "Автор": ref,
                    "Date": "2026-01-02T00:00:00",
                },
            ]
        },
        {"value": []},
    ]

    def fetch_page(_entity: str, *, params: dict) -> dict:
        skip = int(params.get("$skip") or 0)
        return pages[0] if skip == 0 else pages[1]

    mapped, warning = scan_task_zadacha_ispolnitelya(
        user_ref=ref,
        fio="Жалыбин",
        limit=10,
        fetch_page=fetch_page,
        map_row=lambda row, role: {"number": row["Number"], "source": role},
    )
    assert warning == ""
    roles = {item["number"]: item["source"] for item in mapped}
    assert roles["1"] == ROLE_EXECUTOR
    assert roles["2"] == ROLE_AUTHOR

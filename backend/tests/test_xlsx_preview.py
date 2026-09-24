from io import BytesIO

from openpyxl import Workbook

from app.services.workflows.document import extract_xlsx_preview


def test_extract_xlsx_preview_reads_banner_kpis_and_table() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "ActionTracker"
    sheet["A1"] = "ActionTracker — единый журнал поручений"
    sheet["A2"] = "Заказчик Амураль Игорь Борисович"
    sheet["A3"] = "Открытых карточек"
    sheet["B3"] = "Просроченных карточек"
    sheet["A4"] = 13
    sheet["B4"] = 6
    sheet["A6"] = "ID"
    sheet["B6"] = "Статус"
    sheet["C6"] = "Поручение"
    sheet["A7"] = "ACT-0001"
    sheet["B7"] = "IN PROGRESS"
    sheet["C7"] = "Служебное расследование"
    raw = BytesIO()
    book.save(raw)
    preview = extract_xlsx_preview(raw.getvalue())
    assert preview
    sheet_out = preview["sheets"][0]
    assert sheet_out["name"] == "ActionTracker"
    assert "единый журнал" in sheet_out["title"]
    assert sheet_out["kpis"][0]["value"] == "13"
    assert sheet_out["headers"][:3] == ["ID", "Статус", "Поручение"]
    assert sheet_out["rows"][0][0] == "ACT-0001"

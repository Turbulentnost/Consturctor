"""OData документооборота: URL, маппинг задач, без живого /doc."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.docflow_tasks import (
    _map_task,
    _parse_odata_dt,
    docflow_base_url,
)


def test_docflow_base_url_from_erp(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.docflow_tasks.settings",
        SimpleNamespace(docflow_odata_base_url="", odata_base_url="http://host/erp_pm/odata/standard.odata"),
    )
    assert docflow_base_url() == "http://host/doc/odata/standard.odata"


def test_docflow_base_url_explicit(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.docflow_tasks.settings",
        SimpleNamespace(
            docflow_odata_base_url="http://host/doc/odata/standard.odata/",
            odata_base_url="http://host/erp_pm/odata/standard.odata",
        ),
    )
    assert docflow_base_url() == "http://host/doc/odata/standard.odata"


def test_parse_odata_dt_skips_empty() -> None:
    assert _parse_odata_dt("") is None
    assert _parse_odata_dt("0001-01-01T00:00:00") is None
    parsed = _parse_odata_dt("2026-08-17T12:00:00")
    assert parsed == datetime(2026, 8, 17, 12, 0, 0)


def test_map_task_marks_source_and_late() -> None:
    row = {
        "Number": "38",
        "Description": "Исполнить задачу №2",
        "Executed": False,
        "Date": "2026-08-10T09:00:00",
        "СрокИсполнения": "2026-08-12T18:00:00",
        "ДатаИсполнения": "",
        "Описание": "протокол",
        "СостояниеБизнесПроцесса": "",
    }
    item = _map_task(row, fio="Мангасарян Давид Каренович")
    assert item["source"] == "документооборот"
    assert item["done"] is False
    assert item["late"] is False
    assert item["title"] == "Исполнить задачу №2"
    assert item["performer"] == "Мангасарян Давид Каренович"

    done = dict(row)
    done["Executed"] = True
    done["ДатаИсполнения"] = "2026-08-13T10:00:00"
    late = _map_task(done, fio="X")
    assert late["done"] is True
    assert late["late"] is True

from __future__ import annotations

from app.services.act_porucheniya_odata import (
    _normalize_basis,
    is_act_number,
    normalize_act_number,
)
from app.services.act_porucheniya_report import (
    criticality_for_deadline,
    is_act_porucheniya_workflow,
    workflow_runtime_kind,
)
from app.models.workflow import Workflow


def test_normalize_act_number_cyrillic_to_latin() -> None:
    assert normalize_act_number("АСТ00-00088") == "ACT00-00088"
    assert normalize_act_number("ACT00-00001") == "ACT00-00001"


def test_is_act_number() -> None:
    assert is_act_number("АСТ00-00088")
    assert is_act_number("ACT00-00001")
    assert not is_act_number("00-Л-000036795")


def test_is_act_porucheniya_workflow_reads_local_run_runtime() -> None:
    wf = Workflow(
        id="wf-act-local",
        title="ACT agent",
        plan_json={"goal": "Excel на рабочий стол"},
        local_run={"runtime": {"kind": "act_porucheniya"}},
    )
    assert workflow_runtime_kind(wf) == "act_porucheniya"
    assert is_act_porucheniya_workflow(wf)


def test_is_act_porucheniya_workflow_detects_act_seed() -> None:
    wf = Workflow(
        id="wf-act",
        title="ACT registry porucheniya",
        plan_json={
            "goal": "реестр поручений ACT Document_ТД_Поручения",
            "runtime": {"kind": "act_porucheniya"},
        },
    )
    assert is_act_porucheniya_workflow(wf)


def test_normalize_basis_hides_guid() -> None:
    assert _normalize_basis("поручение Амураль И.Б.") == "поручение Амураль И.Б."
    assert _normalize_basis("1d84958c-7c49-11f1-983d-c0123456789a") == ""


def test_row_fill_accepted_is_green() -> None:
    from app.services.act_porucheniya_report import row_fill_for_document

    fill = row_fill_for_document({"status": "Принято", "final_deadline_raw": "2020-01-01"})
    assert fill == "FF81C784"


def test_format_act_status_1c() -> None:
    from app.services.act_porucheniya_report import format_act_status_1c

    assert format_act_status_1c("ВРаботе") == "В работе"
    assert format_act_status_1c("Принято") == "Принято"
    assert format_act_status_1c("Создано") == "Создано"
    assert format_act_status_1c("", source="protocol") == "Из протокола"


def test_row_fill_protocol_uses_criticality_not_blue() -> None:
    from app.services.act_porucheniya_report import row_fill_for_task_row

    overdue = row_fill_for_task_row(
        {
            "source": "protocol",
            "status": "В работе",
            "task_deadline_raw": "2020-01-01T00:00:00",
        }
    )
    assert overdue == "FFFFCDD2"
    future = row_fill_for_task_row(
        {
            "source": "protocol",
            "status": "Из протокола",
            "task_deadline_raw": "2099-12-31T00:00:00",
        }
    )
    assert future == "FFA5D6A7"


def test_task_implies_act_registry() -> None:
    from app.services.act_porucheniya_report import task_implies_act_registry

    assert task_implies_act_registry(
        "Выгрузи реестр поручений ACT через OData Document_ТД_Поручения"
    )


def test_fetch_act_registry_emits_progress(monkeypatch) -> None:
    from app.services import act_porucheniya_odata as mod

    monkeypatch.setattr(mod, "odata_ready", lambda: True)

    sample_doc = {
        "ref_key": "a",
        "number": "ACT00-00001",
        "number_display": "ACT00-00001",
        "task_lines": [{"executor_key": "00000000-0000-0000-0000-000000000001", "task": "t"}],
        "task_line_count": 1,
    }

    def fake_fetch_page(**kwargs):
        _ = kwargs
        return [sample_doc], "path"

    progress: list[str] = []
    monkeypatch.setattr(mod, "_fetch_page", fake_fetch_page)
    monkeypatch.setattr(mod, "resolve_task_line_executors", lambda docs, **kw: None)

    payload = mod.fetch_act_porucheniya_registry(on_progress=progress.append)
    assert payload["count"] == 1
    assert any("страницы 1" in msg for msg in progress)
    assert any("получено 1 документов" in msg for msg in progress)


def test_fio_initials_slug() -> None:
    from app.services.fio_utils import fio_initials_slug

    assert fio_initials_slug("Жалыбин Максим Дмитриевич") == "ЖМД"
    assert fio_initials_slug("Иванов Иван") == "ИИ"
    assert fio_initials_slug("") == "user"


def test_build_act_excel_reformat_from_read() -> None:
    from app.services.act_porucheniya_report import build_act_excel_reformat_arguments

    payload = {
        "sheet": "Задачи ACT",
        "rows": [
            ["Номер ACT", "Задача", "Исполнитель", "Срок", "Статус"],
            ["ACT00-00001", "Test", "Иванов", "01.01.2020", "В работе"],
        ],
    }
    args = build_act_excel_reformat_arguments(
        payload,
        workflow_id="b11f1175-0000-0000-0000-000000000000",
        actor_fio="Иванов И.И.",
    )
    assert args is not None
    assert len(args["rows"]) == 1
    assert len(args["row_fills"]) == 1
    assert args["row_fills"][0] == "FFFFCDD2"


def test_build_act_excel_one_row_per_task_line() -> None:
    from app.services.act_porucheniya_report import build_act_excel_arguments

    docs = [
        {
            "number_display": "ACT00-00069",
            "date": "10.07.2026",
            "about": "О разработке регламентов",
            "status": "Принято",
            "task_lines": [
                {
                    "line_number": 1,
                    "task": "Разработать проекты регламентов",
                    "executor": "Тищенко Марина Николаевна",
                    "deadline": "31.07.2026",
                    "deadline_raw": "2026-07-31T00:00:00",
                },
                {
                    "line_number": 2,
                    "task": "Представить ПСД проекты",
                    "executor": "Тищенко Марина Николаевна",
                    "deadline": "31.07.2026",
                    "deadline_raw": "2026-07-31T00:00:00",
                },
            ],
        }
    ]
    args = build_act_excel_arguments(workflow_id="b11f1175-0000-0000-0000-000000000000", documents=docs)
    assert args["sheet"] == "Задачи ACT"
    assert len(args["rows"]) == 2
    assert args["rows"][0][0] == "ACT00-00069"
    assert args["rows"][0][1] == "Разработать проекты регламентов"
    assert args["rows"][0][2] == "Тищенко Марина Николаевна"
    assert args["rows"][0][3] == "31.07.2026"
    assert args["rows"][0][4] == "Принято"


def test_format_task_lines_for_doc() -> None:
    from app.services.act_porucheniya_report import format_task_lines_for_doc

    doc = {
        "task_lines": [
            {
                "line_number": 1,
                "task": "Задача А",
                "executor": "Иванов И.И.",
                "deadline": "01.01.2026",
            }
        ]
    }
    text = "\n".join(format_task_lines_for_doc(doc))
    assert "1. Задача А" in text
    assert "Исполнитель: Иванов И.И." in text


def test_criticality_for_deadline_critical() -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 8, 18, tzinfo=timezone.utc).replace(tzinfo=None)
    crit = criticality_for_deadline("2026-08-19T00:00:00", now=now)
    assert crit["level"] == "critical"

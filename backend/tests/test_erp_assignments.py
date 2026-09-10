"""Journal of assignments AST00 via OData."""

from __future__ import annotations

from datetime import datetime

from app.models.workflow import Workflow
from app.services.erp_assignments import (
    ASSIGNMENT_ENTITY,
    PROBE_MARK,
    build_assignment_filter,
    build_create_body,
    handle_assignments,
    pick_user_row,
    probe_assignment_write,
    stub_assignments,
    stub_write_probe,
)
from app.services.workflow_tool_routing import collect_write_intents, draft_needs_onec_write
from app.services.local_mcp import list_tools
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.prompts import write_recipe_prompt_text
from app.services.workflows.service import _tools_for_published_plan
from app.services.onec_tools import (
    ONEC_TOOLS,
    ONEC_WRITE_TOOLS,
    OnecToolError,
    _format_catalog,
    _parse_top_limit,
    _stub_catalog_items,
    invoke_onec,
    odata_configured,
)


def _is_onec_acl_error(exc: OnecToolError) -> bool:
    text = str(exc)
    return "401" in text or "Доступ запрещен" in text


def test_pick_user_row_prefers_exact_fio() -> None:
    rows = [
        {"Description": "Кожанов-Амураль Иван Петрович", "Ref_Key": "other"},
        {"Description": "Амураль Игорь Борисович", "Ref_Key": "amural"},
    ]
    chosen = pick_user_row(rows, "Амураль Игорь Борисович")
    assert chosen is not None
    assert chosen["Ref_Key"] == "amural"


def test_filter_uses_cyrillic_prefix_and_leader() -> None:
    filt = build_assignment_filter(
        customer_key="4c6b539d-5606-11e0-b816-008048428575",
        changed_since=datetime(2026, 9, 10),
    )
    assert "startswith(Number,'АСТ')" in filt
    assert "ACT" not in filt
    assert "Руководитель_Key eq guid'4c6b539d-5606-11e0-b816-008048428575'" in filt
    assert "Создано" in filt
    assert "ВРаботе" in filt
    assert "2026-09-10T00:00:00" in filt


def test_create_body_builds_lines() -> None:
    body = build_create_body(
        {
            "topic": "Novoe poruchenie",
            "customer_key": "4c6b539d-5606-11e0-b816-008048428575",
            "due": "2026-09-20",
            "lines": [
                {
                    "text": "Punkt",
                    "executor_key": "11111111-1111-1111-1111-111111111111",
                }
            ],
        }
    )
    assert body["ОЧем"] == "Novoe poruchenie"
    assert body["Основание_Type"] == "Edm.String"
    assert body["Статус"] == "Создано"
    assert body["Руководитель_Key"] == "4c6b539d-5606-11e0-b816-008048428575"
    assert body["Поручения"][0]["Мероприятие"] == "Punkt"


def test_stub_assignments_list() -> None:
    result = stub_assignments({"action": "list", "customer": "Amural I.B."})
    assert result["source"] == "stub"
    assert result["count"] == 1
    assert str(result["assignments"][0]["number"]).startswith("АСТ")


def test_draft_needs_write_for_status_change() -> None:
    draft = {
        "steps": [
            {
                "title": "Сменить статус поручения",
                "system": "onec",
                "entity": "assignment",
                "operation": "update",
            }
        ]
    }
    assert draft_needs_onec_write(draft)
    assert not draft_needs_onec_write(
        {
            "steps": [
                {
                    "title": "Список открытых поручений",
                    "system": "onec",
                    "entity": "assignment",
                    "operation": "list",
                }
            ]
        }
    )


def test_write_intents_cover_any_onec_mutation() -> None:
    draft = {
        "steps": [
            {
                "title": "Поменять статус протокола",
                "system": "onec",
                "entity": "protocol",
                "operation": "update",
            },
            {
                "title": "Список поручений по статусу",
                "system": "onec",
                "entity": "assignment",
                "operation": "list",
            },
        ]
    }
    intents = collect_write_intents(draft)
    assert len(intents) == 1
    assert intents[0].family == "odata"
    assert intents[0].odata_entity == "Document_ТД_Протокол"
    assert draft_needs_onec_write(
        {
            "steps": [
                {
                    "title": "Создать документ в 1С",
                    "system": "onec",
                    "entity": "odata_entity",
                    "operation": "create",
                    "tool_candidates": ["onec.odata_post"],
                }
            ]
        }
    )


def test_write_recipe_prompt_remembers_mechanism() -> None:
    text = write_recipe_prompt_text(
        {
            "ok": True,
            "test_number": "АСТ00-09999",
            "recipe": {
                "tool": "onec.erp_assignments_write",
                "update_status": {"field": "Статус"},
            },
        }
    )
    assert "АСТ00-09999" in text
    assert "onec.erp_assignments_write" in text
    assert "CONSTRUCTOR_PROBE" in text or "тестовое" in text.casefold()


def test_stub_write_probe_recipe() -> None:
    result = stub_write_probe({})
    assert result["ok"] is True
    assert result["cleaned"] is True
    assert result["recipe"]["update_status"]["field"] == "Статус"
    assert result["recipe"]["tool"] == "onec.erp_assignments_write"


def test_write_probe_creates_updates_and_deletes(monkeypatch) -> None:
    customer_key = "4c6b539d-5606-11e0-b816-008048428575"
    created = {"Ref_Key": "b75214dc-a846-11f1-9877-6cb31113810c", "Number": "АСТ00-09999"}
    status = {"value": "Создано"}
    deleted: list[str] = []

    def fake_odata_get(args: dict) -> dict:
        entity = str(args.get("entity") or "")
        if entity == "Catalog_Пользователи":
            return {
                "value": [{"Description": "Тест Тестович", "Ref_Key": customer_key}],
                "source": "odata",
            }
        if entity == ASSIGNMENT_ENTITY and args.get("ref_key"):
            return {
                "value": [
                    {
                        "Number": "АСТ00-09999",
                        "Ref_Key": created["Ref_Key"],
                        "Статус": status["value"],
                        "ОЧем": f"{PROBE_MARK} wf",
                        "Руководитель_Key": customer_key,
                    }
                ],
                "source": "odata",
            }
        return {"value": [], "source": "odata"}

    def fake_post(args: dict) -> dict:
        assert args["entity"] == ASSIGNMENT_ENTITY
        assert PROBE_MARK in str((args.get("body") or {}).get("ОЧем") or "")
        return {"data": created, "erp_document_id": created["Ref_Key"], "source": "odata"}

    def fake_patch(args: dict) -> dict:
        body = args.get("body") or {}
        if body.get("Статус"):
            status["value"] = body["Статус"]
        if body.get("DeletionMark"):
            deleted.append(str(args.get("ref_key") or ""))
        return {"updated": True, "ref_key": args.get("ref_key"), "source": "odata"}

    monkeypatch.setattr("app.services.erp_assignments._odata_get", fake_odata_get)
    monkeypatch.setattr("app.services.erp_assignments._odata_post", fake_post)
    monkeypatch.setattr("app.services.erp_assignments._odata_patch", fake_patch)
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: True)

    result = probe_assignment_write({"customer": "Тест Тестович", "workflow_id": "wf-1"})
    assert result["ok"] is True
    assert result["cleaned"] is True
    assert result["test_left"] is False
    assert result["recipe"]["update_status"]["field"] == "Статус"
    assert created["Ref_Key"] in deleted
    assert status["value"] == "ВРаботе"


def test_write_probe_deletes_on_failure(monkeypatch) -> None:
    customer_key = "4c6b539d-5606-11e0-b816-008048428575"
    created_key = "b75214dc-a846-11f1-9877-6cb31113810c"
    deleted: list[str] = []

    def fake_odata_get(args: dict) -> dict:
        entity = str(args.get("entity") or "")
        if entity == "Catalog_Пользователи":
            return {
                "value": [{"Description": "Тест Тестович", "Ref_Key": customer_key}],
                "source": "odata",
            }
        if entity == ASSIGNMENT_ENTITY and args.get("ref_key"):
            return {
                "value": [
                    {
                        "Number": "АСТ00-09999",
                        "Ref_Key": created_key,
                        "Статус": "Создано",
                        "ОЧем": PROBE_MARK,
                    }
                ],
                "source": "odata",
            }
        return {"value": [], "source": "odata"}

    monkeypatch.setattr("app.services.erp_assignments._odata_get", fake_odata_get)
    monkeypatch.setattr(
        "app.services.erp_assignments._odata_post",
        lambda args: {"data": {"Ref_Key": created_key, "Number": "АСТ00-09999"}},
    )

    def fake_patch(args: dict) -> dict:
        body = args.get("body") or {}
        if body.get("Статус"):
            raise RuntimeError("status field rejected")
        if body.get("DeletionMark"):
            deleted.append(str(args.get("ref_key") or ""))
        return {"updated": True, "source": "odata"}

    monkeypatch.setattr("app.services.erp_assignments._odata_patch", fake_patch)
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: True)

    result = probe_assignment_write({"customer": "Тест Тестович"})
    assert result["ok"] is False
    assert created_key in deleted
    assert result["cleaned"] is True


def test_published_assignment_agent_gets_odata_and_excel_tools() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Ежедневный контроль поручений по 1С ERP и Excel",
            "goal": "Сверка журнала АСТ00 и Action Tracker",
            "runtime": {"kind": "onec"},
        }
    )
    workflow = Workflow(
        id="wf-at",
        user_id="user-1",
        title=plan.title,
        notes="Action Tracker xlsx",
        plan_json=plan.to_dict(),
    )
    tools = _tools_for_published_plan(plan, workflow)
    assert "onec.erp_assignments" in tools
    assert "onec.erp_assignments_write" in tools
    assert "excel.read_workbook" in tools
    assert "onec.erp_tasks_current" not in tools


def test_published_my_1c_tasks_agent_gets_erp_tasks() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Мои задачи исполнителя в 1С",
            "goal": "Показать текущие задачи пользователя",
            "runtime": {"kind": "onec"},
        }
    )
    workflow = Workflow(
        id="wf-tasks",
        user_id="user-1",
        title=plan.title,
        notes="задачи исполнителя из erp_pm",
        plan_json=plan.to_dict(),
    )
    tools = _tools_for_published_plan(plan, workflow)
    assert "onec.erp_tasks_current" in tools


def test_tools_registered() -> None:
    assert "onec.erp_assignments" in ONEC_TOOLS
    assert "onec.erp_assignments_write" in ONEC_WRITE_TOOLS
    assert "onec.erp_write_probe" in ONEC_TOOLS
    assert "onec.erp_write_probe" not in ONEC_WRITE_TOOLS
    names = {item["name"] for item in list_tools()}
    assert "onec.erp_assignments" in names
    assert "onec.erp_assignments_write" in names
    assert "onec.download_artifact" in names
    assert "onec.download_artifact" in ONEC_TOOLS
    assert "onec.download_artifact" not in ONEC_WRITE_TOOLS
    read_tool = next(item for item in list_tools() if item["name"] == "onec.erp_assignments")
    assert read_tool.get("execution") == "server"
    assert read_tool.get("entity") == "assignment"


def test_catalog_documents_before_catalogs() -> None:
    catalogs_first = sorted(
        _stub_catalog_items(),
        key=lambda row: 0 if row["kind"] == "catalog" else 1,
    )
    result = _format_catalog(catalogs_first, {"limit": 20}, source="stub")
    kinds = [item["kind"] for item in result["entities"]]
    assert "document" in kinds
    assert kinds[0] == "document"
    names = [item["name"] for item in result["entities"]]
    assert ASSIGNMENT_ENTITY in names


def test_catalog_search_finds_assignment_document() -> None:
    result = _format_catalog(
        _stub_catalog_items(),
        {"kind": "document", "search": "поруч", "limit": 20},
        source="stub",
    )
    names = [item["name"] for item in result["entities"]]
    assert ASSIGNMENT_ENTITY in names


def test_assignment_entity_default_top() -> None:
    assert _parse_top_limit("", {"entity": ASSIGNMENT_ENTITY}) == 40
    assert _parse_top_limit("", {"entity": "Catalog_Контрагенты"}) == 3


def test_list_normalizes_card(monkeypatch) -> None:
    customer_key = "4c6b539d-5606-11e0-b816-008048428575"
    executor_key = "11111111-1111-1111-1111-111111111111"

    def fake_odata(args: dict) -> dict:
        entity = str(args.get("entity") or "")
        filt = str(args.get("filter") or "")
        if entity == "Catalog_Пользователи" and "substringof" in filt:
            return {
                "value": [
                    {
                        "Description": "Кожанов-Амураль Иван Петрович",
                        "Ref_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    },
                    {"Description": "Амураль Игорь Борисович", "Ref_Key": customer_key},
                ],
                "source": "odata",
            }
        if entity == "Catalog_Пользователи":
            return {
                "value": [{"Description": "Иванов Иван", "Ref_Key": executor_key}],
                "source": "odata",
            }
        if entity == ASSIGNMENT_ENTITY:
            return {
                "value": [
                    {
                        "Number": "АСТ00-00093",
                        "Ref_Key": "b75214dc-a846-11f1-9877-6cb31113810c",
                        "Date": "2026-09-10T09:00:00",
                        "Posted": True,
                        "ОЧем": "Tema",
                        "Статус": "ВРаботе",
                        "Руководитель_Key": customer_key,
                        "Руководитель_Name": "Амураль Игорь Борисович",
                        "Поручения": [
                            {
                                "LineNumber": "1",
                                "Мероприятие": "Sdelat",
                                "СрокИсполнения": "2026-09-20T00:00:00",
                                "ОтветственноеЛицо_Key": executor_key,
                                "Приоритет": "",
                            }
                        ],
                    }
                ],
                "source": "odata",
            }
        return {"value": [], "source": "odata"}

    monkeypatch.setattr("app.services.erp_assignments._odata_get", fake_odata)
    result = handle_assignments(
        {
            "action": "list",
            "customer": "Амураль Игорь Борисович",
            "limit": 5,
        }
    )
    assert result["customer_key"] == customer_key
    assert result["assignments"][0]["number"] == "АСТ00-00093"
    assert result["assignments"][0]["lines"][0]["text"] == "Sdelat"
    assert result["assignments"][0]["lines"][0]["executor"] == "Иванов Иван"
    assert "startswith(Number,'АСТ')" in result["filter"]


def test_list_tasks_has_no_default_check_assignment_title(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_odata_get(args: dict) -> dict:
        captured["filter"] = str(args.get("filter") or "")
        return {"value": [], "source": "odata"}

    monkeypatch.setattr("app.services.erp_assignments._odata_get", fake_odata_get)
    result = handle_assignments({"action": "tasks", "limit": 5})
    filt = captured.get("filter") or ""
    assert "Проверить поручение" not in filt
    assert "substringof" not in filt
    assert result["query"] == ""
    hint = str(result.get("hint") or "")
    assert "action=list" in hint
    assert "erp_tasks_current" not in hint


def test_live_or_stub_list() -> None:
    try:
        result = invoke_onec(
            "onec.erp_assignments",
            {
                "action": "list",
                "customer": "Амураль Игорь Борисович",
                "limit": 5,
            },
        )
    except OnecToolError as exc:
        if odata_configured() and _is_onec_acl_error(exc):
            return
        raise
    assert result.get("count", 0) >= 0
    if result.get("source") == "stub":
        assert result["assignments"][0]["number"].startswith("АСТ")
        return
    assert result.get("entity") == ASSIGNMENT_ENTITY
    if result.get("assignments"):
        assert str(result["assignments"][0]["number"]).startswith("АСТ")

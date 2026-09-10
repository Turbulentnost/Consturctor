"""Constructor write-probe rule: any 1C mutation, throwaway object, then delete."""

from app.services.erp_assignments import PROBE_MARK
from app.services.onec_write_probe import (
    probe_odata_entity_write,
    probe_onec_writes,
    recipe_covers_intents,
    stub_write_probe,
)


def test_recipe_covers_intents_requires_same_keys() -> None:
    assert recipe_covers_intents(
        {"ok": True, "intent_keys": ["assignment:update:status:Document_X"]},
        ["assignment:update:status:Document_X"],
    )
    assert not recipe_covers_intents(
        {"ok": True, "recipe": {"tool": "onec.erp_assignments_write"}},
        ["assignment:update:status:Document_X"],
    )
    assert not recipe_covers_intents(
        {"ok": True, "intent_keys": ["assignment:update:status:Document_X"]},
        ["odata:update:status:Document_Y"],
    )


def test_stub_probe_keeps_assignment_recipe() -> None:
    result = stub_write_probe({})
    assert result["ok"] is True
    assert result["cleaned"] is True
    assert result["recipe"]["tool"] == "onec.erp_assignments_write"


def test_generic_odata_probe_creates_updates_and_deletes(monkeypatch) -> None:
    entity = "Document_ТД_Протокол"
    created = {"Ref_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "Number": "ПСД-1"}
    field_value = {"Тема": PROBE_MARK}
    deleted: list[str] = []

    def fake_get(args: dict) -> dict:
        if args.get("ref_key"):
            return {
                "value": [
                    {
                        "Ref_Key": created["Ref_Key"],
                        "Number": created["Number"],
                        "Тема": field_value["Тема"],
                        "DeletionMark": False,
                    }
                ]
            }
        if "filter" in args:
            return {"value": []}
        return {
            "value": [
                {
                    "Ref_Key": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "Number": "OLD",
                    "Тема": "Live",
                    "Date": "2026-09-01T00:00:00",
                }
            ]
        }

    def fake_post(args: dict) -> dict:
        assert args["entity"] == entity
        assert PROBE_MARK in str((args.get("body") or {}).get("Тема") or "")
        return {"data": created, "erp_document_id": created["Ref_Key"]}

    def fake_patch(args: dict) -> dict:
        body = args.get("body") or {}
        if body.get("Тема"):
            field_value["Тема"] = body["Тема"]
        if body.get("DeletionMark"):
            deleted.append(str(args.get("ref_key") or ""))
        return {"updated": True, "ref_key": args.get("ref_key")}

    monkeypatch.setattr("app.services.onec_write_probe._odata_get", fake_get)
    monkeypatch.setattr("app.services.onec_write_probe._odata_post", fake_post)
    monkeypatch.setattr("app.services.onec_write_probe._odata_patch", fake_patch)
    monkeypatch.setattr(
        "app.services.onec_write_probe.resolve_odata_entity",
        lambda intent: entity,
    )

    result = probe_odata_entity_write(
        {"workflow_id": "wf-1"},
        intent={"family": "odata", "change": "update", "odata_entity": entity},
    )
    assert result["ok"] is True
    assert result["cleaned"] is True
    assert result["recipe"]["entity"] == entity
    assert created["Ref_Key"] in deleted
    assert "OK" in field_value["Тема"]


def test_dispatcher_runs_assignment_and_generic(monkeypatch) -> None:
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: True)
    monkeypatch.setattr(
        "app.services.onec_write_probe.probe_assignment_write",
        lambda args, **kwargs: {
            "ok": True,
            "cleaned": True,
            "recipe": {"entity": "Document_ТД_Поручения", "tool": "onec.erp_assignments_write"},
            "summary": "assignment ok",
            "test_left": False,
        },
    )
    monkeypatch.setattr(
        "app.services.onec_write_probe.probe_odata_entity_write",
        lambda args, intent: {
            "ok": True,
            "cleaned": True,
            "recipe": {"entity": intent.get("odata_entity"), "tool": "onec.odata_patch"},
            "summary": "odata ok",
            "test_left": False,
        },
    )
    result = probe_onec_writes(
        {
            "intents": [
                {
                    "family": "assignment",
                    "operation": "update",
                    "change": "status",
                    "odata_entity": "Document_ТД_Поручения",
                    "key": "assignment:update:status:Document_ТД_Поручения",
                },
                {
                    "family": "odata",
                    "operation": "update",
                    "change": "status",
                    "odata_entity": "Document_ТД_Протокол",
                    "key": "odata:update:status:Document_ТД_Протокол",
                },
            ]
        }
    )
    assert result["ok"] is True
    assert len(result["recipes"]) == 2
    assert result["intent_keys"][1].endswith("Протокол")

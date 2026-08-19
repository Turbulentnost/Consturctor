from __future__ import annotations

from app.services.workflows.service import _effort_params, _resolve_model_variant

_GROK = {
    "id": "grok-4.6",
    "displayName": "Cursor Grok 4.6",
    "parameters": [
        {
            "id": "effort",
            "values": [{"value": "low"}, {"value": "medium"}, {"value": "high"}, {"value": "xhigh"}],
        },
        {"id": "fast", "values": [{"value": "false"}, {"value": "true"}]},
    ],
}
_COMPOSER = {
    "id": "composer-2.5",
    "aliases": ["composer-latest", "composer"],
    "parameters": [{"id": "fast", "values": [{"value": "false"}, {"value": "true"}]}],
}


def test_effort_goes_to_model_that_declares_it() -> None:
    assert _effort_params(_GROK, "high") == [{"id": "effort", "value": "high"}]


def test_effort_skipped_for_model_without_the_parameter() -> None:
    assert _effort_params(_COMPOSER, "high") is None


def test_unsupported_effort_value_is_dropped() -> None:
    assert _effort_params(_GROK, "ultra") is None


def test_no_effort_configured_means_no_params() -> None:
    assert _effort_params(_GROK, "") is None


def test_resolves_grok_high_variant(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.workflows.service.cursor_client.list_models",
        lambda: [_COMPOSER, _GROK],
    )
    monkeypatch.setattr(
        "app.services.workflows.service.settings.cursor_workflow_model", "grok-4.6"
    )
    monkeypatch.setattr(
        "app.services.workflows.service.settings.cursor_workflow_model_effort", "high"
    )

    assert _resolve_model_variant() == ("grok-4.6", [{"id": "effort", "value": "high"}])


def test_alias_still_resolves_and_keeps_params_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.workflows.service.cursor_client.list_models",
        lambda: [_COMPOSER, _GROK],
    )
    monkeypatch.setattr(
        "app.services.workflows.service.settings.cursor_workflow_model", "composer"
    )
    monkeypatch.setattr(
        "app.services.workflows.service.settings.cursor_workflow_model_effort", "high"
    )

    assert _resolve_model_variant() == ("composer-2.5", None)

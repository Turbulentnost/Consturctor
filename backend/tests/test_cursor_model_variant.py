from __future__ import annotations

from app.services.workflows.service import _effort_params, _resolve_model_variant

_GROK_HIGH = [{"id": "effort", "value": "high"}, {"id": "fast", "value": "true"}]
_COMPOSER_FAST = [{"id": "fast", "value": "true"}]

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
    "variants": [
        {"params": [{"id": "effort", "value": "low"}, {"id": "fast", "value": "true"}]},
        {"params": _GROK_HIGH, "isDefault": True},
        {"params": [{"id": "effort", "value": "xhigh"}, {"id": "fast", "value": "true"}]},
    ],
}
_COMPOSER = {
    "id": "composer-2.5",
    "aliases": ["composer-latest", "composer"],
    "parameters": [{"id": "fast", "values": [{"value": "false"}, {"value": "true"}]}],
    "variants": [
        {"params": _COMPOSER_FAST, "isDefault": True},
        {"params": [{"id": "fast", "value": "false"}]},
    ],
}


_GROK_XHIGH = [{"id": "effort", "value": "xhigh"}, {"id": "fast", "value": "true"}]


def test_effort_picks_complete_high_variant() -> None:
    assert _effort_params(_GROK, "high") == _GROK_HIGH


def test_effort_picks_xhigh_variant() -> None:
    assert _effort_params(_GROK, "xhigh") == _GROK_XHIGH


def test_regulation_creation_defaults_to_grok_xhigh_fast() -> None:
    from app.config import Settings
    from app.services.regulation_creation import cursor_agent

    settings = Settings()
    assert settings.cursor_regulation_creation_model == "grok-4.6"
    assert settings.cursor_regulation_creation_effort == "xhigh"
    assert cursor_agent.settings.cursor_regulation_creation_model == "grok-4.6"
    assert cursor_agent.settings.cursor_regulation_creation_effort == "xhigh"


def test_model_without_effort_uses_its_default_variant() -> None:
    assert _effort_params(_COMPOSER, "high") == _COMPOSER_FAST


def test_unknown_effort_falls_back_to_default_variant() -> None:
    assert _effort_params(_GROK, "ultra") == _GROK_HIGH


def test_empty_effort_uses_default_variant() -> None:
    assert _effort_params(_GROK, "") == _GROK_HIGH


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

    assert _resolve_model_variant() == ("grok-4.6", _GROK_HIGH)


def test_composer_alias_uses_complete_default_variant(monkeypatch) -> None:
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

    assert _resolve_model_variant() == ("composer-2.5", _COMPOSER_FAST)

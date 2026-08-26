from app.ui.widgets.dock_layout import (
    DEFAULT_KEYS,
    detach_key,
    first_docked_key,
    move_key,
    _normalize,
)


def test_normalize_keeps_floated_keys_off_rails() -> None:
    layout = _normalize(
        {
            "left": ["create", "agents"],
            "float": ["chat", "kpi"],
        }
    )
    assert layout["float"] == ["chat", "kpi"]
    assert "chat" not in layout["left"]
    assert "kpi" not in layout["left"]
    assert "orchestrator" in layout["left"]
    assert "dashboard" in layout["left"]


def test_detach_and_redock() -> None:
    layout = _normalize({"left": list(DEFAULT_KEYS)})
    floated = detach_key(layout, "agents")
    assert floated["float"] == ["agents"]
    assert "agents" not in floated["left"]
    assert first_docked_key(floated) == "create"
    docked = move_key(floated, "agents", "right")
    assert docked["right"] == ["agents"]
    assert docked["float"] == []


def test_move_unknown_side_keeps_layout() -> None:
    layout = _normalize({})
    before = list(layout["left"])
    same = move_key(layout, "create", "float")
    assert same["left"] == before

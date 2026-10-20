from app.services.user_ui_prefs import UserUiPrefsError, merge_sections, _section_patch


def test_merge_keeps_the_other_section_and_sibling_keys() -> None:
    current = {
        "sidebar": {"layouts": {"user": {"root": ["tab:today"]}}, "collapsed": True},
        "today": {"tileOrder": ["ev", "day"]},
    }
    merged = merge_sections(current, {"today": {"widgets": {"layout": []}}})
    assert merged["sidebar"]["collapsed"] is True
    assert merged["today"]["tileOrder"] == ["ev", "day"]
    assert merged["today"]["widgets"] == {"layout": []}


def test_section_patch_rejects_a_list() -> None:
    try:
        _section_patch({"sidebar": ["today"]})
    except UserUiPrefsError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected UserUiPrefsError")


def test_section_patch_ignores_unknown_keys() -> None:
    assert _section_patch({"theme": {"dark": True}, "sidebar": {"quick": ["today"]}}) == {
        "sidebar": {"quick": ["today"]}
    }

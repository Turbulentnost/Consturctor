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


def test_tishchenko_reads_ilchenko_layout_once() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.models.user import AppUser
    from app.models.user_ui_prefs import UserUiPrefs
    from app.services.orchestrator.ilchenko import ILCHENKO_LOGIN_ID, TISHCHENKO_USER_ID
    from app.services.user_ui_prefs import read_prefs, save_prefs

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    now = datetime.now(timezone.utc)
    db.add(AppUser(id=ILCHENKO_LOGIN_ID, fio="Ильченко", position="", created_at=now, updated_at=now))
    db.add(AppUser(id=TISHCHENKO_USER_ID, fio="Тищенко Марина Николаевна", position="", created_at=now, updated_at=now))
    db.add(
        UserUiPrefs(
            user_id=ILCHENKO_LOGIN_ID,
            body={
                "sidebar": {"quick": ["today", "meetings"]},
                "today": {"tileOrder": ["assignments", "events"]},
            },
        )
    )
    db.commit()

    first = read_prefs(db, user_id=TISHCHENKO_USER_ID)
    assert first["today"]["tileOrder"] == ["assignments", "events"]
    assert first["sidebar"]["quick"] == ["today", "meetings"]

    save_prefs(db, user_id=TISHCHENKO_USER_ID, raw={"today": {"tileOrder": ["events"]}})
    second = read_prefs(db, user_id=TISHCHENKO_USER_ID)
    assert second["today"]["tileOrder"] == ["events"]
    assert second["sidebar"]["quick"] == ["today", "meetings"]
    db.close()

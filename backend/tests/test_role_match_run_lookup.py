from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.role_matching.service import RoleMatchError, get_run_row


def test_get_run_row_accepts_stale_regulation_id() -> None:
    run = SimpleNamespace(id="role-run-1", regulation_id="reg-actual", user_id="u1")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = run

    found = get_run_row(db, user_id="u1", regulation_id="reg-stale", run_id="role-run-1")

    assert found is run


def test_get_run_row_falls_back_to_latest_for_regulation() -> None:
    run = SimpleNamespace(id="role-run-2", regulation_id="reg-1", user_id="u1")
    missing = MagicMock()
    missing.first.return_value = None
    found = MagicMock()
    found.order_by.return_value.first.return_value = run
    db = MagicMock()
    db.query.return_value.filter.side_effect = [missing, found]

    result = get_run_row(db, user_id="u1", regulation_id="reg-1", run_id="role-run-missing")

    assert result is run


def test_get_run_row_missing() -> None:
    missing = MagicMock()
    missing.first.return_value = None
    missing.order_by.return_value.first.return_value = None
    db = MagicMock()
    db.query.return_value.filter.return_value = missing

    with pytest.raises(RoleMatchError, match="Запуск поиска не найден"):
        get_run_row(db, user_id="u1", regulation_id="reg-1", run_id="missing")

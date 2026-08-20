from types import SimpleNamespace

import pytest

from app.services import auth_service


def test_bypass_login_skips_erp_sql(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "auth_skip_erp_sql", True)
    monkeypatch.setattr(auth_service.settings, "erp_login", "Ильченко Екатерина Александровна")
    monkeypatch.setattr(auth_service.settings, "erp_password", "temp-pass")
    monkeypatch.setattr(auth_service.settings, "auth_bypass_user_id", "USER-1")

    def boom(*_args, **_kwargs):
        raise AssertionError("erp_pm SQL must not be queried while bypass is on")

    monkeypatch.setattr(auth_service, "find_user_by_fio", boom)
    monkeypatch.setattr(
        auth_service.app_users,
        "find_app_user_by_fio",
        lambda _fio: SimpleNamespace(
            id="USER-1",
            fio="Ильченко Екатерина Александровна",
            department="Отдел",
            position="Должность",
        ),
    )
    monkeypatch.setattr(
        auth_service.app_users,
        "upsert_app_user",
        lambda **kwargs: SimpleNamespace(
            id=kwargs["user_id"],
            fio=kwargs["fio"],
            department=kwargs["department"],
            position=kwargs["position"],
            avatar_path=None,
            updated_at=None,
            department_changed_at=None,
        ),
    )
    monkeypatch.setattr(
        auth_service.app_users,
        "to_user_out",
        lambda user: auth_service.UserOut(
            id=user.id,
            fio=user.fio,
            department=user.department,
            position=user.position,
        ),
    )

    result = auth_service._login_via_bypass(
        "Ильченко Екатерина Александровна",
        "temp-pass",
    )
    assert result.user.id == "USER-1"
    assert result.user.fio == "Ильченко Екатерина Александровна"
    assert result.access_token


def test_bypass_login_rejects_other_user(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "auth_skip_erp_sql", True)
    monkeypatch.setattr(auth_service.settings, "erp_login", "Ильченко Екатерина Александровна")
    monkeypatch.setattr(auth_service.settings, "erp_password", "temp-pass")

    with pytest.raises(auth_service.AuthError) as exc:
        auth_service._login_via_bypass("Другой Пользователь", "temp-pass")
    assert exc.value.status_code == 401

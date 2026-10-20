from app.services import assignment_docflow_tasks as mod


def _patch(monkeypatch, *, fail_users=()):
    tried: list[str] = []

    def fake_load_config(*, username, password, **_):
        tried.append(username)
        if username in fail_users:
            raise RuntimeError("HTTP 401: Документооборот отклонил Basic-учётку")
        return username

    monkeypatch.setattr("app.tools.onec.dok_soap.load_config", fake_load_config)
    monkeypatch.setattr(mod, "_rows_for", lambda config, refs: {ref: [{"by": config}] for ref in refs})
    return tried


def test_without_session_password_reads_as_service_account(monkeypatch):
    tried = _patch(monkeypatch)
    monkeypatch.setattr(mod, "_service_login", lambda: ("Робот", "secret"))
    rows, error = mod._session_rows({"fio": "", "password": ""}, ["ref-1"])
    assert error == ""
    assert rows["ref-1"][0]["by"] == "Робот"
    assert tried == ["Робот"]


def test_rejected_session_falls_back_to_service_account(monkeypatch):
    tried = _patch(monkeypatch, fail_users={"Ильченко"})
    monkeypatch.setattr(mod, "_service_login", lambda: ("Робот", "secret"))
    monkeypatch.setattr(
        "app.tools.onec.docflow_inbox_fetch._soap_login_attempts",
        lambda args: [("Ильченко", "pwd")],
    )
    rows, error = mod._session_rows({"fio": "Ильченко", "password": "pwd"}, ["ref-1"])
    assert error == "" and rows["ref-1"][0]["by"] == "Робот"
    assert tried == ["Ильченко", "Робот"]


def test_no_password_and_no_service_account_keeps_old_error(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(mod, "_service_login", lambda: ("", ""))
    rows, error = mod._session_rows({"fio": "", "password": ""}, ["ref-1"])
    assert rows == {} and error == "нет пароля 1С сеанса"

from __future__ import annotations

from types import SimpleNamespace

from app.tools.ac.workers import com_availability


def test_onec_com_availability_fails_when_connector_registration_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(com_availability, "is_windows", lambda: True)
    monkeypatch.setattr(
        com_availability,
        "_check_pywin32_availability",
        lambda: (True, None),
    )
    monkeypatch.setenv("ONEC_COM_CONNECTION_STRING", "Srvr=test;Ref=test;")
    monkeypatch.setenv("ONEC_COM_PROGID", "V83.COMConnector")

    def fake_import_module(name: str):
        if name == "win32com.client":
            return SimpleNamespace(
                Dispatch=lambda progid: (_ for _ in ()).throw(
                    RuntimeError(f"Class not registered: {progid}")
                )
            )
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(com_availability.importlib, "import_module", fake_import_module)

    assert com_availability.is_onec_com_available() is False
    assert "Не удалось создать COMConnector" in com_availability.get_onec_com_unavailable_reason()


def test_onec_com_availability_passes_when_connector_is_creatable(monkeypatch) -> None:
    monkeypatch.setattr(com_availability, "is_windows", lambda: True)
    monkeypatch.setattr(
        com_availability,
        "_check_pywin32_availability",
        lambda: (True, None),
    )
    monkeypatch.setenv("ONEC_COM_CONNECTION_STRING", "Srvr=test;Ref=test;")
    monkeypatch.setenv("ONEC_COM_PROGID", "V83.COMConnector")

    def fake_import_module(name: str):
        if name == "win32com.client":
            return SimpleNamespace(Dispatch=lambda progid: SimpleNamespace(progid=progid))
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(com_availability.importlib, "import_module", fake_import_module)

    assert com_availability.is_onec_com_available() is True
    assert com_availability.get_onec_com_unavailable_reason() == "1C COMConnector доступен"

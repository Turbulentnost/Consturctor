from __future__ import annotations

import importlib
from types import SimpleNamespace

from app.tools.ac.workers import com_availability
from app.tools.ac.workers import onec_com32_helper


def _reset() -> None:
    com_availability.reset_onec_com_availability_cache()


def test_onec_com_availability_fails_when_connector_registration_is_missing(monkeypatch) -> None:
    _reset()
    monkeypatch.setattr(com_availability, "is_windows", lambda: True)
    monkeypatch.setattr(
        com_availability,
        "_check_pywin32_availability",
        lambda: (True, None),
    )
    monkeypatch.setenv("ONEC_COM_CONNECTION_STRING", "Srvr=test;Ref=test;")
    monkeypatch.setenv("ONEC_COM_PROGID", "V83.COMConnector")
    monkeypatch.delenv("ONEC_COM_PYTHON", raising=False)

    real_import = importlib.import_module

    def fake_import_module(name: str, package=None):
        if name == "win32com.client":
            return SimpleNamespace(
                Dispatch=lambda progid: (_ for _ in ()).throw(
                    RuntimeError(f"Class not registered: {progid}")
                )
            )
        return real_import(name, package)

    monkeypatch.setattr(com_availability.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        onec_com32_helper,
        "is_com32_available",
        lambda: (False, "32-bit helper off"),
    )

    assert com_availability.is_onec_com_available() is False
    assert "Не удалось создать COMConnector" in com_availability.get_onec_com_unavailable_reason()
    _reset()


def test_onec_com_available_via_32bit_helper_when_64bit_dispatch_fails(monkeypatch) -> None:
    _reset()
    monkeypatch.setattr(com_availability, "is_windows", lambda: True)
    monkeypatch.setenv("ONEC_COM_SERVER", "srv1")
    monkeypatch.setenv("ONEC_COM_REF", "erp_pm")
    monkeypatch.setenv("ONEC_COM_PROGID", "V83.COMConnector")
    monkeypatch.delenv("ONEC_COM_PYTHON", raising=False)
    monkeypatch.setattr(
        onec_com32_helper,
        "is_com32_available",
        lambda: (True, "32-bit COMConnector доступен"),
    )

    assert com_availability.is_onec_com_available() is True
    assert com_availability.onec_com_runtime() == com_availability.ONEC_COM_RUNTIME_CSCRIPT32
    assert com_availability.prefers_com32() is True
    capability = com_availability.describe_com_capability()
    assert capability["onec_com_available"] is True
    assert capability["onec_com_runtime"] == "cscript32"
    _reset()


def test_onec_com_availability_passes_when_connector_is_creatable(monkeypatch) -> None:
    _reset()
    monkeypatch.setattr(com_availability, "is_windows", lambda: True)
    monkeypatch.setattr(
        com_availability,
        "_check_pywin32_availability",
        lambda: (True, None),
    )
    monkeypatch.setenv("ONEC_COM_CONNECTION_STRING", "Srvr=test;Ref=test;")
    monkeypatch.setenv("ONEC_COM_PROGID", "V83.COMConnector")
    monkeypatch.delenv("ONEC_COM_PYTHON", raising=False)
    monkeypatch.setattr(
        onec_com32_helper,
        "is_com32_available",
        lambda: (False, "32-bit helper off"),
    )

    def fake_import_module(name: str, package=None):
        if name == "win32com.client":
            return SimpleNamespace(Dispatch=lambda progid: SimpleNamespace(progid=progid))
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(com_availability.importlib, "import_module", fake_import_module)

    assert com_availability.is_onec_com_available() is True
    assert com_availability.get_onec_com_unavailable_reason() == "1C COMConnector доступен"
    assert com_availability.onec_com_runtime() == com_availability.ONEC_COM_RUNTIME_INPROC
    assert com_availability.prefers_com32() is False
    _reset()


def test_availability_does_not_probe_py32_launcher(monkeypatch) -> None:
    _reset()
    monkeypatch.setattr(com_availability, "is_windows", lambda: True)
    monkeypatch.setenv("ONEC_COM_SERVER", "srv1")
    monkeypatch.setenv("ONEC_COM_REF", "erp_pm")
    monkeypatch.delenv("ONEC_COM_PYTHON", raising=False)
    monkeypatch.setattr(
        onec_com32_helper,
        "is_com32_available",
        lambda: (False, "off"),
    )
    monkeypatch.setattr(
        com_availability,
        "_check_pywin32_availability",
        lambda: (False, "no pywin32"),
    )
    called = []

    def fake_run(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("py -3.12-32 must not be probed")

    monkeypatch.setattr(com_availability.subprocess, "run", fake_run)
    assert com_availability.is_onec_com_available() is False
    assert called == []
    _reset()


def test_pywin32_dll_dirs_returns_list() -> None:
    dirs = com_availability.pywin32_dll_dirs()
    assert isinstance(dirs, list)
    com_availability.ensure_pywin32_dll_path()

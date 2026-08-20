from __future__ import annotations

from pathlib import Path

from installer.build_installer import find_iscc
from installer.server_env import backend_base_url, set_backend_url


def _iss_text() -> str:
    return (Path(__file__).resolve().parents[1] / "installer" / "ConstructorDesktop.iss").read_text(
        encoding="utf-8"
    )


def test_iss_is_per_user_and_keeps_env() -> None:
    text = _iss_text()
    assert "PrivilegesRequired=lowest" in text
    assert "onlyifdoesntexist" in text
    assert "uninsneveruninstall" in text
    assert "Excludes: \".env\"" in text
    assert "OutputBaseFilename=ConstructorDesktop-Setup" in text
    assert "WorkingDir: \"{app}\"" in text
    assert "ERP_PASSWORD" not in text
    assert r"{localappdata}\ConstructorDesktop" in text
    assert "UpdateBackendUrl" in text
    assert "BACKEND_URL={#BackendUrl}" in text
    assert "SaveStringsToUTF8File" in text
    assert "SaveStringsToFile(" not in text


def test_find_iscc_on_this_machine() -> None:
    iscc = find_iscc()
    assert iscc is not None
    assert iscc.name.casefold() in {"iscc.exe", "iscc"}


def test_set_backend_url_replaces_localhost_and_keeps_other_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BACKEND_URL=http://127.0.0.1:7812\nERP_LOGIN=demo\n# BACKEND_URL=keep-comment\n",
        encoding="utf-8",
    )
    set_backend_url(env_path, "http://192.168.2.135:7812/")
    text = env_path.read_text(encoding="utf-8")
    assert "BACKEND_URL=http://192.168.2.135:7812\n" in text
    assert "127.0.0.1" not in text
    assert "ERP_LOGIN=demo" in text
    assert "# BACKEND_URL=keep-comment" in text


def test_backend_url_override() -> None:
    assert backend_base_url(override="http://10.0.0.5:7812/") == "http://10.0.0.5:7812"

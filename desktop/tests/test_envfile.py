from __future__ import annotations

import os

from app.envfile import decode_env_bytes, load_env_file
from installer.server_env import set_backend_url


def test_decode_cp1251_cyrillic_login() -> None:
    payload = "BACKEND_URL=http://192.168.2.135:7812\nERP_LOGIN=Ильченко\n".encode("cp1251")
    assert b"\xc8" in payload
    text = decode_env_bytes(payload)
    assert "Ильченко" in text
    assert "192.168.2.135" in text


def test_load_env_file_from_cp1251(tmp_path, monkeypatch) -> None:
    path = tmp_path / ".env"
    path.write_bytes("ERP_LOGIN=Ильченко\n".encode("cp1251"))
    monkeypatch.delenv("ERP_LOGIN", raising=False)
    assert load_env_file(path, override=True) is True
    assert os.getenv("ERP_LOGIN") == "Ильченко"
    monkeypatch.delenv("ERP_LOGIN", raising=False)


def test_set_backend_url_rewrites_cp1251_as_utf8(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(
        "BACKEND_URL=http://127.0.0.1:7812\nERP_LOGIN=Ильченко\n".encode("cp1251")
    )
    set_backend_url(path, "http://192.168.2.135:7812")
    data = path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "BACKEND_URL=http://192.168.2.135:7812" in text
    assert "Ильченко" in text
    assert "127.0.0.1" not in text

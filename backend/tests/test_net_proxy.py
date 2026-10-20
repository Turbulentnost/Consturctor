from __future__ import annotations

import os

import httpx

from app.net_proxy import drop_unsupported_proxy_env, filter_proxy_map, install


def test_socks4_env_is_removed(monkeypatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks4://127.0.0.1:10808")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:8080")
    drop_unsupported_proxy_env()
    assert "ALL_PROXY" not in os.environ
    assert os.environ["https_proxy"] == "http://127.0.0.1:8080"


def test_registry_socks4_is_not_passed_to_httpx(monkeypatch) -> None:
    import urllib.request

    import httpx._utils as httpx_utils

    import app.net_proxy as net_proxy

    previous_urllib = urllib.request.getproxies
    previous_httpx = httpx_utils.getproxies
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"https": "socks4://127.0.0.1:10808", "http": "http://127.0.0.1:8080", "no": "localhost"},
    )
    net_proxy._INSTALLED = False
    try:
        install()
        resolved = httpx_utils.get_environment_proxies()
        assert resolved["http://"] == "http://127.0.0.1:8080"
        assert all("socks4" not in str(value) for value in resolved.values() if value)
        httpx.Client(timeout=1.0).close()
    finally:
        urllib.request.getproxies = previous_urllib
        httpx_utils.getproxies = previous_httpx
        net_proxy._INSTALLED = False
    assert filter_proxy_map({"https": "socks4://127.0.0.1:10808", "no": "localhost"}) == {"no": "localhost"}

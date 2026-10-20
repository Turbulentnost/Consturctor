import httpx

from app.net_env import install_direct_http


def test_system_socks_proxy_does_not_break_httpx(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks4://127.0.0.1:10808")
    install_direct_http()
    httpx.Client(timeout=1.0).close()

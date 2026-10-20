"""Drop Happ's socks4 proxy before any httpx client is built.

Happ publishes ALL_PROXY=socks4://127.0.0.1:10808 and the same value in the
Windows Internet Settings registry. httpx rejects that scheme while constructing
a client, so login dies before the request. urllib.request.getproxies() reads
the registry even after the environment variables are removed.
"""

from __future__ import annotations

import os
from collections.abc import Callable

_PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)
_INSTALLED = False


def _allowed_prefixes() -> tuple[str, ...]:
    allowed = ("http://", "https://")
    try:
        import socksio  # noqa: F401
    except ImportError:
        return allowed
    return allowed + ("socks5://", "socks5h://")


def proxy_url_supported(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    url = raw if "://" in raw else f"http://{raw}"
    return url.lower().startswith(_allowed_prefixes())


def drop_unsupported_proxy_env() -> None:
    for key in _PROXY_ENV_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value and not proxy_url_supported(value):
            os.environ.pop(key, None)


def filter_proxy_map(info: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in info.items():
        if key == "no":
            if (value or "").strip():
                cleaned[key] = value
            continue
        if proxy_url_supported(value):
            cleaned[key] = value
    return cleaned


def install() -> None:
    """Remove socks4 from the process environment and from urllib/httpx lookups."""
    global _INSTALLED
    drop_unsupported_proxy_env()
    if _INSTALLED:
        return

    import urllib.request

    original: Callable[[], dict[str, str]] = urllib.request.getproxies

    def filtered() -> dict[str, str]:
        return filter_proxy_map(original())

    urllib.request.getproxies = filtered
    try:
        import httpx._utils as httpx_utils
    except ImportError:
        httpx_utils = None
    if httpx_utils is not None:
        httpx_utils.getproxies = filtered
    _INSTALLED = True

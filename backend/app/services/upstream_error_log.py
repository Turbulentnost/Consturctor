"""Временный журнал отказов публикации 1С и TurboProject.

Тело HTTP 503 в обычный лог не попадает, поэтому причина кластера теряется.
Файл обрезается по размеру. Выключить: UPSTREAM_ERROR_LOG=0.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import BACKEND_ROOT, settings

_LOCK = threading.Lock()
_MAX_BYTES = 1_500_000
_BODY_CHARS = 1500
_PATH = BACKEND_ROOT / "logs" / "upstream-http.log"
_INSTALLED = False


def _watched_hosts() -> set[str]:
    hosts = {(settings.dok_http_server or "").strip().lower()}
    for raw in (
        settings.odata_base_url,
        settings.docflow_odata_base_url,
        settings.turboproject_api_base,
    ):
        host = (urlsplit(str(raw or "")).hostname or "").strip().lower()
        if host:
            hosts.add(host)
    hosts.discard("")
    return hosts


def _public_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _interesting(url: str) -> bool:
    host = (urlsplit(url).hostname or "").strip().lower()
    return bool(host) and host in _watched_hosts()


def _clip(text: str) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= _BODY_CHARS:
        return flat
    return flat[:_BODY_CHARS] + "…"


def record(message: str) -> None:
    if not settings.upstream_error_log:
        return
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            if _PATH.is_file() and _PATH.stat().st_size > _MAX_BYTES:
                backup = _PATH.with_suffix(".log.1")
                if backup.is_file():
                    backup.unlink()
                _PATH.replace(backup)
            with _PATH.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        return


def record_response(method: str, url: str, status: int, body: str, *, elapsed_sec: float) -> None:
    if status < 500 or not _interesting(url):
        return
    record(
        f"{method} {_public_url(url)} -> {status} in {elapsed_sec:.1f}s body={_clip(body) or '<empty>'}"
    )


def record_failure(method: str, url: str, error: BaseException, *, elapsed_sec: float) -> None:
    if not _interesting(url):
        return
    record(
        f"{method} {_public_url(url)} -> FAIL in {elapsed_sec:.1f}s {type(error).__name__}: {_clip(str(error))}"
    )


def install_httpx_capture() -> None:
    """Все sync-клиенты httpx: 5xx и обрыв соединения пишем в файл."""
    global _INSTALLED
    if _INSTALLED:
        return
    original = httpx.Client.send

    def send(self, request, *args, **kwargs):  # noqa: ANN001
        started = time.perf_counter()
        url = str(request.url)
        method = str(request.method)
        try:
            response = original(self, request, *args, **kwargs)
        except Exception as exc:
            record_failure(method, url, exc, elapsed_sec=time.perf_counter() - started)
            raise
        if response.status_code >= 500 and not kwargs.get("stream"):
            try:
                body = response.text
            except Exception:
                body = ""
            record_response(
                method,
                url,
                response.status_code,
                body,
                elapsed_sec=time.perf_counter() - started,
            )
        return response

    httpx.Client.send = send  # type: ignore[method-assign]
    _INSTALLED = True

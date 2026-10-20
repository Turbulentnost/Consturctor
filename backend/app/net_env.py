"""Запросы бэкенда в 1С не должны идти через системный прокси.

На Windows urllib подставляет прокси из настроек системы. httpx по умолчанию
ему доверяет и падает на socks4://127.0.0.1:10808 ещё до OData.
Клиенты 1С, Документооборота и TurboProject остаются в локальной сети.
Явный trust_env=True у вызова по-прежнему включает прокси.
"""

from __future__ import annotations

import httpx

_INSTALLED = False


def install_direct_http() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    original = httpx.Client.__init__

    def init(self, *args, **kwargs):  # noqa: ANN001
        kwargs.setdefault("trust_env", False)
        original(self, *args, **kwargs)

    httpx.Client.__init__ = init  # type: ignore[method-assign]
    _INSTALLED = True

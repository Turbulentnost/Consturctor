"""Снимок опубликованных агентов Constructor.

Запросы к API читают готовый снимок и не ждут базу: соединение с 192.168.1.157
может висеть секундами. Снимок обновляется фоновым потоком.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.constructor.owners import AgentOwner

logger = logging.getLogger(__name__)

Loader = Callable[[], list[AgentOwner]]


class CatalogSnapshot(BaseModel):
    state: Literal["idle", "ready", "error"]
    refreshing: bool
    error: str = ""
    source: str = ""
    loaded_at: str | None = None
    items: list[AgentOwner] = Field(default_factory=list)


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else type(exc).__name__


class ConstructorCatalog:
    def __init__(self, loader: Loader, source: str = "") -> None:
        self.loader = loader
        self.source = source
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._owners: list[AgentOwner] = []
        self._loaded = False
        self._error = ""
        self._loaded_at: datetime | None = None
        self._refreshing = False

    def snapshot(self) -> CatalogSnapshot:
        with self._lock:
            state = "ready" if self._loaded else "error" if self._error else "idle"
            return CatalogSnapshot(
                state=state,
                refreshing=self._refreshing,
                error=self._error,
                source=self.source,
                loaded_at=self._loaded_at.isoformat() if self._loaded_at else None,
                items=list(self._owners),
            )

    def owners(self) -> list[AgentOwner]:
        with self._lock:
            return list(self._owners)

    def refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        try:
            owners = self.loader()
        except Exception as exc:
            message = f"База Constructor {self.source} недоступна: {_first_line(exc)}"
            logger.warning("%s", message)
            with self._lock:
                self._error = message
                self._refreshing = False
            return
        with self._lock:
            self._owners = owners
            self._loaded = True
            self._error = ""
            self._loaded_at = datetime.now(timezone.utc)
            self._refreshing = False
        logger.info(
            "Constructor: %s сотрудников, %s агентов",
            len(owners),
            sum(len(owner.agents) for owner in owners),
        )

    def request_refresh(self) -> None:
        self._wake.set()

    def start(self, interval_seconds: int) -> None:
        if self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.is_set():
                self.refresh()
                self._wake.wait(interval_seconds)
                self._wake.clear()

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="constructor-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread = None


def _load_from_database() -> list[AgentOwner]:
    from app.constructor.db import fetch_published_candidates
    from app.constructor.owners import build_owners

    return build_owners(fetch_published_candidates())


def _make_catalog() -> ConstructorCatalog:
    from app.constructor.db import database_label

    return ConstructorCatalog(_load_from_database, source=database_label())


constructor_catalog = _make_catalog()

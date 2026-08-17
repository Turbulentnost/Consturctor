"""Run all COM calls on a dedicated STA thread (Outlook requires apartment threading)."""

from __future__ import annotations

import queue
import sys
import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_call_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any], queue.Queue[Any]] | None] = (
    queue.Queue()
)
_ready = threading.Event()
_thread: threading.Thread | None = None


def _com_worker() -> None:
    import pythoncom

    try:
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    except TypeError:
        pythoncom.CoInitialize()
    _ready.set()
    while True:
        item = _call_queue.get()
        if item is None:
            break
        fn, args, kwargs, result_queue = item
        try:
            result_queue.put((True, fn(*args, **kwargs)))
        except Exception as exc:  # noqa: BLE001
            result_queue.put((False, exc))


def _ensure_thread() -> None:
    global _thread
    if sys.platform != "win32":
        return
    if _thread is not None and _thread.is_alive():
        return
    _ready.clear()
    _thread = threading.Thread(target=_com_worker, name="platform-com-sta", daemon=True)
    _thread.start()
    if not _ready.wait(timeout=10.0):
        raise RuntimeError("COM worker thread failed to initialize")


def com_call(fn: Callable[..., T], /, *args: Any, timeout: float = 120.0, **kwargs: Any) -> T:
    """Execute *fn* on the COM STA worker thread and return its result."""
    if sys.platform != "win32":
        return fn(*args, **kwargs)
    _ensure_thread()
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    _call_queue.put((fn, args, kwargs, result_queue))
    try:
        ok, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"COM call timed out after {timeout}s") from exc
    if ok:
        return payload
    raise payload

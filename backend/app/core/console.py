"""Консольный вывод и журнал без блокировки обработчиков запросов.

Если читатель stdout/stderr (окно терминала, конвейер) перестал читать, запись
в заполненный канал останавливает пишущий поток навсегда. На event loop uvicorn
это останавливает весь backend: не отвечает даже /health/live. Поэтому строки
идут в ограниченную очередь, пишет их отдельный поток, переполнение отбрасывается.
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import queue
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

_STREAM_QUEUE_ITEMS = 20_000
_LOG_QUEUE_ITEMS = 50_000
_EXIT_DRAIN_SEC = 2.0
_LOG_FILE_BYTES = 10_000_000
_LOG_FILE_BACKUPS = 5
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

_install_guard = threading.Lock()
_log_listener: logging.handlers.QueueListener | None = None
_log_file: Path | None = None


class NonBlockingStream:
    """Обёртка над stdout/stderr: write() кладёт текст в очередь и сразу возвращается."""

    def __init__(self, target: TextIO, name: str) -> None:
        self._target = target
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=_STREAM_QUEUE_ITEMS)
        self._dropped = 0
        self._dropped_guard = threading.Lock()
        self._thread = threading.Thread(target=self._drain, name=f"console-{name}", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    @property
    def target(self) -> TextIO:
        return self._target

    def write(self, text: str) -> int:
        if not text:
            return 0
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            with self._dropped_guard:
                self._dropped += 1
        return len(text)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        try:
            self._queue.put(None, timeout=_EXIT_DRAIN_SEC)
        except queue.Full:
            return
        self._thread.join(timeout=_EXIT_DRAIN_SEC)

    def _take_dropped(self) -> int:
        with self._dropped_guard:
            dropped, self._dropped = self._dropped, 0
        return dropped

    def _drain(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                return
            try:
                dropped = self._take_dropped()
                if dropped:
                    self._target.write(f"[console] пропущено записей: {dropped}\n")
                self._target.write(text)
                if self._queue.empty():
                    self._target.flush()
            except Exception:
                continue

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


class _DroppingQueueHandler(logging.handlers.QueueHandler):
    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            pass


def install_nonblocking_console() -> None:
    with _install_guard:
        for name in ("stdout", "stderr"):
            stream = getattr(sys, name, None)
            if stream is None or isinstance(stream, NonBlockingStream):
                continue
            setattr(sys, name, NonBlockingStream(stream, name))


def _wrapped_for(stream: Any) -> Any:
    for name in ("stdout", "stderr"):
        wrapped = getattr(sys, name, None)
        if isinstance(wrapped, NonBlockingStream) and stream is wrapped.target:
            return wrapped
    return stream


def _detach_console_handlers(logger: logging.Logger) -> None:
    """Обработчики, созданные до обёртки (uvicorn), пишут в исходный канал напрямую."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            wrapped = _wrapped_for(handler.stream)
            if wrapped is not handler.stream:
                handler.setStream(wrapped)


def configure_logging(log_file: Path | None = None) -> None:
    """Корневой журнал: очередь → поток-писатель → консоль и, если указан, файл с ротацией."""
    global _log_listener, _log_file
    install_nonblocking_console()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        _detach_console_handlers(logging.getLogger(name))
    formatter = logging.Formatter(_LOG_FORMAT)
    with _install_guard:
        if _log_listener is None:
            console = logging.StreamHandler(sys.stderr)
            console.setFormatter(formatter)
            records: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=_LOG_QUEUE_ITEMS)
            for handler in list(root.handlers):
                root.removeHandler(handler)
            root.addHandler(_DroppingQueueHandler(records))
            _log_listener = logging.handlers.QueueListener(records, console, respect_handler_level=False)
            _log_listener.start()
            atexit.register(_log_listener.stop)
        if log_file is None or _log_file is not None:
            return
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=_LOG_FILE_BYTES,
                backupCount=_LOG_FILE_BACKUPS,
                encoding="utf-8",
                delay=True,
            )
        except OSError:
            return
        file_handler.setFormatter(formatter)
        _log_listener.handlers = (*_log_listener.handlers, file_handler)
        _log_file = log_file

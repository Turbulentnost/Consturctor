"""Консольный вывод backend не должен останавливать обработчик запроса."""

from __future__ import annotations

import io
import threading
import time

from app.core.console import NonBlockingStream


class _StuckPipe(io.StringIO):
    """Канал, который читатель перестал вычитывать: write() висит."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def write(self, text: str) -> int:
        self.release.wait()
        return super().write(text)


def test_write_returns_while_reader_is_stuck() -> None:
    pipe = _StuckPipe()
    stream = NonBlockingStream(pipe, "test")
    started = time.perf_counter()
    for index in range(30_000):
        stream.write(f"API request {index}\n")
    stream.flush()
    assert time.perf_counter() - started < 2.0
    pipe.release.set()
    stream.close()
    assert "API request 0" in pipe.getvalue()


def test_lines_reach_target_in_order() -> None:
    target = io.StringIO()
    stream = NonBlockingStream(target, "order")
    stream.write("первая\n")
    stream.writelines(["вторая\n", "третья\n"])
    stream.close()
    assert target.getvalue() == "первая\nвторая\nтретья\n"

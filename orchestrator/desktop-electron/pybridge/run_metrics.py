"""Фоновый замер хода агента: ЦП, ОЗУ, ГП, SSD и скорость генерации.

Тот же смысл, что у Sampler конфигурации 2: раз в секунду дерево процесса раннера.
Пишется в журнал запуска, чтобы история в TurboTester показала график после хода.
Скачки — по правилам SpikeWatch конфигурации 2: у замера со скачком поле spike
с отметками и снимком процессов в этот момент.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 1.0
FLUSH_EVERY_SECONDS = 15.0
CHARS_PER_TOKEN = 4
SAMPLE_LIMIT = 7_200
_GPU_INSTANCE = re.compile(r"pid_(\d+)_.*engtype_(.+)$")
SPIKE_PROCESSES = 20
# Пороги и окно — как у SpikeWatch в TurboTester (app/platform/metrics.py), иначе скачки не сравнить.
_SPIKE_FLOOR = {"cpu": 3.0, "ram": 0.5, "gpu": 3.0, "disk": 1.0}
_SPIKE_RELATIVE = {"cpu": 1.0, "ram": 0.25, "gpu": 1.0, "disk": 1.0}
_SPIKE_READY = 3
_SPIKE_WINDOW = 8


class SpikeWatch:
    """Новый скачок — шаг вверх от последнего отмеченного уровня, а не от максимума ряда."""

    def __init__(self) -> None:
        self._values: dict[str, list[float]] = {}
        self._marked: dict[str, float] = {}

    def observe(self, metric: str, value: float | None) -> tuple[float, float] | None:
        if value is None:
            return None
        previous = self._values.setdefault(metric, [])
        found: tuple[float, float] | None = None
        if len(previous) >= _SPIKE_READY:
            window = previous[-_SPIKE_WINDOW:]
            baseline = sorted(window)[len(window) // 2]
            floor = max(_SPIKE_FLOOR[metric], _SPIKE_RELATIVE[metric] * baseline)
            last = self._marked.get(metric, baseline)
            if value >= last + floor and value >= baseline + floor:
                found = (round(value, 3), round(baseline, 3))
                self._marked[metric] = value
            elif value <= last - floor:
                self._marked[metric] = value
        previous.append(value)
        if len(previous) > 30:
            del previous[:-30]
        return found


def runner_pid(bridge: Any) -> int | None:
    process = getattr(bridge, "_process", None)
    if process is None:
        return None
    try:
        if process.poll() is not None:
            return None
        return int(process.pid)
    except Exception:  # noqa: BLE001
        return None


class _GpuCounters:
    def __init__(self) -> None:
        import win32pdh

        self._pdh = win32pdh
        self._query = win32pdh.OpenQuery()
        self._counter = win32pdh.AddEnglishCounter(self._query, r"\GPU Engine(*)\Utilization Percentage")
        win32pdh.CollectQueryData(self._query)

    def by_pid(self) -> dict[int, dict[str, float]]:
        self._pdh.CollectQueryData(self._query)
        try:
            values = self._pdh.GetFormattedCounterArray(self._counter, self._pdh.PDH_FMT_DOUBLE)
        except self._pdh.error:
            return {}
        usage: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for name, value in values.items():
            match = _GPU_INSTANCE.match(name)
            if match:
                usage[int(match.group(1))][match.group(2)] += float(value)
        return usage


class RunMetrics:
    def __init__(self, pid_of: Callable[[], int | None], on_flush: Callable[[list[dict[str, Any]]], None]) -> None:
        self._pid_of = pid_of
        self._on_flush = on_flush
        self._samples: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._chars = 0

    def note_chars(self, count: int) -> None:
        if count > 0:
            with self._lock:
                self._chars += count

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="run-metrics", daemon=True)
        self._thread.start()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._samples]

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        return self.snapshot()

    def _loop(self) -> None:
        try:
            import psutil
        except Exception as exc:  # noqa: BLE001
            logger.warning("run metrics disabled, psutil is unavailable: %s", exc)
            return
        gpu = _gpu_probe()
        cores = psutil.cpu_count() or 1
        total_ram = psutil.virtual_memory().total or 1
        processes: dict[tuple[int, float], Any] = {}
        io: dict[tuple[int, float], tuple[float, int, int]] = {}
        primed: set[tuple[int, float]] = set()
        gen_at = time.monotonic()
        chars_at = 0
        flushed_at = time.monotonic()
        spikes = SpikeWatch()
        names: dict[tuple[int, float], str] = {}
        while not self._stop.wait(INTERVAL_SECONDS):
            pid = self._pid_of()
            if not pid:
                processes.clear()
                io.clear()
                primed.clear()
                continue
            try:
                root = psutil.Process(pid)
                tree = [root, *root.children(recursive=True)]
            except (psutil.Error, OSError):
                # WinError 1455: the snapshot needs memory the machine does not have right now.
                continue
            alive: set[tuple[int, float]] = set()
            cpu = 0.0
            rss = 0
            read_bps = 0.0
            write_bps = 0.0
            engines: dict[str, float] = defaultdict(float)
            gpu_usage = gpu.by_pid() if gpu is not None else None
            rows: list[dict[str, Any]] = []
            for raw in tree:
                try:
                    key = (raw.pid, raw.create_time())
                    proc = processes.get(key)
                    if proc is None:
                        proc = raw
                        processes[key] = proc
                    if key not in primed:
                        proc.cpu_percent(None)
                        primed.add(key)
                        _disk_rate(proc, io)
                        continue
                    alive.add(key)
                    proc_cpu = proc.cpu_percent(None) / cores
                    proc_rss = proc.memory_info().rss
                    cpu += proc_cpu
                    rss += proc_rss
                    proc_read, proc_write = _disk_rate(proc, io)
                    read_bps += proc_read
                    write_bps += proc_write
                    proc_engines = gpu_usage.get(proc.pid, {}) if gpu_usage is not None else {}
                    for engine, value in proc_engines.items():
                        engines[engine] += value
                    if key not in names:
                        names[key] = proc.name()
                    rows.append(
                        {
                            "pid": proc.pid,
                            "name": names[key],
                            "cpu": round(proc_cpu, 2),
                            "ram_mb": round(proc_rss / 1_048_576, 1),
                            "gpu": round(max(proc_engines.values(), default=0.0), 2) if gpu_usage is not None else None,
                            "disk": round((proc_read + proc_write) / 1_048_576, 3),
                        }
                    )
                except psutil.Error:
                    continue
            seen: set[tuple[int, float]] = set()
            for raw in tree:
                try:
                    seen.add((raw.pid, raw.create_time()))
                except psutil.Error:
                    continue
            for key in list(processes):
                if key not in seen:
                    processes.pop(key, None)
                    io.pop(key, None)
                    primed.discard(key)
                    names.pop(key, None)
            now = time.monotonic()
            if not alive:
                gen_at = now
                continue
            elapsed = now - gen_at
            gen_at = now
            with self._lock:
                chars = self._chars
            delta = chars - chars_at
            chars_at = chars
            sample: dict[str, Any] = {
                "t": round(time.time() * 1000, 3),
                "turn": 1,
                "cpu": round(min(cpu, 100.0), 2),
                "ram": round(rss / total_ram * 100, 3),
                "ram_mb": round(rss / 1_048_576, 1),
                "disk": round((read_bps + write_bps) / 1_048_576, 3),
                "disk_read": round(read_bps / 1_048_576, 3),
                "disk_write": round(write_bps / 1_048_576, 3),
                "processes": len(alive),
                "gen": round((delta / CHARS_PER_TOKEN) / max(elapsed, 0.1), 1),
            }
            if gpu_usage is not None:
                sample["gpu"] = round(min(max(engines.values(), default=0.0), 100.0), 2)
            marks = [
                {"metric": metric, "value": found[0], "baseline": found[1]}
                for metric in ("cpu", "ram", "gpu", "disk")
                if (found := spikes.observe(metric, sample.get(metric))) is not None
            ]
            if marks:
                rows.sort(key=lambda row: (row["cpu"], row["ram_mb"]), reverse=True)
                sample["spike"] = {"marks": marks, "processes": rows[:SPIKE_PROCESSES]}
            with self._lock:
                self._samples.append(sample)
                if len(self._samples) > SAMPLE_LIMIT:
                    del self._samples[: len(self._samples) - SAMPLE_LIMIT]
            if now - flushed_at >= FLUSH_EVERY_SECONDS:
                flushed_at = now
                try:
                    self._on_flush(self.snapshot())
                except Exception:  # noqa: BLE001
                    logger.debug("run metrics flush failed", exc_info=True)


def _gpu_probe() -> _GpuCounters | None:
    if sys.platform != "win32":
        return None
    try:
        return _GpuCounters()
    except Exception as exc:  # noqa: BLE001
        logger.warning("GPU counters unavailable: %s", exc)
        return None


def _disk_rate(proc: Any, io: dict[tuple[int, float], tuple[float, int, int]]) -> tuple[float, float]:
    try:
        counters = proc.io_counters()
        key = (proc.pid, proc.create_time())
    except (AttributeError, Exception):  # noqa: BLE001
        return 0.0, 0.0
    now = time.monotonic()
    previous = io.get(key)
    io[key] = (now, counters.read_bytes, counters.write_bytes)
    if previous is None:
        return 0.0, 0.0
    elapsed = now - previous[0]
    if elapsed <= 0:
        return 0.0, 0.0
    return (
        max(0.0, counters.read_bytes - previous[1]) / elapsed,
        max(0.0, counters.write_bytes - previous[2]) / elapsed,
    )

"""Ресурсы, которые занимает агент: дерево процессов раннера (node, MCP-сервер, команды shell).

Раз в секунду для каждого идущего хода: CPU — доля всех ядер, RAM — доля физической памяти,
GPU — как в диспетчере задач: максимум по типам движков от суммы загрузки процессов дерева,
SSD — скорость чтения и записи этих процессов. Генерация — токены/с, которые модель выдала в поток
за секунду; точное число токенов SDK отдаёт только в конце хода, поэтому здесь оценка по символам.
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

import psutil

from app.platform.sessions import MetricSample, SpikeEvent, SpikeMark, store

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 1.0
CHARS_PER_TOKEN = 4
_GPU_INSTANCE = re.compile(r"pid_(\d+)_.*engtype_(.+)$")
# Новый скачок — шаг вверх от последнего сохранённого уровня, не от исторического максимума.
# Более сильный следующий скачок дописывается рядом и не затирает предыдущие.
# Порог: не меньше абсолютного минимума и не меньше доли от уровня перед точкой,
# чтобы плавный рост (например, ОЗУ) не превращался в десятки «скачков».
_SPIKE_FLOOR = {"cpu": 3.0, "ram": 0.5, "gpu": 3.0, "disk": 1.0}
_SPIKE_RELATIVE = {"cpu": 1.0, "ram": 0.25, "gpu": 1.0, "disk": 1.0}
_SPIKE_READY = 3
_SPIKE_WINDOW = 8


class SpikeWatch:
    """Скачки одной сессии. Решение локальное: уровень перед точкой, а не максимум ряда."""

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


def spikes_from_samples(samples: list[MetricSample]) -> list[SpikeEvent]:
    """Те же правила, что у живого сэмплера. Процессов в ряду уже нет — список пустой."""
    watch = SpikeWatch()
    events: list[SpikeEvent] = []
    for sample in samples:
        marks: list[SpikeMark] = []
        for metric, value in (
            ("cpu", sample.cpu),
            ("ram", sample.ram),
            ("gpu", sample.gpu),
            ("disk", sample.disk),
        ):
            found = watch.observe(metric, value)
            if found is not None:
                marks.append(SpikeMark(metric=metric, value=found[0], baseline=found[1]))
        if marks:
            events.append(SpikeEvent(t=sample.t, turn=sample.turn, marks=marks))
    return events


class _GpuCounters:
    """Счётчики Windows «GPU Engine»: загрузка по каждому процессу и движку."""

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


class Sampler:
    def __init__(self, active: Callable[[], list[tuple[str, int, int]]]) -> None:
        self._active = active
        self._cache: dict[tuple[int, float], psutil.Process] = {}
        # Предыдущие счётчики диска: (момент, прочитано, записано) в байтах.
        self._io: dict[tuple[int, float], tuple[float, int, int]] = {}
        self._spikes: dict[str, SpikeWatch] = {}
        # Момент прошлого замера генерации по сессии (monotonic).
        self._gen_at: dict[str, float] = {}
        self._gpu: _GpuCounters | None = None
        self._gpu_failed = sys.platform != "win32"
        self._started = False
        self._lock = threading.Lock()

    def ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, name="platform-metrics", daemon=True).start()

    def _loop(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                logger.exception("platform metrics tick failed")
            time.sleep(max(0.1, INTERVAL_SECONDS - (time.monotonic() - started)))

    def _gpu_usage(self) -> dict[int, dict[str, float]] | None:
        if self._gpu_failed:
            return None
        try:
            if self._gpu is None:
                self._gpu = _GpuCounters()
            return self._gpu.by_pid()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GPU counters unavailable: %s", exc)
            self._gpu_failed = True
            return None

    def _process(self, proc: psutil.Process) -> psutil.Process:
        key = (proc.pid, proc.create_time())
        cached = self._cache.get(key)
        if cached is None:
            cached = proc
            cached.cpu_percent(None)
            self._cache[key] = cached
        return cached

    def _tick(self) -> None:
        active = self._active()
        if not active:
            self._cache.clear()
            self._io.clear()
            self._spikes.clear()
            self._gen_at.clear()
            return
        gpu = self._gpu_usage()
        cores = psutil.cpu_count() or 1
        total_ram = psutil.virtual_memory().total
        alive: set[tuple[int, float]] = set()
        seen_sessions: set[str] = set()
        for session_id, pid, turn in active:
            seen_sessions.add(session_id)
            try:
                root = psutil.Process(pid)
                tree = [root, *root.children(recursive=True)]
            except psutil.Error:
                continue
            cpu = 0.0
            rss = 0
            read_bps = 0.0
            write_bps = 0.0
            engines: dict[str, float] = defaultdict(float)
            processes: list[dict[str, Any]] = []
            for raw in tree:
                try:
                    proc = self._process(raw)
                    alive.add((proc.pid, proc.create_time()))
                    proc_cpu = proc.cpu_percent(None) / cores
                    proc_rss = proc.memory_info().rss
                    proc_read, proc_write = self._disk_rate(proc)
                    name = proc.name()
                except psutil.Error:
                    continue
                proc_gpu = 0.0
                if gpu is not None:
                    for engine, value in gpu.get(proc.pid, {}).items():
                        engines[engine] += value
                    proc_gpu = max(gpu.get(proc.pid, {}).values(), default=0.0)
                cpu += proc_cpu
                rss += proc_rss
                read_bps += proc_read
                write_bps += proc_write
                processes.append(
                    {
                        "pid": proc.pid,
                        "name": name,
                        "cpu": round(proc_cpu, 2),
                        "ram_mb": round(proc_rss / 1_048_576, 1),
                        "gpu": round(proc_gpu, 2) if gpu is not None else None,
                        "disk": round((proc_read + proc_write) / 1_048_576, 3),
                    }
                )
            processes.sort(key=lambda item: (-item["cpu"], -item["ram_mb"]))
            now = time.monotonic()
            elapsed = now - self._gen_at.get(session_id, now - INTERVAL_SECONDS)
            self._gen_at[session_id] = now
            generated = store.take_generated(session_id) / CHARS_PER_TOKEN
            sample = MetricSample(
                t=time.time() * 1000,
                turn=turn,
                cpu=round(min(cpu, 100.0), 2),
                ram=round(rss / total_ram * 100, 3),
                ram_mb=round(rss / 1_048_576, 1),
                gpu=round(min(max(engines.values(), default=0.0), 100.0), 2) if gpu is not None else None,
                disk=round((read_bps + write_bps) / 1_048_576, 3),
                disk_read=round(read_bps / 1_048_576, 3),
                disk_write=round(write_bps / 1_048_576, 3),
                processes=len(processes),
                gen=round(generated / max(elapsed, 0.1), 1),
            )
            watch = self._spikes.setdefault(session_id, SpikeWatch())
            spike_marks = [
                (metric, found[0], found[1])
                for metric, value in (
                    ("cpu", sample.cpu),
                    ("ram", sample.ram),
                    ("gpu", sample.gpu),
                    ("disk", sample.disk),
                )
                if (found := watch.observe(metric, value)) is not None
            ]
            store.add_metric(session_id, sample, processes, spike_marks or None)
        for session_id in list(self._spikes):
            if session_id not in seen_sessions:
                del self._spikes[session_id]
        for session_id in list(self._gen_at):
            if session_id not in seen_sessions:
                del self._gen_at[session_id]
        for key in list(self._cache):
            if key not in alive:
                del self._cache[key]
                self._io.pop(key, None)

    def _disk_rate(self, proc: psutil.Process) -> tuple[float, float]:
        """Байты чтения и записи в секунду с прошлого замера. Первый замер — ноль."""
        try:
            io = proc.io_counters()
        except (psutil.Error, AttributeError):
            return 0.0, 0.0
        key = (proc.pid, proc.create_time())
        now = time.monotonic()
        previous = self._io.get(key)
        self._io[key] = (now, io.read_bytes, io.write_bytes)
        if previous is None:
            return 0.0, 0.0
        elapsed = now - previous[0]
        if elapsed <= 0:
            return 0.0, 0.0
        return max(0.0, io.read_bytes - previous[1]) / elapsed, max(0.0, io.write_bytes - previous[2]) / elapsed

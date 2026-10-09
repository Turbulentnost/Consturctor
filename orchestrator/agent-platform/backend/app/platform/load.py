"""Нагрузка этой машины: ЦП и ОЗУ через psutil, видеокарта через nvidia-smi."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

import psutil

from app.platform.sessions import MachineLoad

logger = logging.getLogger(__name__)

_gpu_probed = False
_gpu_ok = False


def sample_machine() -> MachineLoad:
    memory = psutil.virtual_memory()
    gpu_percent, gpu_used, gpu_total, gpu_available = _read_gpu()
    return MachineLoad(
        cpu_percent=float(psutil.cpu_percent(interval=None)),
        ram_percent=float(memory.percent),
        ram_used_mb=int(memory.used // (1024 * 1024)),
        ram_total_mb=int(memory.total // (1024 * 1024)),
        gpu_percent=gpu_percent,
        gpu_memory_used_mb=gpu_used,
        gpu_memory_total_mb=gpu_total,
        gpu_available=gpu_available,
    )


def _read_gpu() -> tuple[float | None, int | None, int | None, bool]:
    global _gpu_probed, _gpu_ok
    if _gpu_probed and not _gpu_ok:
        return None, None, None, False
    if not _gpu_probed and shutil.which("nvidia-smi") is None:
        _gpu_probed = True
        _gpu_ok = False
        return None, None, None, False
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("nvidia-smi недоступен: %s", exc)
        _gpu_probed = True
        _gpu_ok = False
        return None, None, None, False
    _gpu_probed = True
    line = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not line:
        _gpu_ok = False
        return None, None, None, False
    parts = [part.strip() for part in line[0].split(",")]
    if len(parts) < 3:
        _gpu_ok = False
        return None, None, None, False
    try:
        percent = float(parts[0])
        used = int(float(parts[1]))
        total = int(float(parts[2]))
    except ValueError:
        _gpu_ok = False
        return None, None, None, False
    _gpu_ok = True
    return percent, used, total, True

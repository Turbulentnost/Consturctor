"""Локальный сервис ИИ-агентов Оркестратора: платформа TurboTester (конфигурация 2) на этом компьютере.

Запускает Electron main (src/main/agentPlatform.ts). Встроенный Python установщика видит
desktop/ Constructor через ._pth, где тоже есть пакет app, поэтому своя папка идёт первой.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if sys.path[:1] != [ROOT]:
    sys.path.insert(0, ROOT)

from app.main import run  # noqa: E402

if __name__ == "__main__":
    run()

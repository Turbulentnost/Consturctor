"""Пути к встроенным регламентам для шаблонов конструктора."""

from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def act_registry_regulation_path() -> Path | None:
    """ACT_REGISTRY.md для шаблона «ACT-реестр» (dev + собранный exe)."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "regulations" / "ACT_REGISTRY.md")
    candidates.extend(
        [
            Path(__file__).resolve().parent / "regulations" / "ACT_REGISTRY.md",
            _repo_root() / "ACT_REGISTRY.md",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None

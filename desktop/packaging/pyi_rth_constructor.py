"""Runtime hook: pywin32 DLL search path inside the onedir bundle."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    extra = root / "pywin32_system32"
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(root))
        if extra.is_dir():
            os.add_dll_directory(str(extra))
    current = os.environ.get("PATH", "")
    prefix = str(root) if not extra.is_dir() else f"{root}{os.pathsep}{extra}"
    os.environ["PATH"] = prefix if not current else f"{prefix}{os.pathsep}{current}"

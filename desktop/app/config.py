from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        """Fallback for helper Python environments without python-dotenv."""
        return False


def _desktop_root() -> Path:
    # PyInstaller onedir/onefile: config next to the .exe
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundle_root() -> Path:
    # Unpackaged resources (fonts/icons) live in _MEIPASS for onefile.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return _desktop_root()


DESKTOP_ROOT = _desktop_root()
BUNDLE_ROOT = _bundle_root()
REPO_ROOT = DESKTOP_ROOT.parent if not getattr(sys, "frozen", False) else DESKTOP_ROOT

# Prefer .env beside the exe / desktop folder.
load_dotenv(DESKTOP_ROOT / ".env")
if getattr(sys, "frozen", False):
    load_dotenv(DESKTOP_ROOT / ".env", override=False)


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://127.0.0.1:7812").rstrip("/")


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)

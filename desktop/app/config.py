from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

DESKTOP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DESKTOP_ROOT.parent
load_dotenv(DESKTOP_ROOT / ".env")


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://127.0.0.1:7812").rstrip("/")


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"

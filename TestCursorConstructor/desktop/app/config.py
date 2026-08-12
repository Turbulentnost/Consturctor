from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

DESKTOP_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(DESKTOP_ROOT / ".env")


def api_key() -> str:
    return (os.getenv("CURSOR_API_KEY") or "").strip()


def model_id() -> str:
    return (os.getenv("CURSOR_MODEL") or "composer").strip() or "composer"

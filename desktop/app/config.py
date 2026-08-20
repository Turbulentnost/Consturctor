from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


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

# Prefer .env beside the exe / desktop folder (override stale QSettings / old defaults).
load_dotenv(DESKTOP_ROOT / ".env", override=True)
if getattr(sys, "frozen", False):
    load_dotenv(BUNDLE_ROOT / ".env", override=False)

from app.session_store import saved_auth_url, saved_backend_url


def backend_url() -> str:
    """Локальный gateway: агенты, workflow, LLM, инструменты через Docker."""
    env_url = os.getenv("BACKEND_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    if getattr(sys, "frozen", False):
        return "http://127.0.0.1:7812"
    saved = saved_backend_url().rstrip("/")
    stale_markers = ()
    if saved and not any(marker in saved for marker in stale_markers):
        return saved
    return "http://127.0.0.1:7812"


def auth_url() -> str:
    """Общий сервер входа (ERP SQL / 1С). Если не задан — тот же, что BACKEND_URL."""
    env_url = os.getenv("AUTH_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    saved = saved_auth_url().rstrip("/")
    if saved:
        return saved
    return backend_url()


def catalog_url() -> str:
    """Каталог опубликованных агентов (общий сервер)."""
    env_url = os.getenv("WORKFLOWS_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    auth = auth_url()
    local = backend_url()
    if auth.rstrip("/") != local.rstrip("/"):
        return auth
    return local


def skip_login_fio() -> str:
    flag = os.getenv("SKIP_LOGIN", "").strip().lower()
    fio = os.getenv("SKIP_LOGIN_FIO", "").strip()
    if flag in {"1", "true", "yes", "on"} or fio:
        return fio or "Жалыбин Максим Дмитриевич"
    return ""


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)

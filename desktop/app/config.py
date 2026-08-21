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

# Sidecar .env beside the exe wins; bundled copy inside onefile is fallback.
load_dotenv(DESKTOP_ROOT / ".env")
if getattr(sys, "frozen", False):
    load_dotenv(BUNDLE_ROOT / ".env", override=False)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def auth_skip_login_page() -> bool:
    return _env_flag("AUTH_SKIP_LOGIN_PAGE")


def erp_login() -> str:
    return os.getenv("ERP_LOGIN", "").strip()


def erp_password() -> str:
    return os.getenv("ERP_PASSWORD", "")


def backend_url() -> str:
    host = os.getenv("HOST_IP", "").strip()
    default = f"http://{host}:7812" if host else "http://192.168.1.157:7812"
    return os.getenv("BACKEND_URL", default).rstrip("/")


def host_ip() -> str:
    return os.getenv("HOST_IP", "").strip()


def auth_url() -> str:
    return os.getenv("AUTH_URL", (f"http://{host_ip()}:7812" if host_ip() else backend_url())).rstrip("/")


def auth_uses_remote_server() -> bool:
    return auth_url().casefold() != backend_url().casefold()


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)

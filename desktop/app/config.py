from __future__ import annotations

import os
import sys
from pathlib import Path

from app.envfile import load_env_file


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
load_env_file(DESKTOP_ROOT / ".env")
if getattr(sys, "frozen", False):
    load_env_file(DESKTOP_ROOT / ".env", override=False)
    _bundled_browsers = DESKTOP_ROOT / "ms-playwright"
    if _bundled_browsers.is_dir() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_bundled_browsers)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def constructor_instance() -> str:
    return os.getenv("CONSTRUCTOR_INSTANCE", "").strip()


def auth_test_user() -> bool:
    return _env_flag("CONSTRUCTOR_TEST_USER")


def auth_skip_login_page() -> bool:
    return _env_flag("AUTH_SKIP_LOGIN_PAGE") or auth_test_user()


def erp_login() -> str:
    return os.getenv("ERP_LOGIN", "").strip()


def erp_password() -> str:
    return os.getenv("ERP_PASSWORD", "")


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://127.0.0.1:7812").rstrip("/")


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)

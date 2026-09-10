from __future__ import annotations

import os
import sys
from pathlib import Path

from app.envfile import load_env_file, read_env_text


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
load_env_file(DESKTOP_ROOT / ".env", override=True)
if getattr(sys, "frozen", False):
    load_env_file(DESKTOP_ROOT / ".env", override=True)
    _bundled_browsers = DESKTOP_ROOT / "ms-playwright"
    if _bundled_browsers.is_dir() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_bundled_browsers)

_CURSOR_ENV_KEYS = ("CURSOR_API_KEY", "CURSOR_API_BASE_URL", "CURSOR_SDK_MODEL")


def _env_value(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    prefix = f"{name}="
    for line in read_env_text(path).splitlines():
        text = line.strip()
        if not text.startswith(prefix):
            continue
        raw = text[len(prefix):].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            raw = raw[1:-1]
        return raw.strip()
    return ""


def _cursor_env_candidates() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA") or "")
    workspace = REPO_ROOT.parent if not getattr(sys, "frozen", False) else DESKTOP_ROOT
    return [
        appdata / "constructor-desktop-electron" / ".env",
        appdata / "Orchestrator" / ".env",
        DESKTOP_ROOT / ".env",
        REPO_ROOT / "backend" / ".env",
        workspace / "Consturctor" / "desktop" / ".env",
        workspace / "Consturctor" / "backend" / ".env",
    ]


def reload_cursor_api_key() -> str:
    """Перечитать CURSOR_* из .env перед каждым запуском SDK (не кешировать старый ключ)."""
    for path in _cursor_env_candidates():
        key = _env_value(path, "CURSOR_API_KEY")
        if key:
            os.environ["CURSOR_API_KEY"] = key
            for name in _CURSOR_ENV_KEYS:
                if name == "CURSOR_API_KEY":
                    continue
                extra = _env_value(path, name)
                if extra:
                    os.environ[name] = extra
            return key
    return os.getenv("CURSOR_API_KEY", "").strip()


_load_missing_cursor_env = reload_cursor_api_key
reload_cursor_api_key()


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
    return os.getenv("BACKEND_URL", "http://192.168.1.157:7812").rstrip("/")


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)

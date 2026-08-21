from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _desktop_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return _desktop_root()


DESKTOP_ROOT = _desktop_root()
BUNDLE_ROOT = _bundle_root()
ROOT = DESKTOP_ROOT

for _path in (BUNDLE_ROOT, DESKTOP_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _configure_cursor_bridge() -> None:
    """Frozen exe: local Cursor bridge (node.exe), not 1C/gateway."""
    override = (os.environ.get("CURSOR_SDK_BRIDGE_BIN") or "").strip()
    candidates: list[Path] = []
    if override:
        raw = Path(override)
        candidates.append(raw if raw.is_absolute() else DESKTOP_ROOT / raw)
    candidates.append(DESKTOP_ROOT / "cursor-sdk-bridge" / "bin" / "cursor-sdk-bridge.cmd")
    if getattr(sys, "frozen", False):
        candidates.append(
            BUNDLE_ROOT / "cursor_sdk" / "_vendor" / "bridge" / "bin" / "cursor-sdk-bridge.cmd"
        )
    for candidate in candidates:
        if candidate.is_file() and (candidate.parent / "node.exe").is_file():
            os.environ["CURSOR_SDK_BRIDGE_BIN"] = str(candidate.resolve())
            return


# Рядом с exe важнее; внутри onefile — запасной вариант.
load_dotenv(DESKTOP_ROOT / ".env")
if getattr(sys, "frozen", False):
    load_dotenv(BUNDLE_ROOT / ".env", override=False)

_configure_cursor_bridge()

from app.cursor_sdk_win_patch import apply as _apply_cursor_sdk_win_patch

_apply_cursor_sdk_win_patch()


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)


DATA_DIR = DESKTOP_ROOT / "data"
CARDS_DB = DATA_DIR / "cards.db"
REGULATIONS_DIR = DATA_DIR / "regulations"
WORKSPACES_DIR = DATA_DIR / "workspaces"


def ensure_data_dirs() -> None:
    for path in (DATA_DIR, REGULATIONS_DIR, WORKSPACES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def cursor_api_key() -> str:
    return (os.environ.get("CURSOR_API_KEY") or "").strip()


def cursor_model() -> str:
    return (os.environ.get("CURSOR_MODEL") or "composer-2.5").strip()


def backend_url() -> str:
    return (os.environ.get("BACKEND_URL") or "http://192.168.1.157:7812").strip()


def auth_skip_login_page() -> bool:
    return (os.environ.get("AUTH_SKIP_LOGIN_PAGE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def erp_login() -> str:
    return (os.environ.get("ERP_LOGIN") or "").strip()


def erp_password() -> str:
    return (os.environ.get("ERP_PASSWORD") or "").strip()


def regagent_test_login_enabled() -> bool:
    return (os.environ.get("REGAGENT_TEST_LOGIN") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def regagent_test_fio() -> str:
    return (
        os.environ.get("REGAGENT_TEST_FIO") or "Ильченко Екатерина Александровна"
    ).strip()


def regagent_test_password() -> str:
    return (os.environ.get("REGAGENT_TEST_PASSWORD") or "123").strip()


def regagent_test_user_id() -> str:
    return (os.environ.get("REGAGENT_TEST_USER_ID") or "test-ilchenko").strip()


def odata_base_url() -> str:
    return (os.environ.get("ODATA_BASE_URL") or "").strip().rstrip("/")


def odata_username() -> str:
    return (os.environ.get("ODATA_USERNAME") or "").strip()


def odata_password() -> str:
    return (os.environ.get("ODATA_PASSWORD") or "").strip()


def odata_auth() -> tuple[str, str] | None:
    user = (odata_username() or erp_login()).strip()
    password = (odata_password() or erp_password()).strip()
    if user and password:
        return user, password
    return None


def docflow_odata_base_url() -> str:
    explicit = (os.environ.get("DOCFLOW_ODATA_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    erp = odata_base_url()
    if "/erp_pm/" in erp:
        return erp.replace("/erp_pm/", "/doc/").rstrip("/")
    return ""


def docflow_odata_username() -> str:
    return (
        os.environ.get("DOCFLOW_ODATA_USERNAME")
        or odata_username()
        or erp_login()
    ).strip()


def docflow_odata_password() -> str:
    return (
        os.environ.get("DOCFLOW_ODATA_PASSWORD")
        or odata_password()
        or erp_password()
    ).strip()


def odata_timeout_sec() -> int:
    raw = (os.environ.get("ODATA_TIMEOUT_SEC") or "30").strip()
    try:
        return max(5, min(int(raw), 120))
    except ValueError:
        return 30

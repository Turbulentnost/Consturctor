"""Замена desktop/app/config.py Constructor: пути и адрес backend берутся из TurboTest."""

from __future__ import annotations

from pathlib import Path

from app import tool_settings
from app.config import settings

# Инструменты Constructor читают ONEC_*, ERP_*, OUTLOOK_* и т.п. прямо из os.environ.
tool_settings.ensure_applied()

# host._tools_root() и plan_export ищут CLI-инструменты в <root>/tools.
DESKTOP_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = DESKTOP_ROOT
REPO_ROOT = DESKTOP_ROOT


def backend_url() -> str:
    return settings.constructor_api_url.rstrip("/")


def repo_root() -> Path:
    return REPO_ROOT


def tools_dir() -> Path:
    return REPO_ROOT / "tools"


def bundle_path(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts)

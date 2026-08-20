"""Команды запуска desktop host / launcher (исходники и собранный exe)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_worker_argv(argv: list[str] | None = None) -> bool:
    args = argv if argv is not None else sys.argv[1:]
    worker_flags = {"--desktop-host", "--desktop-launcher", "--com-worker", "--background", "--hidden"}
    return any(item in worker_flags for item in args)


def desktop_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def constructor_root() -> Path:
    from app.config import DESKTOP_ROOT, repo_root

    if getattr(sys, "frozen", False):
        return DESKTOP_ROOT
    return repo_root()


def host_executable(root: Path | None = None) -> Path | None:
    base = root or desktop_root()
    candidate = base / "DesktopHost.exe"
    return candidate if candidate.is_file() else None


def launcher_executable(root: Path | None = None) -> Path | None:
    base = root or desktop_root()
    candidate = base / "DesktopLauncher.exe"
    return candidate if candidate.is_file() else None


def _frozen_self_command(*flags: str) -> list[str]:
    return [str(Path(sys.executable).resolve()), *flags]


def build_host_command(*, root: Path | None = None) -> list[str]:
    base = root or constructor_root()
    bundled = host_executable(base)
    if bundled is not None:
        return [str(bundled)]
    if getattr(sys, "frozen", False):
        return _frozen_self_command("--desktop-host")
    py = shutil.which("py") or sys.executable
    cmd = [py]
    if py.casefold().endswith("py.exe") or Path(py).name.casefold() == "py":
        cmd.append("-3.12")
    cmd.extend(["-m", "platform_desktop_host.main"])
    return cmd


def build_launcher_command(*, root: Path | None = None) -> list[str]:
    base = root or constructor_root()
    bundled = launcher_executable(base)
    if bundled is not None:
        return [str(bundled)]
    if getattr(sys, "frozen", False):
        return _frozen_self_command("--desktop-launcher")
    py = shutil.which("py") or sys.executable
    cmd = [py]
    if py.casefold().endswith("py.exe") or Path(py).name.casefold() == "py":
        cmd.append("-3.12")
    cmd.extend(["-m", "platform_desktop_launcher.main"])
    return cmd


def extend_pythonpath(env: dict[str, str], root: Path) -> None:
    """Добавить пути репозитория для dev-запуска через py -m."""
    if getattr(sys, "frozen", False):
        return
    paths = [
        root,
        root / "services" / "platform-desktop-host",
        root / "services" / "platform-desktop-launcher",
        root / "services" / "platform-tool-com",
        root / "services" / "platform-tool-filesystem",
        root / "services" / "platform-tool-shell",
        root / "services" / "platform-tool-imap",
        root / "services" / "platform-tool-browser",
        root / "services" / "platform-tool-onec",
        root / "services" / "platform-tool-onec-com",
        root / "platform-contracts",
        root / "platform-db",
        root / "platform-service-common",
    ]
    existing = env.get("PYTHONPATH", "")
    merged: list[str] = []
    for item in paths:
        text = str(item)
        if item.is_dir() and text not in merged:
            merged.append(text)
    if existing:
        merged.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(merged)

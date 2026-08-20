"""Собрать портативный onedir Constructor Desktop (все инструменты + COM)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from installer.server_env import backend_base_url, set_backend_url

DESKTOP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DESKTOP_ROOT.parent
SPEC_PATH = DESKTOP_ROOT / "NewConstructor.spec"
DIST_NAME = "ConstructorDesktop"
GUI_EXE_NAME = "ConstructorDesktop.exe"
COM_EXE_NAME = "ConstructorComWorker.exe"
SKIP_TOOL_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "tests",
    "venv",
}
BROWSER_PREFIXES = ("chromium", "ffmpeg", "winldd")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка Constructor Desktop exe")
    parser.add_argument(
        "--skip-browsers",
        action="store_true",
        help="Не копировать Chromium Playwright в дистрибутив",
    )
    parser.add_argument(
        "--skip-pyinstaller",
        action="store_true",
        help="Только дописать tools/.env/браузеры в уже собранный dist",
    )
    parser.add_argument(
        "--backend-url",
        default="",
        help="BACKEND_URL для .env рядом с exe (по умолчанию LAN IP этой машины)",
    )
    args = parser.parse_args(argv)

    stash = None
    if not args.skip_pyinstaller:
        if args.skip_browsers:
            stash = _stash_playwright(DESKTOP_ROOT / "dist" / DIST_NAME)
        _ensure_pyinstaller()
        try:
            _run_pyinstaller()
        finally:
            if stash is not None:
                _restore_playwright(DESKTOP_ROOT / "dist" / DIST_NAME, stash)
    dist = DESKTOP_ROOT / "dist" / DIST_NAME
    gui = dist / GUI_EXE_NAME
    com = dist / COM_EXE_NAME
    if not gui.is_file() or not com.is_file():
        print(f"Сборка не создала {GUI_EXE_NAME} и {COM_EXE_NAME} в {dist}", file=sys.stderr)
        return 1
    _copy_tools(dist)
    _install_env(dist, backend_url=args.backend_url)
    if not args.skip_browsers:
        _copy_playwright_browsers(dist)
    _write_readme(dist, backend_url=args.backend_url)
    _write_start_cmd(dist)
    print(f"Готово: {gui}")
    print(f"Переносите всю папку: {dist}")
    return 0


def _stash_playwright(dist: Path) -> Path | None:
    src = dist / "ms-playwright"
    if not src.is_dir():
        return None
    dest = dist.parent / "_ms-playwright-stash"
    if dest.exists():
        shutil.rmtree(dest)
    src.rename(dest)
    return dest


def _restore_playwright(dist: Path, stash: Path) -> None:
    dest = dist / "ms-playwright"
    if dest.exists():
        shutil.rmtree(dest)
    dist.mkdir(parents=True, exist_ok=True)
    stash.rename(dest)


def _ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def _run_pyinstaller() -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_PATH),
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=str(DESKTOP_ROOT))


def _copy_tools(dist: Path) -> None:
    src = REPO_ROOT / "tools"
    dest = dist / "tools"
    if not src.is_dir():
        print(f"Папка tools не найдена: {src}")
        return
    if dest.exists():
        shutil.rmtree(dest)

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set()
        for name in names:
            path = Path(directory) / name
            if name in SKIP_TOOL_DIRS or name.endswith(".pyc"):
                skipped.add(name)
            elif path.is_dir() and name == "ms-playwright":
                skipped.add(name)
        return skipped

    shutil.copytree(src, dest, ignore=ignore)
    print(f"Скопированы локальные инструменты: {dest}")


def _install_env(dist: Path, *, backend_url: str = "") -> None:
    src = DESKTOP_ROOT / ".env"
    example = DESKTOP_ROOT / ".env.example"
    dest = dist / ".env"
    if src.is_file():
        shutil.copy2(src, dest)
    elif example.is_file():
        shutil.copy2(example, dest)
    url = backend_base_url(override=backend_url)
    set_backend_url(dest, url)
    print(f"Скопирован .env рядом с exe, BACKEND_URL={url}")


def _copy_playwright_browsers(dist: Path) -> None:
    src = _playwright_cache()
    if src is None:
        print("Кэш Playwright не найден, site_browser/roseltorg возьмут системный браузер")
        return
    dest = dist / "ms-playwright"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied = 0
    for child in src.iterdir():
        name = child.name
        if name == ".links" or name.startswith(BROWSER_PREFIXES):
            target = dest / name
            if child.is_dir():
                shutil.copytree(child, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(child, target)
            copied += 1
    print(f"Скопирован Playwright Chromium ({copied} элементов): {dest}")


def _playwright_cache() -> Path | None:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override))
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.append(Path(local) / "ms-playwright")
    candidates.append(Path.home() / "AppData" / "Local" / "ms-playwright")
    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    return None


def _write_readme(dist: Path, backend_url: str = "") -> None:
    url = backend_url or backend_base_url()
    text = f"""Constructor Desktop — портативная папка

Запуск: ConstructorDesktop.exe
Переносите всю папку {DIST_NAME}, не один файл.

Backend
  Приложение ходит на сервер из .env (BACKEND_URL).
  Сейчас: {url}
  Backend должен быть запущен и доступен по этому адресу из сети.

COM
  Outlook: на целевом ПК должен быть установлен Outlook.
  1С: 32-bit V83.COMConnector и C:\\Windows\\SysWOW64\\cscript.exe.
  ConstructorComWorker.exe — служебный консольный процесс (не запускайте вручную).

Инструменты
  tools\\ — web_search, site_browser, roseltorg.
  ms-playwright\\ — Chromium для Playwright, если он был скопирован при сборке.
"""
    (dist / "README.txt").write_text(text, encoding="utf-8")


def _write_start_cmd(dist: Path) -> None:
    (dist / "Start-ConstructorDesktop.cmd").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "start \"\" \"%~dp0ConstructorDesktop.exe\"\r\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())

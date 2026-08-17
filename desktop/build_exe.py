from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_DIR = ROOT / "desktop"
TOOLS_DIR = ROOT / "tools" / "roseltorg_tender_search"
BUILD_DIR = ROOT / "build" / "desktop-exe"
PYI_WORK = BUILD_DIR / "work"
PYI_DIST = BUILD_DIR / "pyinstaller-dist"
FINAL_DIST = ROOT / "dist" / "ConstructorDesktop"


def main() -> int:
    ensure_dependencies()
    clean_build_dirs()
    build_roseltorg_tool()
    build_desktop()
    assemble_distribution()
    print()
    print(f"Готово: {FINAL_DIST}")
    print(f"Запуск: {FINAL_DIST / 'ConstructorDesktop.exe'}")
    return 0


def ensure_dependencies() -> None:
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(DESKTOP_DIR / "requirements.txt"),
            "-r",
            str(TOOLS_DIR / "requirements.txt"),
            "pyinstaller",
        ],
        cwd=ROOT,
    )
    run([sys.executable, "-m", "playwright", "install", "chromium"], cwd=ROOT)


def clean_build_dirs() -> None:
    for path in (BUILD_DIR, FINAL_DIST):
        if path.exists():
            shutil.rmtree(path)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)


def build_roseltorg_tool() -> None:
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name",
            "roseltorg_tender_search",
            "--distpath",
            str(PYI_DIST / "tools"),
            "--workpath",
            str(PYI_WORK / "roseltorg"),
            "--specpath",
            str(BUILD_DIR / "spec"),
            "--paths",
            str(TOOLS_DIR),
            "--collect-all",
            "playwright",
            str(TOOLS_DIR / "roseltorg_tool.py"),
        ],
        cwd=ROOT,
    )


def build_desktop() -> None:
    add_data = f"{DESKTOP_DIR / 'app' / 'ui' / 'temp'}{os.pathsep}app/ui/temp"
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--console",
            "--name",
            "ConstructorDesktop",
            "--distpath",
            str(PYI_DIST),
            "--workpath",
            str(PYI_WORK / "desktop"),
            "--specpath",
            str(BUILD_DIR / "spec"),
            "--paths",
            str(DESKTOP_DIR),
            "--add-data",
            add_data,
            str(DESKTOP_DIR / "main.py"),
        ],
        cwd=ROOT,
    )


def assemble_distribution() -> None:
    app_dir = PYI_DIST / "ConstructorDesktop"
    if not app_dir.exists():
        raise RuntimeError(f"PyInstaller не создал папку {app_dir}")
    shutil.copytree(app_dir, FINAL_DIST)

    env_source = DESKTOP_DIR / ".env"
    env_target = FINAL_DIST / ".env"
    if env_source.exists():
        shutil.copy2(env_source, env_target)
    elif not env_target.exists():
        env_target.write_text("BACKEND_URL=http://127.0.0.1:7812\n", encoding="utf-8")

    target_tool_dir = FINAL_DIST / "tools" / "roseltorg_tender_search"
    shutil.copytree(
        TOOLS_DIR,
        target_tool_dir,
        ignore=shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "report.xlsx",
            "*.pyc",
        ),
    )
    tool_exe = PYI_DIST / "tools" / "roseltorg_tender_search.exe"
    if not tool_exe.exists():
        raise RuntimeError(f"PyInstaller не создал {tool_exe}")
    shutil.copy2(tool_exe, target_tool_dir / tool_exe.name)
    copy_playwright_browsers(target_tool_dir)


def copy_playwright_browsers(target_tool_dir: Path) -> None:
    source = playwright_browsers_dir()
    if source is None:
        print("Внимание: папка браузеров Playwright не найдена, запускаю без копирования браузера.")
        return
    shutil.copytree(
        source,
        target_tool_dir / "ms-playwright",
        ignore=shutil.ignore_patterns(".links"),
    )


def playwright_browsers_dir() -> Path | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured and configured != "0":
        path = Path(configured)
        return path if path.exists() else None
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        path = Path(local_app_data) / "ms-playwright"
        if path.exists():
            return path
    return None


def run(command: list[str], *, cwd: Path) -> None:
    print("$ " + " ".join(str(part) for part in command))
    subprocess.run(command, cwd=cwd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())

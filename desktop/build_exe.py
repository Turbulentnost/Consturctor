from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_DIR = ROOT / "desktop"
TOOLS_DIR = ROOT / "tools" / "roseltorg_tender_search"
BUILD_DIR = ROOT / "build" / "desktop-exe"
PYI_WORK = BUILD_DIR / "work"
PYI_DIST = BUILD_DIR / "pyinstaller-dist"
FINAL_DIST = ROOT / "dist" / "ConstructorDesktop"

def ensure_64bit_python() -> None:
    if sys.maxsize > 2**32:
        return

    python64 = find_64bit_python()
    if python64 is None:
        raise SystemExit(
            "Сборка требует 64-bit Python: PySide6 не публикует wheels для 32-bit Windows.\n"
            f"Сейчас используется: {sys.executable}\n"
            "Установите Python 3.12 (64-bit) и запустите:\n"
            "  py -3.12 build_exe.py"
        )

    if Path(sys.executable).resolve() != python64.resolve():
        print(f"32-bit Python обнаружен. Перезапуск через 64-bit: {python64}")
        result = subprocess.run([str(python64), *sys.argv], cwd=DESKTOP_DIR)
        raise SystemExit(result.returncode)


def find_64bit_python() -> Path | None:
    candidates: list[Path] = []

    if sys.platform == "win32":
        try:
            listing = subprocess.run(
                ["py", "-0p"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in listing.stdout.splitlines():
                tag = line.strip().split()[0] if line.strip() else ""
                if "-32" in tag:
                    continue
                path = Path(line.strip().split()[-1])
                if path.suffix.lower() == ".exe":
                    candidates.append(path)
        except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
            pass

        version_tag = f"Python{sys.version_info.major}{sys.version_info.minor}"
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "Python" / version_tag / "python.exe")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            probe = subprocess.run(
                [str(resolved), "-c", "import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)"],
                capture_output=True,
                check=False,
            )
        except OSError:
            continue
        if probe.returncode == 0:
            return resolved
    return None


PLATFORM_PATHS = [
    ROOT / "platform-contracts",
    ROOT / "platform-db",
    ROOT / "platform-service-common",
    ROOT / "services" / "platform-desktop-host",
    ROOT / "services" / "platform-desktop-launcher",
    ROOT / "services" / "platform-tool-com",
    ROOT / "services" / "platform-tool-filesystem",
    ROOT / "services" / "platform-tool-shell",
    ROOT / "services" / "platform-tool-imap",
    ROOT / "services" / "platform-tool-browser",
    ROOT / "services" / "platform-tool-onec",
    ROOT / "services" / "platform-tool-onec-com",
]


def main() -> int:
    ensure_64bit_python()
    ensure_dependencies()
    clean_build_dirs()
    build_roseltorg_tool()
    build_desktop_host()
    build_desktop_launcher()
    build_desktop()
    assemble_distribution()
    print()
    print(f"Готово: {FINAL_DIST}")
    print(f"Запуск: {FINAL_DIST / 'ConstructorDesktop.exe'}")
    return 0


def ensure_dependencies() -> None:
    cmd = [sys.executable, "-m", "pip", "install"]
    cmd.extend(["-r", str(DESKTOP_DIR / "requirements.txt")])
    cmd.extend(["-r", str(TOOLS_DIR / "requirements.txt")])
    for path in PLATFORM_PATHS:
        if (path / "pyproject.toml").is_file():
            cmd.append(str(path))
    cmd.append("pyinstaller")
    run(cmd, cwd=ROOT)
    run([sys.executable, "-m", "playwright", "install", "chromium"], cwd=ROOT)


def stop_running_desktop() -> list[str]:
    if sys.platform != "win32":
        return []

    stopped: list[str] = []
    for image in ("ConstructorDesktop.exe", "DesktopHost.exe", "DesktopLauncher.exe"):
        probe = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        if image.lower() not in probe.stdout.lower():
            continue
        result = subprocess.run(
            ["taskkill", "/IM", image, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            stopped.append(image)
    if stopped:
        print("Остановлены процессы:", ", ".join(stopped))
        time.sleep(1)
    return stopped


def clean_build_dirs() -> None:
    for path in (BUILD_DIR, FINAL_DIST):
        if not path.exists():
            continue
        try:
            shutil.rmtree(path)
        except PermissionError:
            stop_running_desktop()
            try:
                shutil.rmtree(path)
            except PermissionError as exc:
                if path == FINAL_DIST:
                    raise SystemExit(
                        f"Не удалось очистить {path}: файлы всё ещё заняты.\n"
                        "Закройте ConstructorDesktop вручную или перезагрузите ПК, затем повторите сборку."
                    ) from exc
                raise
    BUILD_DIR.mkdir(parents=True, exist_ok=True)


def _platform_pyinstaller_args(*, name: str, entry: Path, work_subdir: str) -> list[str]:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        name,
        "--distpath",
        str(PYI_DIST / "services"),
        "--workpath",
        str(PYI_WORK / work_subdir),
        "--specpath",
        str(BUILD_DIR / "spec"),
    ]
    for path in PLATFORM_PATHS:
        if path.exists():
            args.extend(["--paths", str(path)])
    args.extend(
        [
            "--hidden-import",
            "platform_desktop_host.main",
            "--hidden-import",
            "platform_desktop_launcher.main",
            "--hidden-import",
            "platform_tool_browser.main",
            "--hidden-import",
            "platform_tool_com.main",
            "--hidden-import",
            "platform_tool_filesystem.main",
            "--hidden-import",
            "platform_tool_imap.main",
            "--hidden-import",
            "platform_tool_shell.native_main",
            "--collect-submodules",
            "uvicorn",
            "--collect-submodules",
            "fastapi",
            str(entry),
        ]
    )
    return args


def build_desktop_host() -> None:
    run(_platform_pyinstaller_args(name="DesktopHost", entry=DESKTOP_DIR / "host_main.py", work_subdir="host"), cwd=ROOT)


def build_desktop_launcher() -> None:
    run(
        _platform_pyinstaller_args(
            name="DesktopLauncher",
            entry=DESKTOP_DIR / "launcher_main.py",
            work_subdir="launcher",
        ),
        cwd=ROOT,
    )


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

    for exe_name in ("DesktopHost.exe", "DesktopLauncher.exe"):
        src = PYI_DIST / "services" / exe_name
        if not src.exists():
            raise RuntimeError(f"PyInstaller не создал {src}")
        shutil.copy2(src, FINAL_DIST / exe_name)

    env_source = DESKTOP_DIR / ".env"
    env_target = FINAL_DIST / ".env"
    if env_target.exists():
        shutil.copy2(env_source, env_target)
    elif not env_target.exists():
        env_target.write_text(
            "BACKEND_URL=http://127.0.0.1:7812\nAUTH_URL=http://127.0.0.1:7812\n",
            encoding="utf-8",
        )

    reg_src = ROOT / "ACT_REGISTRY.md"
    if reg_src.is_file():
        reg_dir = FINAL_DIST / "regulations"
        reg_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reg_src, reg_dir / "ACT_REGISTRY.md")

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
    for script_name in ("restart_app.bat", "start_app.bat"):
        script_src = DESKTOP_DIR / script_name
        if script_src.is_file():
            shutil.copy2(script_src, FINAL_DIST / script_name)


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

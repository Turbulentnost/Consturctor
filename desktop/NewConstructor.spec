# -*- mode: python ; coding: utf-8 -*-
"""Onedir: ConstructorDesktop.exe (GUI) + ConstructorComWorker.exe (COM/stdin)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
root = Path(SPECPATH)


def _datas_dir(src: Path, dest: str) -> list[tuple[str, str]]:
    if src.is_dir() and any(src.iterdir()):
        return [(str(src), dest)]
    return []


def _pywin32_binaries() -> list[tuple[str, str]]:
    binaries: list[tuple[str, str]] = []
    try:
        import win32api
    except ImportError:
        return binaries
    site = Path(win32api.__file__).resolve().parent
    candidates = (site, site / "pywin32_system32", site.parent / "pywin32_system32")
    seen: set[str] = set()
    for folder in candidates:
        if not folder.is_dir():
            continue
        dest = "pywin32_system32" if folder.name == "pywin32_system32" else "."
        for dll in folder.glob("*.dll"):
            key = f"{dest}:{dll.name.casefold()}"
            if key in seen:
                continue
            seen.add(key)
            binaries.append((str(dll), dest))
    return binaries


datas = []
datas += _datas_dir(root / "assets", "assets")
datas += _datas_dir(root / "app" / "ui" / "temp", "app/ui/temp")
if (root / ".env.example").is_file():
    datas.append((str(root / ".env.example"), "."))
try:
    datas += collect_data_files("certifi")
except Exception:
    pass
try:
    datas += collect_data_files("playwright")
except Exception:
    pass

binaries = _pywin32_binaries()
hiddenimports = [
    "httpx",
    "dotenv",
    "certifi",
    "winotify",
    "pydantic",
    "pydantic_core",
    "openpyxl",
    "openpyxl.cell._writer",
    "win32com",
    "win32com.client",
    "win32com.client.gencache",
    "pythoncom",
    "pywintypes",
    "win32timezone",
    "win32api",
    "playwright",
    "playwright.sync_api",
    "greenlet",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtWebSockets",
]
hiddenimports += collect_submodules("app")
try:
    hiddenimports += collect_submodules("playwright")
except Exception:
    pass

excludes = [
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "pandas",
    "matplotlib",
    "scipy",
    "sklearn",
    "cv2",
    "IPython",
    "notebook",
    "jupyter",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebView",
    "PySide6.QtXml",
    "PySide6.scripts",
]

icon = root / "app" / "ui" / "temp" / "logo.png"
icon_path = str(icon) if icon.is_file() else None

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "packaging" / "pyi_rth_constructor.py")],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

gui_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ConstructorDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

com_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ConstructorComWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    gui_exe,
    com_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ConstructorDesktop",
)

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)

datas = [
    (str(root / "app" / "ui" / "temp"), "app/ui/temp"),
]
if (root / "assets").exists():
    datas.append((str(root / "assets"), "assets"))
for name in ("odata_organization_keys.json", "odata_department_keys.json", "sample_regulation.md"):
    src = root / "data" / name
    if src.exists():
        datas.append((str(src), "data"))
# Release: never bundle .env (secrets). Portable package ships .env.example beside exe.
if (root / ".env.example").exists():
    datas.append((str(root / ".env.example"), "."))

binaries = []
hiddenimports = [
    "httpx",
    "dotenv",
    "certifi",
    "openpyxl",
    "docx",
    "pypdf",
    "cursor_sdk",
    "win32com",
    "pythoncom",
    "PySide6.QtWebSockets",
]
pathex = [str(root)]

for pkg in ("PySide6", "cursor_sdk"):
    collected = collect_all(pkg)
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]

try:
    import cursor_sdk as _cursor_sdk

    _bridge_dir = Path(_cursor_sdk.__file__).resolve().parent / "_vendor" / "bridge"
    _node = _bridge_dir / "bin" / "node.exe"
    if _node.is_file():
        binaries.append((str(_node), "cursor_sdk/_vendor/bridge/bin"))
except Exception:
    pass

a = Analysis(
    [str(root / "main.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="RegAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

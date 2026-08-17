from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

from platform_contracts.tools import ToolInvokeRequest

DESKTOP_HOST_PORT = 7830

HOST_TOOL_PREFIXES = ("com.", "fs.", "shell.", "desktop.")


def is_host_tool(tool_name: str, *, shell_runtime: str = "") -> bool:
    name = (tool_name or "").strip()
    if name.startswith(("com.", "fs.", "desktop.")):
        return True
    if name.startswith("shell."):
        runtime = (shell_runtime or "").strip().lower()
        if runtime == "sandbox":
            return False
        return runtime == "native" or os.environ.get("SHELL_DEFAULT_RUNTIME", "").lower() == "native" or bool(runtime == "")
    return False


def _system_info(_: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "system info",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "hostname": platform.node(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "cwd": str(Path.cwd()),
        "desktop_host_port": DESKTOP_HOST_PORT,
        "source": "desktop-host",
    }


def _capabilities(_: ToolInvokeRequest) -> dict[str, Any]:
    packages = {
        "microsoft_com": ["onec", "outlook", "excel", "word", "powerpoint"],
        "filesystem": ["fs.list", "fs.read", "fs.write", "fs.stat", "fs.move", "fs.copy"],
        "shell_native": ["shell.run"],
        "desktop": [
            "desktop.system_info",
            "desktop.capabilities",
            "desktop.clipboard_read",
            "desktop.clipboard_write",
            "desktop.open_path",
        ],
    }
    return {
        "summary": "desktop host capability catalog",
        "packages": packages,
        "single_port": DESKTOP_HOST_PORT,
        "source": "desktop-host",
    }


def _clipboard_read(req: ToolInvokeRequest) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("clipboard requires Windows host")
    import win32clipboard  # type: ignore[import-untyped]

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        else:
            text = ""
    finally:
        win32clipboard.CloseClipboard()
    max_len = int(req.payload.get("max_chars", 8000))
    text = str(text or "")
    truncated = len(text) > max_len
    if truncated:
        text = text[:max_len]
    return {
        "summary": f"clipboard {len(text)} chars",
        "text": text,
        "truncated": truncated,
        "source": "desktop-host",
    }


def _clipboard_write(req: ToolInvokeRequest) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("clipboard requires Windows host")
    text = str(req.payload.get("text", ""))
    import win32clipboard  # type: ignore[import-untyped]

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    return {
        "summary": f"wrote {len(text)} chars to clipboard",
        "chars": len(text),
        "source": "desktop-host",
    }


def _open_path(req: ToolInvokeRequest) -> dict[str, Any]:
    path_str = str(req.payload.get("path", "")).strip()
    if not path_str:
        raise ValueError("path required")
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"path not found: {path}")
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        import subprocess

        subprocess.Popen(["open", str(path)])
    else:
        import subprocess

        subprocess.Popen(["xdg-open", str(path)])
    return {
        "summary": f"opened {path}",
        "path": str(path),
        "source": "desktop-host",
    }


def _stub_clipboard_read(_: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub clipboard",
        "text": "stub clipboard content",
        "truncated": False,
        "source": "stub",
    }


def _stub_clipboard_write(req: ToolInvokeRequest) -> dict[str, Any]:
    text = str(req.payload.get("text", ""))
    return {"summary": "stub clipboard write", "chars": len(text), "source": "stub"}


def _stub_open_path(req: ToolInvokeRequest) -> dict[str, Any]:
    path = str(req.payload.get("path", "")).strip() or "C:\\stub"
    return {"summary": "stub open", "path": path, "source": "stub"}


DESKTOP_HANDLERS = {
    "desktop.system_info": _system_info,
    "desktop.capabilities": _capabilities,
    "desktop.clipboard_read": _clipboard_read,
    "desktop.clipboard_write": _clipboard_write,
    "desktop.open_path": _open_path,
}

DESKTOP_STUB_HANDLERS = {
    "desktop.system_info": _system_info,
    "desktop.capabilities": _capabilities,
    "desktop.clipboard_read": _stub_clipboard_read,
    "desktop.clipboard_write": _stub_clipboard_write,
    "desktop.open_path": _stub_open_path,
}

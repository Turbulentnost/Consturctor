"""Windows helpers to spawn child processes without flashing console windows."""

from __future__ import annotations

import os
import subprocess
import sys

_PATCHED = False


def hidden_subprocess_kwargs() -> dict:
    """Return kwargs for subprocess.run/Popen that hide the console on Windows."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def merge_hidden_subprocess_kwargs(kwargs: dict) -> dict:
    """Merge hidden-window flags into an existing subprocess kwargs dict."""
    hidden = hidden_subprocess_kwargs()
    if not hidden:
        return kwargs
    merged = dict(kwargs)
    merged.setdefault("startupinfo", hidden["startupinfo"])
    flags = int(merged.get("creationflags") or 0)
    merged["creationflags"] = flags | int(hidden["creationflags"])
    return merged


def apply_global_subprocess_patch() -> None:
    """Monkey-patch stdlib subprocess so all child processes hide their console."""
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return
    if allow_console_subprocess():
        return

    original_popen = subprocess.Popen
    original_run = subprocess.run

    class _HiddenPopen(original_popen):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **merge_hidden_subprocess_kwargs(kwargs))

    def hidden_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return original_run(*args, **merge_hidden_subprocess_kwargs(kwargs))

    subprocess.Popen = _HiddenPopen  # type: ignore[assignment]
    subprocess.run = hidden_run  # type: ignore[assignment]
    _PATCHED = True


def allow_console_subprocess() -> bool:
    """Return True when REGAGENT_ALLOW_CONSOLE_SUBPROCESS is set (debug only)."""
    return os.environ.get("REGAGENT_ALLOW_CONSOLE_SUBPROCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

"""Windows fixes for cursor-sdk local bridge subprocesses.

1. ``selectors.DefaultSelector`` cannot watch pipe fds on Windows вЂ” replace
   ``_read_discovery`` with a stderr ``readline()`` loop.
2. Launch the bridge via bundled ``node.exe`` directly (not ``.cmd``) so
   Windows does not spawn a visible ``cmd.exe`` wrapper.
3. Pre-warm the default bridge at app startup so card open does not pay launch
   latency on the UI thread.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import subprocess

from app.subprocess_win import apply_global_subprocess_patch, merge_hidden_subprocess_kwargs

logger = logging.getLogger(__name__)

_PATCHED = False

def _read_discovery_win(
    process: subprocess.Popen[str], timeout: float
) -> Mapping[str, Any]:
    from cursor_sdk._bridge import parse_discovery_line
    from cursor_sdk.errors import CursorSDKError

    if process.stderr is None:
        raise CursorSDKError("Bridge process stderr is unavailable")

    deadline = time.monotonic() + timeout
    stderr_lines: list[str] = []

    while time.monotonic() < deadline:
        line = process.stderr.readline()
        if line:
            stderr_lines.append(line)
            discovery = parse_discovery_line(line)
            if discovery is not None:
                return discovery
        code = process.poll()
        if code is not None:
            tail = process.stderr.read() or ""
            if tail:
                stderr_lines.append(tail)
                discovery = parse_discovery_line(tail)
                if discovery is not None:
                    return discovery
            raise CursorSDKError(
                f"Bridge exited before discovery with status {code}: "
                + "".join(stderr_lines)
            )
        if not line:
            time.sleep(0.02)

    raise CursorSDKError("Timed out waiting for bridge discovery")


def direct_bridge_argv(launcher: str | os.PathLike[str]) -> list[str]:
    """Expand ``cursor-sdk-bridge.cmd`` to ``node.exe`` + bridge JS (no cmd.exe)."""
    path = Path(os.fspath(launcher))
    if path.suffix.lower() != ".cmd":
        return [str(path)]
    node = path.parent / "node.exe"
    js = path.parent.parent / "dist" / "bin" / "cursor-sdk-bridge.js"
    if node.is_file() and js.is_file():
        return [str(node), str(js)]
    return [str(path)]


def _normalize_bridge_command(
    command: str | os.PathLike[str] | Sequence[str | os.PathLike[str]] | None,
) -> list[str] | None:
    if command is None:
        from cursor_sdk._vendor import resolve_bridge_path

        return direct_bridge_argv(resolve_bridge_path())
    if isinstance(command, (str, os.PathLike)):
        return direct_bridge_argv(os.fspath(command))
    parts = [os.fspath(arg) for arg in command]
    if parts and Path(parts[0]).suffix.lower() == ".cmd":
        return direct_bridge_argv(parts[0]) + parts[1:]
    return parts


def _patch_bridge_popen(module: Any) -> None:
    original_popen = module.subprocess.Popen

    class _HiddenBridgePopen(original_popen):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **merge_hidden_subprocess_kwargs(kwargs))

    module.subprocess.Popen = _HiddenBridgePopen  # type: ignore[assignment]


def _patch_bridge_launch(module: Any) -> None:
    original_launch = module.Bridge.launch.__func__

    def launch(
        cls: type,
        command: str | os.PathLike[str] | Sequence[str | os.PathLike[str]] | None = None,
        **kwargs: Any,
    ) -> Any:
        normalized = _normalize_bridge_command(command)
        return original_launch(cls, normalized, **kwargs)

    module.Bridge.launch = classmethod(launch)  # type: ignore[assignment]


def prewarm_bridge(*, timeout: float = 30) -> bool:
    """Start the default cursor-sdk bridge once at app startup (hidden)."""
    if sys.platform != "win32":
        return True
    try:
        from cursor_sdk._client import _default_client

        _default_client()
        return True
    except Exception as exc:
        logger.warning("Bridge prewarm failed: %s", exc, exc_info=True)
        return False


def apply() -> None:
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return

    apply_global_subprocess_patch()

    import cursor_sdk._bridge as bridge

    bridge._read_discovery = _read_discovery_win  # type: ignore[assignment]
    _patch_bridge_popen(bridge)
    _patch_bridge_launch(bridge)
    _PATCHED = True

"""Windows fix for cursor-sdk bridge discovery.

On Windows, ``selectors.DefaultSelector`` only accepts sockets, not pipe fds.
The stock ``cursor_sdk._bridge._read_discovery`` registers stderr on a selector
and raises ``OSError: [WinError 10038]``.

The replacement uses line reads from stderr. Use ``readline()``, not ``read(n)``:
with the default block buffer, ``read(n)`` can block until the buffer fills.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from typing import Any

import subprocess

from cursor_sdk.errors import CursorSDKError

_PATCHED = False


def _read_discovery_win(
    process: subprocess.Popen[str], timeout: float
) -> Mapping[str, Any]:
    from cursor_sdk._bridge import parse_discovery_line

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


def apply() -> None:
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return
    import cursor_sdk._bridge as bridge

    bridge._read_discovery = _read_discovery_win  # type: ignore[assignment]
    _PATCHED = True

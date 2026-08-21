from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cursor_sdk_win_patch import direct_bridge_argv
from app.subprocess_win import (
    apply_global_subprocess_patch,
    hidden_subprocess_kwargs,
    merge_hidden_subprocess_kwargs,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only subprocess flags")
def test_hidden_subprocess_kwargs_include_create_no_window() -> None:
    kwargs = hidden_subprocess_kwargs()
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only subprocess patch")
def test_global_subprocess_patch_wraps_popen_and_run() -> None:
    apply_global_subprocess_patch()
    assert isinstance(subprocess.Popen, type)
    assert subprocess.Popen.__name__.startswith("_Hidden")
    assert subprocess.run.__name__ == "hidden_run"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only subprocess patch")
def test_global_subprocess_patch_allows_asyncio_import() -> None:
    apply_global_subprocess_patch()
    import asyncio.windows_utils  # noqa: F401


def test_direct_bridge_argv_expands_cmd_to_node_and_js(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dist_js = tmp_path / "dist" / "bin" / "cursor-sdk-bridge.js"
    dist_js.parent.mkdir(parents=True)
    dist_js.write_text("// stub", encoding="utf-8")
    cmd = bin_dir / "cursor-sdk-bridge.cmd"
    node = bin_dir / "node.exe"
    cmd.write_text("@echo off\n", encoding="utf-8")
    node.write_bytes(b"")

    argv = direct_bridge_argv(cmd)
    assert argv == [str(node), str(dist_js)]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only bridge patch")
def test_bridge_launch_uses_node_not_cmd() -> None:
    from app.config import ensure_data_dirs

    ensure_data_dirs()
    import cursor_sdk._bridge as bridge

    calls: list[list[str]] = []
    original_popen = bridge.subprocess.Popen

    def capture_popen(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append([str(part) for part in args])
        proc = original_popen(args, **kwargs)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise RuntimeError("stop-after-spawn")

    with patch.object(bridge.subprocess, "Popen", side_effect=capture_popen):
        with pytest.raises(RuntimeError, match="stop-after-spawn"):
            bridge.Bridge.launch(timeout=5)

    assert calls
    argv = calls[0]
    assert argv[0].lower().endswith("node.exe")
    assert argv[1].replace("\\", "/").endswith("dist/bin/cursor-sdk-bridge.js")

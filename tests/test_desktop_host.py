from __future__ import annotations

import importlib


def test_desktop_host_merges_handlers() -> None:
    module = importlib.import_module("platform_desktop_host.main")
    names = set(module.REAL_HANDLERS)
    assert "com.list_apps" in names
    assert "fs.list" in names
    assert "shell.run" in names
    assert "desktop.capabilities" in names
    assert "com.outlook.calendar_list" in names


def test_desktop_host_tool_count() -> None:
    module = importlib.import_module("platform_desktop_host.main")
    assert len(module.REAL_HANDLERS) >= 20

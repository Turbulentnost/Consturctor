from __future__ import annotations

import pytest

from app.tools.host import ToolHostError, invoke_tool


def test_odata_post_blocked_on_desktop() -> None:
    with pytest.raises(ToolHostError, match="отключена"):
        invoke_tool("onec.odata_post", {"entity": "Document_Foo"})


def test_write_tools_not_in_sdk_catalog() -> None:
    from app.tools.server_tools import SERVER_TOOL_NAMES

    assert "onec.odata_post" not in SERVER_TOOL_NAMES
    assert "onec.odata_patch" not in SERVER_TOOL_NAMES
    assert "onec.attach_file" not in SERVER_TOOL_NAMES

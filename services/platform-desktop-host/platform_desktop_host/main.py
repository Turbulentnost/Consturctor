from __future__ import annotations

from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app
from platform_tool_browser.main import REAL_HANDLERS as BROWSER_REAL, STUB_HANDLERS as BROWSER_STUB
from platform_tool_com.main import REAL_HANDLERS as COM_REAL, STUB_HANDLERS as COM_STUB
from platform_tool_filesystem.main import REAL_HANDLERS as FS_REAL, STUB_HANDLERS as FS_STUB
from platform_tool_imap.main import REAL_HANDLERS as IMAP_REAL, STUB_HANDLERS as IMAP_STUB, _imap_ready
from platform_tool_shell.native_main import HANDLERS as SHELL_HANDLERS, STUB_HANDLERS as SHELL_STUB

from platform_desktop_host.automation import DESKTOP_HANDLERS, DESKTOP_STUB_HANDLERS, DESKTOP_HOST_PORT


class DesktopHostSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-desktop-host"
    api_port: int = DESKTOP_HOST_PORT


settings = DesktopHostSettings()


def build_handlers() -> tuple[dict[str, Any], dict[str, Any]]:
    real: dict[str, Any] = {}
    stub: dict[str, Any] = {}
    for mapping in (
        COM_REAL,
        FS_REAL,
        SHELL_HANDLERS,
        DESKTOP_HANDLERS,
        IMAP_REAL,
        BROWSER_REAL,
    ):
        real.update(mapping)
    for mapping in (
        COM_STUB,
        FS_STUB,
        SHELL_STUB,
        DESKTOP_STUB_HANDLERS,
        IMAP_STUB,
        BROWSER_STUB,
    ):
        stub.update(mapping)
    # Real mailbox when IMAP_* configured — even if USE_STUBS=true for demos.
    if _imap_ready():
        stub.update(IMAP_REAL)
    return real, stub


REAL_HANDLERS, STUB_HANDLERS = build_handlers()

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


@app.get("/api/v1/capabilities")
def capabilities() -> dict[str, Any]:
    from platform_contracts.tools import ToolInvokeRequest

    return DESKTOP_HANDLERS["desktop.capabilities"](ToolInvokeRequest(payload={}))


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()

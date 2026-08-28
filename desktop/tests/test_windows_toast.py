import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.notifications.service import _launch_command, _toast_icon, _toast_text


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path)


def _toast_xml(launch: str, icon: str = "") -> str:
    launch_attr = f'activationType="protocol" launch="{launch}"' if launch else ""
    return (
        f'<toast {launch_attr} duration="long">'
        "<visual><binding template=\"ToastImageAndText02\">"
        f'<image id="1" src="{icon}" />'
        "<text id=\"1\"><![CDATA[title]]></text>"
        "<text id=\"2\"><![CDATA[msg]]></text>"
        "</binding></visual>"
        f'<actions><action activationType="protocol" content="Open" arguments="{launch}" />'
        "</actions></toast>"
    )


def test_launch_is_file_uri_without_quotes() -> None:
    launch = _launch_command("ac67b8d9-3d96-41c7-8a81-c5c42ffa1754", "run-1")
    assert launch.startswith("file:")
    assert '"' not in launch
    ET.fromstring(_toast_xml(launch))


def test_quoted_command_line_breaks_toast_xml() -> None:
    broken = '"C:\\Python\\python.exe" "C:\\app\\main.py" --open-workflow=wf-1'
    try:
        ET.fromstring(_toast_xml(broken))
    except ET.ParseError:
        return
    raise AssertionError("quoted argv must not be used as toast launch")


def test_launch_cmd_opens_workflow() -> None:
    launch = _launch_command("wf-live-1", "run-9")
    path = _path_from_file_uri(launch)
    assert path.suffix == ".cmd"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "wf-live-1" in text
    assert "run-9" in text
    assert "--ipc" in text
    assert "open-workflow:wf-live-1|run-9" in text
    assert "QApplication" not in text
    assert "subprocess" not in text
    assert "--open-workflow=" not in text


def test_empty_workflow_has_no_launch() -> None:
    assert _launch_command("") == ""
    ET.fromstring(_toast_xml(""))


def test_toast_icon_is_xml_safe() -> None:
    icon = _toast_icon()
    if icon:
        assert '"' not in icon
        ET.fromstring(_toast_xml("file:///C:/open.cmd", icon))


def test_toast_text_strips_powershell_and_cdata_breakers() -> None:
    assert "$" not in _toast_text('Агент "X" ждёт $HOME]]>', 80)
    assert '"' not in _toast_text('Агент "X" ждёт', 80)
    assert "]]>" not in _toast_text("a ]]> b", 80)

"""Запуск локального Cursor SDK.

Сейчас runner не подключён: прогон фиксируется, но на устройство не уходит.
"""

from __future__ import annotations

from app.sdk.protocol import RunCommand


class SdkNotConnected(RuntimeError):
    pass


def sdk_status() -> dict[str, object]:
    return {
        "connected": False,
        "runtime": "cursor-sdk",
        "message": (
            "Локальный runner @cursor/sdk ещё не подключён. "
            "Каталоги агентов и инструментов пустые — реализации не переносились."
        ),
    }


def start_run(command: RunCommand) -> None:
    if not command.prompt.strip():
        raise ValueError("prompt is empty")
    raise SdkNotConnected(str(sdk_status()["message"]))

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from app.ui.widgets.app_dialog import confirm_dialog


def confirm_tool(parent: QWidget | None, tool_name: str, arguments: dict) -> bool:
    preview = "\n".join(f"{k}: {v}" for k, v in list(arguments.items())[:8])
    message = f"Разрешить выполнение «{tool_name}»?"
    if preview:
        message = f"{message}\n\n{preview}"
    return confirm_dialog(
        parent,
        "Подтверждение действия",
        message,
        primary="Разрешить",
        secondary="Отмена",
    )

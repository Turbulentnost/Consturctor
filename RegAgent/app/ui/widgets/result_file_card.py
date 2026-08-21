"""Карточка документа в ленте: открыть и сохранить к себе."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.ui.styles import primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class ResultFileCard(QFrame):
    def __init__(self, path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = "file"
        self._path = Path(path)
        self.setObjectName("ResultFileCard")
        self.setStyleSheet(
            """
            QFrame#ResultFileCard {
                background: #F4F7F6;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 12px;
            }
            """
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        caption = QLabel("Файл результата")
        caption.setFont(app_font(11))
        caption.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        name = QLabel(self._path.name)
        name.setFont(app_font(13, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        save = QPushButton("Сохранить у себя")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setFont(app_font(12, QFont.Weight.DemiBold))
        save.setFixedHeight(32)
        save.setStyleSheet(primary_button_qss(radius=10, compact=True))
        save.clicked.connect(self._save)
        open_btn = QPushButton("Открыть")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        open_btn.setFixedHeight(32)
        open_btn.setStyleSheet(secondary_button_qss(radius=10))
        open_btn.clicked.connect(self._open)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(save, 0)
        buttons.addWidget(open_btn, 0)
        buttons.addStretch(1)
        root.addWidget(caption)
        root.addWidget(name)
        root.addLayout(buttons)

    def _open(self) -> None:
        if not self._path.is_file():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path)))

    def _save(self) -> None:
        if not self._path.is_file():
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить файл",
            str(Path.home() / "Desktop" / self._path.name),
            f"Файлы (*{self._path.suffix});;Все файлы (*.*)",
        )
        if dest:
            shutil.copy2(self._path, dest)


def paths_from_result(result: object) -> list[Path]:
    found: list[Path] = []
    if isinstance(result, str):
        path = Path(result)
        if path.is_file():
            found.append(path)
        return found
    if not isinstance(result, dict):
        return found
    for key in ("path", "file", "output", "saved_path"):
        raw = result.get(key)
        if isinstance(raw, str):
            path = Path(raw)
            if path.is_file():
                found.append(path)
    files = result.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, str):
                path = Path(item)
            elif isinstance(item, dict):
                raw = item.get("path") or item.get("file") or ""
                path = Path(str(raw))
            else:
                continue
            if path.is_file():
                found.append(path)
    return found

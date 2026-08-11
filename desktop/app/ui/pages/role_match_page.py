from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.api_client import RoleMatch, RoleMatchResult
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, SIDEBAR_MIDDLE, app_font, scroll_bar_qss


class RoleMatchPage(QWidget):
    back_requested = Signal()
    finish_requested = Signal()
    decision_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content = QVBoxLayout()

        self._title = QLabel("Связь с должностью")
        self._title.setFont(app_font(30, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._subtitle = QLabel("Проверьте, какие фрагменты регламента относятся к выбранной должности")
        self._subtitle.setFont(app_font(14))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(14)
        scroll_content.setLayout(self._content)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(scroll_content)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        back = QPushButton("Назад")
        back.setFixedHeight(42)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFont(app_font(13, QFont.Weight.DemiBold))
        back.setStyleSheet(_secondary_button_qss())
        back.clicked.connect(self.back_requested.emit)

        finish = QPushButton("Завершить")
        finish.setFixedHeight(42)
        finish.setCursor(Qt.CursorShape.PointingHandCursor)
        finish.setFont(app_font(13, QFont.Weight.DemiBold))
        finish.setStyleSheet(_primary_button_qss())
        finish.clicked.connect(self.finish_requested.emit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(back)
        actions.addWidget(finish)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._title)
        root.addWidget(self._subtitle)
        root.addSpacing(12)
        root.addWidget(scroll, 1)
        root.addLayout(actions)

    def set_result(self, result: RoleMatchResult) -> None:
        _clear_layout(self._content)
        self._subtitle.setText(
            f"Должность: {result.canonical_title}"
            + (f" · {result.department}" if result.department else "")
        )
        groups = [
            ("accepted", "Включено автоматически"),
            ("probable", "Вероятные фрагменты"),
            ("pending", "Требует подтверждения"),
            ("rejected", "Отклонено"),
        ]
        for status, title in groups:
            items = [match for match in result.matches if match.status == status]
            if not items:
                continue
            self._content.addWidget(_group_title(title, len(items)))
            for match in items:
                self._content.addWidget(self._match_card(match))
        if not result.matches:
            empty = QLabel("Связанные с должностью фрагменты не найдены.")
            empty.setFont(app_font(14))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._content.addWidget(empty)
        self._content.addStretch(1)

    def _match_card(self, match: RoleMatch) -> QWidget:
        card = QFrame()
        card.setObjectName("RoleMatchCard")
        card.setStyleSheet(
            """
            QFrame#RoleMatchCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        meta = QLabel(
            f"Стр. {match.fragment.page} · {match.relation} · "
            f"{match.confidence * 100:.0f}% · {', '.join(match.match_types)}"
        )
        meta.setFont(app_font(11, QFont.Weight.DemiBold))
        meta.setStyleSheet(f"color: {SIDEBAR_MIDDLE.name()}; background: transparent;")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        if match.fragment.section_path:
            section = QLabel(" / ".join(match.fragment.section_path))
            section.setFont(app_font(12, QFont.Weight.DemiBold))
            section.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            section.setWordWrap(True)
            layout.addWidget(section)

        text = QLabel(_fragment_text(match))
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setFont(app_font(13))
        text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(text)

        explanation = QLabel(match.explanation)
        explanation.setWordWrap(True)
        explanation.setFont(app_font(12))
        explanation.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(explanation)

        for signal in match.signals[:4]:
            sig = QLabel(
                f"{signal.match_type}: {signal.confidence * 100:.0f}%"
                + (f" · {signal.explanation}" if signal.explanation else "")
            )
            sig.setWordWrap(True)
            sig.setFont(app_font(11))
            sig.setStyleSheet("color: #7B8A85; background: transparent;")
            layout.addWidget(sig)

        if match.status in {"pending", "probable"} or match.requires_confirmation:
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            reject = QPushButton("Отклонить")
            reject.setFixedHeight(34)
            reject.setCursor(Qt.CursorShape.PointingHandCursor)
            reject.setFont(app_font(12, QFont.Weight.DemiBold))
            reject.setStyleSheet(_secondary_button_qss())
            reject.clicked.connect(lambda _=False, mid=match.match_id: self.decision_requested.emit(mid, "rejected"))
            accept = QPushButton("Подтвердить")
            accept.setFixedHeight(34)
            accept.setCursor(Qt.CursorShape.PointingHandCursor)
            accept.setFont(app_font(12, QFont.Weight.DemiBold))
            accept.setStyleSheet(_primary_button_qss())
            accept.clicked.connect(lambda _=False, mid=match.match_id: self.decision_requested.emit(mid, "accepted"))
            buttons.addWidget(reject)
            buttons.addWidget(accept)
            layout.addLayout(buttons)

        return card


def _fragment_text(match: RoleMatch) -> str:
    fragment = match.fragment
    if fragment.cells:
        return "\n".join(f"{key}: {value}" for key, value in fragment.cells.items() if value)
    return fragment.text or "Пустой фрагмент"


def _group_title(title: str, count: int) -> QLabel:
    label = QLabel(f"{title} · {count}")
    label.setFont(app_font(15, QFont.Weight.DemiBold))
    label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
    return label


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _primary_button_qss() -> str:
    return """
    QPushButton {
        background: #06483D;
        color: #F7FBFA;
        border: none;
        border-radius: 17px;
        padding: 0 18px;
    }
    QPushButton:hover { background: #08745F; }
    """


def _secondary_button_qss() -> str:
    return """
    QPushButton {
        background: #EEF7F3;
        color: #06483D;
        border: none;
        border-radius: 17px;
        padding: 0 18px;
    }
    QPushButton:hover { background: #DFF5EC; }
    """

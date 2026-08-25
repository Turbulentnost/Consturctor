from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.orchestrator.engine import counts, decide, start_process
from app.orchestrator.models import (
    COMPLETED,
    DEFINITIONS,
    READY,
    WAITING_HUMAN,
    ProcessDefinition,
    ProcessInstance,
)
from app.orchestrator.store import latest_by_definition, load_instances
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_USER_MENU_RESERVE = 360

_CARD = """
QFrame#OrchCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
"""
_BADGE = """
QLabel#OrchBadge {
    background: #EAF7F3;
    color: #08745F;
    border: 1px solid rgba(8,116,95,0.28);
    border-radius: 10px;
    padding: 4px 10px;
}
"""
_STATUS = """
QLabel#OrchStatus {
    background: #EEF7F3;
    color: #06483D;
    border-radius: 8px;
    padding: 3px 8px;
}
"""
_START_BTN = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    padding: 0 18px;
}
QPushButton:hover { background: #0A8A70; }
QPushButton:pressed { background: #06483D; }
"""
_SECONDARY_BTN = """
QPushButton {
    background: #FFFFFF;
    color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px;
    padding: 0 14px;
}
QPushButton:hover { background: #F4F7F6; }
"""


class OrchestratorPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._user_id = "local"
        title = QLabel("Оркестратор")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        badge = QLabel("Пилот · 2 агента")
        badge.setObjectName("OrchBadge")
        badge.setFont(app_font(12, QFont.Weight.Medium))
        badge.setStyleSheet(_BADGE)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        header.setSpacing(12)
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)

        today = QLabel("Сегодня")
        today.setFont(app_font(16, QFont.Weight.DemiBold))
        today.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._chip_waiting = self._chip("Ждут меня", "0")
        self._chip_active = self._chip("Активные", "0")
        self._chip_errors = self._chip("Ошибки", "0")
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(12)
        chips.addWidget(self._chip_waiting, 1)
        chips.addWidget(self._chip_active, 1)
        chips.addWidget(self._chip_errors, 1)

        self._cards = QVBoxLayout()
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(12)

        note = QLabel("Старт создаёт экземпляр локально и останавливается на решении человека. Агенты ещё не подключены.")
        note.setWordWrap(True)
        note.setFont(app_font(13))
        note.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(16)
        inner_lay.addWidget(today)
        inner_lay.addLayout(chips)
        inner_lay.addLayout(self._cards)
        inner_lay.addWidget(note)
        inner_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(scroll, 1)
        self.refresh()

    def set_user(self, user_id: str) -> None:
        self._user_id = user_id or "local"
        self.refresh()

    def refresh(self) -> None:
        instances = load_instances(self._user_id)
        waiting, active, errors = counts(instances)
        self._set_chip(self._chip_waiting, str(waiting))
        self._set_chip(self._chip_active, str(active))
        self._set_chip(self._chip_errors, str(errors))
        latest = latest_by_definition(instances)
        while self._cards.count():
            taken = self._cards.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.deleteLater()
        for definition in DEFINITIONS:
            self._cards.addWidget(self._process_card(definition, latest.get(definition.id)))

    def _chip(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("OrchCard")
        card.setStyleSheet(_CARD)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        name = QLabel(label)
        name.setObjectName("OrchChipName")
        name.setFont(app_font(12, QFont.Weight.Medium))
        name.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        number = QLabel(value)
        number.setObjectName("OrchChipValue")
        number.setFont(app_font(28, QFont.Weight.DemiBold))
        number.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(4)
        lay.addWidget(name)
        lay.addWidget(number)
        return card

    def _set_chip(self, card: QFrame, value: str) -> None:
        number = card.findChild(QLabel, "OrchChipValue")
        if number is not None:
            number.setText(value)

    def _process_card(self, definition: ProcessDefinition, instance: ProcessInstance | None) -> QFrame:
        status = instance.status if instance is not None else READY
        status_label = instance.status_label if instance is not None else "Готов к запуску"
        waiting = instance.waiting if instance is not None else 0
        card = QFrame()
        card.setObjectName("OrchCard")
        card.setStyleSheet(_CARD)

        name = QLabel(definition.title)
        name.setFont(app_font(16, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        pill = QLabel(f"{status_label} · {status}")
        pill.setObjectName("OrchStatus")
        pill.setFont(app_font(12, QFont.Weight.Medium))
        pill.setStyleSheet(_STATUS)

        meta = QLabel(f"ждут меня: {waiting}")
        meta.setFont(app_font(13))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        if status == WAITING_HUMAN and instance is not None:
            approve = QPushButton("Подтвердить")
            approve.setCursor(Qt.CursorShape.PointingHandCursor)
            approve.setFixedHeight(36)
            approve.setStyleSheet(_START_BTN)
            approve.clicked.connect(lambda: self._decide(instance.id, True))
            reject = QPushButton("Вернуть")
            reject.setCursor(Qt.CursorShape.PointingHandCursor)
            reject.setFixedHeight(36)
            reject.setStyleSheet(_SECONDARY_BTN)
            reject.clicked.connect(lambda: self._decide(instance.id, False))
            actions.addWidget(approve)
            actions.addWidget(reject)
        if status in {READY, COMPLETED} or instance is None:
            start = QPushButton("Старт")
            start.setCursor(Qt.CursorShape.PointingHandCursor)
            start.setFixedHeight(36)
            start.setStyleSheet(_START_BTN)
            start.clicked.connect(lambda _checked=False, did=definition.id: self._start(did))
            actions.addWidget(start)
        actions.addStretch(1)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        top.addWidget(name, 1)
        top.addLayout(actions, 0)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addWidget(pill, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(meta)
        return card

    def _start(self, definition_id: str) -> None:
        _instances, error = start_process(self._user_id, definition_id)
        if error:
            QMessageBox.information(self, "Оркестратор", error)
            return
        self.refresh()

    def _decide(self, instance_id: str, approved: bool) -> None:
        _instances, error = decide(self._user_id, instance_id, approved)
        if error:
            QMessageBox.information(self, "Оркестратор", error)
            return
        self.refresh()

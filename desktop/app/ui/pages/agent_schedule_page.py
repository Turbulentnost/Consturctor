from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ScheduleDraft, ScheduleTriggerSpec, WorkflowRecord
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_SECONDARY = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
"""
_CARD = """
QFrame#ScheduleCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
"""
_FIELD = """
QLineEdit, QTextEdit, QComboBox, QDateTimeEdit, QDoubleSpinBox {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 10px;
    padding: 6px 10px;
}
"""
_CHIP = """
QFrame#TriggerChip {
    background: #E8F3FB;
    border: 1px solid #B7D4E8;
    border-radius: 14px;
}
QFrame#TriggerChip:hover {
    background: #D9ECF8;
}
QPushButton#ChipClose {
    background: transparent;
    color: #1A4A6B;
    border: none;
    border-radius: 10px;
    padding: 0;
}
QPushButton#ChipClose:hover {
    background: rgba(26,74,107,0.10);
}
"""


class AgentSchedulePage(QWidget):
    back_requested = Signal()
    save_requested = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._record: WorkflowRecord | None = None
        self._cards: list[_TriggerChip] = []

        title = QLabel("Паспорт агента")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("Название, цель и когда запускать. Пустой список триггеров — только вручную из чата.")
        subtitle.setFont(app_font(13))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._back = QPushButton("Назад")
        self._back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back.setFixedHeight(36)
        self._back.setStyleSheet(_SECONDARY)
        self._back.clicked.connect(self.back_requested.emit)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Название агента")
        self._name.setFont(app_font(14))
        self._name.setStyleSheet(_FIELD)
        self._goal = QTextEdit()
        self._goal.setPlaceholderText("Цель")
        self._goal.setFont(app_font(13))
        self._goal.setFixedHeight(90)
        self._goal.setStyleSheet(_FIELD)

        self._list = QVBoxLayout()
        self._list.setSpacing(8)
        self._list.setContentsMargins(0, 0, 0, 0)

        add = QPushButton("Добавить триггер")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setFixedHeight(36)
        add.setStyleSheet(_SECONDARY)
        add.clicked.connect(self._on_add_menu)

        self._save = QPushButton("Сохранить")
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.setFixedHeight(40)
        self._save.setFont(app_font(13, QFont.Weight.DemiBold))
        self._save.setStyleSheet(_PRIMARY)
        self._save.clicked.connect(self._on_save)

        form = QFrame()
        form.setObjectName("ScheduleCard")
        form.setStyleSheet(_CARD)
        form_lay = QVBoxLayout(form)
        form_lay.setContentsMargins(20, 18, 20, 18)
        form_lay.setSpacing(10)
        form_lay.addWidget(_field_label("Название"))
        form_lay.addWidget(self._name)
        form_lay.addWidget(_field_label("Цель"))
        form_lay.addWidget(self._goal)
        form_lay.addWidget(_field_label("Когда запускается"))
        form_lay.addLayout(self._list)
        form_lay.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.addWidget(form)
        inner_lay.addStretch(1)
        scroll.setWidget(inner)

        header = QHBoxLayout()
        header.addWidget(title, 1)
        header.addWidget(self._back, 0, Qt.AlignmentFlag.AlignRight)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 8)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(subtitle)
        root.addWidget(scroll, 1)
        root.addWidget(self._save, 0, Qt.AlignmentFlag.AlignRight)

    def load(self, record: WorkflowRecord, draft: ScheduleDraft | None = None) -> None:
        self._record = record
        draft = draft or ScheduleDraft()
        name = (draft.name or record.title or "ИИ-агент").strip()
        if name.casefold() in {"notes", "notes.txt"}:
            name = (record.title or "ИИ-агент").strip()
        goal = (draft.goal or (record.plan.goal if record.plan else "") or "").strip()
        self._name.setText(name)
        self._goal.setPlainText(goal)
        self._clear_cards()
        for spec in draft.triggers:
            self._add_card(spec)

    def current_record(self) -> WorkflowRecord | None:
        return self._record

    def current_draft(self) -> ScheduleDraft:
        return ScheduleDraft(
            name=self._name.text().strip() or "ИИ-агент",
            goal=self._goal.toPlainText().strip(),
            triggers=[card.spec() for card in self._cards],
        )

    def set_busy(self, busy: bool) -> None:
        self._save.setEnabled(not busy)
        self._save.setText("Сохраняю…" if busy else "Сохранить")

    def _on_add_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Каждые 15 мин", lambda: self._add_card(
            ScheduleTriggerSpec(kind="interval", interval_value=15, interval_unit="minutes", once=False)
        ))
        menu.addAction("Ежедневно в 12:00", lambda: self._add_card(
            ScheduleTriggerSpec(kind="datetime", at="12:00", once=False)
        ))
        menu.addAction("По событию", lambda: self._add_and_edit(
            ScheduleTriggerSpec(kind="event", condition="изменён файл или получено сообщение", once=False)
        ))
        sender = self.sender()
        if isinstance(sender, QPushButton):
            menu.exec(sender.mapToGlobal(sender.rect().bottomLeft()))
        else:
            menu.exec()

    def _add_and_edit(self, spec: ScheduleTriggerSpec) -> None:
        chip = self._add_card(spec)
        if chip is not None:
            self._edit_card(chip)

    def _add_card(self, spec: ScheduleTriggerSpec) -> _TriggerChip:
        card = _TriggerChip(spec)
        card.remove_requested.connect(lambda c=card: self._remove_card(c))
        card.edit_requested.connect(lambda c=card: self._edit_card(c))
        self._cards.append(card)
        self._list.addWidget(card)
        return card

    def _edit_card(self, card: _TriggerChip) -> None:
        dialog = _TriggerEditDialog(card.spec(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            card.set_spec(dialog.spec())

    def _remove_card(self, card: _TriggerChip) -> None:
        if card in self._cards:
            self._cards.remove(card)
        card.setParent(None)
        card.deleteLater()

    def _clear_cards(self) -> None:
        for card in list(self._cards):
            self._remove_card(card)

    def _on_save(self) -> None:
        if self._record is None:
            return
        draft = self.current_draft()
        for spec in draft.triggers:
            if spec.kind == "interval" and spec.interval_value <= 0:
                QMessageBox.information(self, "Триггер", "Укажите интервал больше нуля.")
                return
            if spec.kind == "event" and not spec.condition.strip():
                QMessageBox.information(self, "Триггер", "Опишите событие: изменён файл или получено сообщение.")
                return
            if spec.kind == "datetime" and not spec.at.strip():
                QMessageBox.information(self, "Триггер", "Укажите дату и время запуска.")
                return
        self.save_requested.emit(self._record, draft)


class _TriggerChip(QFrame):
    remove_requested = Signal(object)
    edit_requested = Signal(object)

    def __init__(self, spec: ScheduleTriggerSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TriggerChip")
        self.setStyleSheet(_CHIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._spec = spec
        self._label = QLabel(trigger_chip_label(spec))
        self._label.setFont(app_font(13, QFont.Weight.Medium))
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: #1A4A6B; background: transparent;")
        close = QPushButton("×")
        close.setObjectName("ChipClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(22, 22)
        close.setToolTip("Убрать")
        close.clicked.connect(lambda: self.remove_requested.emit(self))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(self._label, 1)
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 8, 8)
        layout.addLayout(top)

    def spec(self) -> ScheduleTriggerSpec:
        return self._spec

    def set_spec(self, spec: ScheduleTriggerSpec) -> None:
        self._spec = spec
        self._label.setText(trigger_chip_label(spec))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint()) if hasattr(event, "position") else None
            if child is None or not isinstance(child, QPushButton):
                self.edit_requested.emit(self)
                return
        super().mousePressEvent(event)


class _TriggerEditDialog(QDialog):
    def __init__(self, spec: ScheduleTriggerSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Когда запускается")
        self._kind = QComboBox()
        self._kind.addItem("Через время после последнего запуска", "interval")
        self._kind.addItem("Событие (файл, сообщение)", "event")
        self._kind.addItem("В определённое время", "datetime")
        self._kind.setCurrentIndex(max(0, self._kind.findData(spec.kind)))
        self._kind.setStyleSheet(_FIELD)

        self._interval_value = QDoubleSpinBox()
        self._interval_value.setRange(0.1, 10_000)
        self._interval_value.setDecimals(1)
        self._interval_value.setValue(spec.interval_value or 1)
        self._interval_value.setStyleSheet(_FIELD)
        self._interval_unit = QComboBox()
        self._interval_unit.addItem("мин.", "minutes")
        self._interval_unit.addItem("час.", "hours")
        self._interval_unit.addItem("дн.", "days")
        unit_index = self._interval_unit.findData(spec.interval_unit or "hours")
        self._interval_unit.setCurrentIndex(max(0, unit_index))
        self._interval_unit.setStyleSheet(_FIELD)

        self._condition = QLineEdit()
        self._condition.setPlaceholderText("Например: изменён файл на шаре")
        self._condition.setText(spec.condition)
        self._condition.setStyleSheet(_FIELD)

        self._at = QDateTimeEdit()
        self._at.setCalendarPopup(True)
        self._at.setDisplayFormat("dd.MM.yyyy HH:mm")
        parsed = _parse_dt(spec.at)
        self._at.setDateTime(parsed or QDateTime.currentDateTime().addDays(1))
        self._at.setStyleSheet(_FIELD)
        self._once = QCheckBox("Один раз")
        self._once.setChecked(bool(spec.once) if spec.kind == "datetime" else False)

        self._message = QLineEdit()
        self._message.setPlaceholderText("Задача при запуске (кратко)")
        self._message.setText(spec.message)
        self._message.setStyleSheet(_FIELD)

        interval_row = QWidget()
        interval_lay = QHBoxLayout(interval_row)
        interval_lay.setContentsMargins(0, 0, 0, 0)
        interval_lay.addWidget(self._interval_value)
        interval_lay.addWidget(self._interval_unit)

        event_row = QWidget()
        event_lay = QVBoxLayout(event_row)
        event_lay.setContentsMargins(0, 0, 0, 0)
        event_lay.addWidget(self._condition)

        dt_row = QWidget()
        dt_lay = QHBoxLayout(dt_row)
        dt_lay.setContentsMargins(0, 0, 0, 0)
        dt_lay.addWidget(self._at)
        dt_lay.addWidget(self._once)

        self._stack = QStackedWidget()
        self._stack.addWidget(interval_row)
        self._stack.addWidget(event_row)
        self._stack.addWidget(dt_row)
        self._kind.currentIndexChanged.connect(self._sync_stack)
        self._sync_stack()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._kind)
        layout.addWidget(self._stack)
        layout.addWidget(self._message)
        layout.addWidget(buttons)

    def _sync_stack(self) -> None:
        kind = str(self._kind.currentData() or "interval")
        self._stack.setCurrentIndex({"interval": 0, "event": 1, "datetime": 2}.get(kind, 0))

    def spec(self) -> ScheduleTriggerSpec:
        kind = str(self._kind.currentData() or "interval")
        at = spec_at = ""
        if kind == "datetime":
            if not self._once.isChecked():
                spec_at = self._at.dateTime().toString("HH:mm")
            else:
                spec_at = self._at.dateTime().toUTC().toString(Qt.DateFormat.ISODate)
            at = spec_at
        return ScheduleTriggerSpec(
            kind=kind,
            message=self._message.text().strip(),
            interval_value=float(self._interval_value.value()),
            interval_unit=str(self._interval_unit.currentData() or "hours"),
            condition=self._condition.text().strip(),
            at=at,
            once=self._once.isChecked() if kind == "datetime" else False,
        )


def trigger_chip_label(spec: ScheduleTriggerSpec) -> str:
    kind = (spec.kind or "").strip().casefold()
    if kind == "interval":
        value = spec.interval_value or 0
        unit = (spec.interval_unit or "hours").strip().casefold()
        amount = int(value) if float(value).is_integer() else value
        if unit == "minutes":
            return "каждую минуту" if amount == 1 else f"каждые {amount} мин"
        if unit == "days":
            return "ежедневно" if amount == 1 else f"каждые {amount} дн."
        return "каждый час" if amount == 1 else f"каждые {amount} ч"
    if kind == "datetime":
        clock = _time_from_at(spec.at)
        if (not spec.once or not _has_date(spec.at)) and clock:
            return f"ежедневно в {clock}"
        pretty = _pretty_datetime(spec.at)
        return pretty or "в указанное время"
    condition = (spec.condition or spec.message or "").strip()
    if len(condition) > 60:
        condition = condition[:57].rsplit(" ", 1)[0].strip() + "…"
    return f"при событии: {condition}" if condition else "по событию"


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(app_font(12, QFont.Weight.DemiBold))
    label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    return label


def _parse_dt(value: str) -> QDateTime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    clock = _time_from_at(raw)
    if clock and not _has_date(raw):
        hour, minute = clock.split(":")
        now = QDateTime.currentDateTime()
        now.setTime(now.time())
        parsed = QDateTime(now.date(), now.time())
        parsed.setTime(now.time())
        from PySide6.QtCore import QTime
        parsed.setTime(QTime(int(hour), int(minute)))
        return parsed
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return QDateTime.fromSecsSinceEpoch(int(parsed.timestamp()))


def _time_from_at(value: str) -> str:
    import re

    match = re.search(r"(\d{1,2})[:.](\d{2})", value or "")
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _has_date(value: str) -> bool:
    import re

    return bool(re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}", value or ""))


def _pretty_datetime(value: str) -> str:
    import re

    raw = (value or "").strip()
    clock = _time_from_at(raw)
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        return f"{match.group(3)}.{match.group(2)}.{match.group(1)}" + (f" {clock}" if clock else "")
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw)
    if match:
        return f"{int(match.group(1)):02d}.{int(match.group(2)):02d}.{match.group(3)}" + (
            f" {clock}" if clock else ""
        )
    return clock or raw[:40]
